"""Temporary Prometheus and Nagios wiring and a Grafana incident dashboard."""
import base64
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
from urllib.parse import urlencode
from urllib.request import Request, urlopen


PROMETHEUS = "http://127.0.0.1:9090"
GRAFANA = "http://127.0.0.1:3000"
QUERIES = {
    "p95_ms": "quotelab_probe_window_p95_seconds * 1000",
    "sample_count": "quotelab_probe_window_count",
    "cpu_percent": "quotelab_host_cpu_execution_ratio * 100",
    "runnable": "quotelab_host_runnable_tasks",
    "failed_total": "quotelab_probe_failure_total",
    "skipped_total": "quotelab_probe_skipped_total",
}
ALERT_NAME = "QuoteLabHighLatency"


def get_json(url):
    with urlopen(url, timeout=6) as response:
        return json.load(response)


def system(*args):
    subprocess.run(args, check=True, stdout=subprocess.DEVNULL)


@contextmanager
def install_monitoring(directory):
    prometheus = Path("/etc/prometheus/prometheus.yml")
    rules = Path("/etc/prometheus/quotelab-incident.rules.yml")
    nagios = Path("/etc/nagios4/conf.d/quotelab-incident.cfg")
    original = prometheus.read_bytes()
    if rules.exists() or nagios.exists() or b"rule_files:" in original:
        raise RuntimeError("The lab monitoring files already exist or the Prometheus layout has changed")
    modified = f'rule_files:\n  - "{rules}"\n\n'.encode() + original.rstrip() + b"""
  - job_name: quotelab-incident
    scrape_interval: 5s
    static_configs:
      - targets: ["127.0.0.1:19817"]
"""
    try:
        rules.write_bytes((directory / "alert.yml").read_bytes())
        rules.chmod(0o644)
        prometheus.write_bytes(modified)
        system("promtool", "check", "config", str(prometheus))
        system("systemctl", "reload", "prometheus")
        nagios.write_bytes((directory / "nagios.cfg").read_bytes())
        nagios.chmod(0o644)
        system("nagios4", "-v", "/etc/nagios4/nagios.cfg")
        system("systemctl", "reload", "nagios4")
        yield
    finally:
        if prometheus.read_bytes() == modified:
            prometheus.write_bytes(original)
            rules.unlink(missing_ok=True)
            system("promtool", "check", "config", str(prometheus))
            system("systemctl", "reload", "prometheus")
        if nagios.exists():
            nagios.unlink()
            system("nagios4", "-v", "/etc/nagios4/nagios.cfg")
            system("systemctl", "reload", "nagios4")


def alert():
    for item in get_json(PROMETHEUS + "/api/v1/alerts")["data"]["alerts"]:
        if item["labels"]["alertname"] == ALERT_NAME:
            return {"state": item["state"], "active_at": item["activeAt"], "value": float(item["value"])}
    return {"state": "inactive"}


def nagios_sample():
    status = Path("/var/lib/nagios4/status.dat").read_text()
    for match in re.finditer(r"^servicestatus\s*\{([^}]*)\}", status, flags=re.M):
        values = dict(line.strip().split("=", 1) for line in match[1].splitlines() if "=" in line)
        if values.get("host_name") == "quotelab-incident" and values.get("service_description") == "QuoteLab HTTP health":
            timestamp = int(values["last_check"])
            if timestamp:
                return {"time": timestamp, "state": int(values["current_state"]), "output": values["plugin_output"]}
    return None


def schedule_nagios_check(timestamp):
    """Ask the running Nagios daemon for a fresh check of this one service."""
    command = f"[{timestamp}] SCHEDULE_FORCED_SVC_CHECK;quotelab-incident;QuoteLab HTTP health;{timestamp}\n"
    descriptor = os.open("/var/lib/nagios4/rw/nagios.cmd", os.O_WRONLY | os.O_NONBLOCK)
    with os.fdopen(descriptor, "w") as pipe:
        pipe.write(command)


def query_series(start, end):
    data = {}
    for name, query in QUERIES.items():
        params = urlencode({"query": query, "start": start, "end": end, "step": 5})
        series = get_json(PROMETHEUS + "/api/v1/query_range?" + params)["data"]["result"]
        if len(series) != 1:
            raise RuntimeError(f"Expected one Prometheus series for {name}, got {len(series)}")
        data[name] = [[t, float(value)] for t, value in series[0]["values"]]
    return data


class Grafana:
    uid = "quotelab-incident"

    def __init__(self):
        config = Path("/etc/grafana/devops-lab-admin.env").read_text()
        value = next(line.split("=", 1)[1] for line in config.splitlines()
                     if line.startswith("GF_SECURITY_ADMIN_PASSWORD="))
        password = shlex.split(value)[0]
        token = base64.b64encode(f"admin:{password}".encode()).decode()
        self.headers = {"Authorization": "Basic " + token, "Content-Type": "application/json"}

    def request(self, path, payload=None):
        body = None if payload is None else json.dumps(payload).encode()
        with urlopen(Request(GRAFANA + path, body, self.headers), timeout=10) as response:
            return json.load(response)

    def save(self, start, end, threshold, events):
        datasource = next(item for item in self.request("/api/datasources") if item["type"] == "prometheus")
        ref = {"type": "prometheus", "uid": datasource["uid"]}
        panels = []
        for index, (title, unit, query) in enumerate((
            ("Quote request rolling p95", "ms", QUERIES["p95_ms"]),
            ("QuoteLab host CPU execution", "percent", QUERIES["cpu_percent"]),
            ("Runnable tasks on the QuoteLab VM", "short", QUERIES["runnable"]),
            ("Requests in the rolling p95 window", "short", QUERIES["sample_count"]),
        )):
            targets = [{"refId": "A", "expr": query, "datasource": ref, "legendFormat": title}]
            if index == 0:
                targets.append({"refId": "B", "expr": f"vector({threshold})", "datasource": ref,
                                "legendFormat": "Latency alert threshold"})
            panels.append({
                "id": index + 1, "title": title, "type": "timeseries", "datasource": ref,
                "gridPos": {"x": (index % 2) * 12, "y": (index // 2) * 9, "w": 12, "h": 9},
                "targets": targets, "fieldConfig": {"defaults": {"unit": unit}, "overrides": []},
            })
        from datetime import datetime, timezone
        time_range = {key: datetime.fromtimestamp(value, timezone.utc).isoformat()
                      for key, value in (("from", start), ("to", end))}
        annotation_source = {"type": "grafana", "uid": "-- Grafana --"}
        dashboard = {
            "uid": self.uid, "title": "QuoteLab | From alert to recovery", "schemaVersion": 39,
            "tags": ["quotelab", "lab"], "time": time_range, "panels": panels,
            "annotations": {"list": [{"builtIn": 1, "datasource": annotation_source, "enable": True,
                                     "hide": False, "name": "Annotations & Alerts", "type": "dashboard"}]},
        }
        self.request("/api/dashboards/db", {"dashboard": dashboard, "overwrite": True})
        for event in events:
            self.request("/api/annotations", {"dashboardUID": self.uid, "time": round(event["time"] * 1000),
                                              "text": event["label"], "tags": ["quotelab-incident"]})
        actual = self.request("/api/dashboards/uid/" + self.uid)
        annotations = self.request("/api/annotations?" + urlencode({
            "dashboardUID": self.uid, "from": round(start * 1000), "to": round(end * 1000),
        }))
        return {"title": actual["dashboard"]["title"], "panels": len(actual["dashboard"]["panels"]),
                "annotations": len(annotations), "from": time_range["from"], "to": time_range["to"]}
