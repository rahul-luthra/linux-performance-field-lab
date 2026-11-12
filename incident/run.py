"""Run the two-host incident once and export a public, credential-free capture."""
import argparse
from contextlib import ExitStack, contextmanager
from datetime import datetime
import json
from pathlib import Path
import subprocess
import time

from awx_lab import AWX
from monitoring import Grafana, alert, install_monitoring, nagios_sample, query_series, schedule_nagios_check


THRESHOLD_MS = 500
FINISHED = {"successful", "failed", "error", "canceled"}


@contextmanager
def background(command, log):
    with log.open("w") as output:
        process = subprocess.Popen(command, stdout=output, stderr=output)
        try:
            yield process
        finally:
            process.terminate()
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def operator_ssh(directory, target):
    return [
        "ssh", "-F", "/dev/null", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
        "-o", f"UserKnownHostsFile={directory / 'known_hosts'}", "-o", "ConnectTimeout=8",
        "-o", "IdentitiesOnly=yes", "-i", str(directory / "operator"), target,
    ]


def record_incident(awx, objects, ssh, output, version):
    events = []
    alerts = []
    checks = {}
    last_nagios_request = 0

    def mark(key, label, timestamp=None):
        event = {"key": key, "label": label, "time": time.time() if timestamp is None else timestamp}
        events.append(event)
        print(label, flush=True)
        return event["time"]

    def observe():
        nonlocal last_nagios_request
        now = int(time.time())
        if now - last_nagios_request >= 10:
            schedule_nagios_check(now)
            last_nagios_request = now
        observed = alert()
        if not alerts or observed["state"] != alerts[-1]["state"]:
            alerts.append({"time": time.time(), **observed})
        check = nagios_sample()
        if check:
            checks[check["time"]] = check
        return observed

    start = mark("baseline", "Started recording the healthy baseline")
    while time.time() < start + 45:
        if observe()["state"] == "firing":
            raise RuntimeError("The latency rule fired during baseline")
        time.sleep(2)
    if observe()["state"] != "inactive":
        raise RuntimeError("The latency rule was still pending at the end of baseline")
    if not any(t >= start and check["state"] == 0 for t, check in checks.items()):
        raise RuntimeError("Nagios did not record a healthy baseline check")

    launch = subprocess.check_output(ssh + ["start"], text=True, timeout=12)
    fault = mark("load", "Started four CPU workers under a 140% CPU quota", float(launch.splitlines()[-1]))
    firing = None
    while time.time() < fault + 100:
        state = observe()
        if state["state"] == "firing":
            firing = mark("firing", "Prometheus latency alert fired")
            break
        time.sleep(2)
    if firing is None:
        raise RuntimeError("The alert did not fire after introducing the lab workload")

    workflow = awx.launch("workflow_job_templates", objects["workflow"])
    mark("workflow", "Launched the AWX incident workflow")
    approved = False
    workflow_data = None
    nodes = []
    try:
        while time.time() < fault + 280:
            observe()
            workflow_data = awx.request(f"workflow_jobs/{workflow}/")
            nodes = awx.request(f"workflow_jobs/{workflow}/workflow_nodes/")["results"]
            if workflow_data["status"] in FINISHED:
                break
            approval = next((node for node in nodes if node["identifier"] == "approval" and node["job"]), None)
            if approval and not approved:
                good_check = any(t >= firing and check["state"] == 0 for t, check in checks.items())
                approval_job = awx.request(f"workflow_approvals/{approval['job']}/")
                if approval_job["status"] == "pending" and good_check and alerts[-1]["state"] == "firing":
                    diagnostic = next(node for node in nodes if node["identifier"] == "diagnose")
                    diagnosis = awx.job_output(diagnostic["job"])
                    if "ActiveState=active" not in diagnosis:
                        raise RuntimeError("AWX could not confirm an active lab load unit")
                    mark("diagnosis", "AWX identified the running CPU workers")
                    awx.request(f"workflow_approvals/{approval['job']}/approve/", {})
                    mark("approval", "Approved stopping the scoped load unit")
                    approved = True
            time.sleep(2)
        if not workflow_data or workflow_data["status"] != "successful" or not approved:
            detail = [(node["identifier"], node.get("summary_fields", {}).get("job", {}).get("status")) for node in nodes]
            raise RuntimeError(f"AWX workflow {workflow} did not succeed: {detail}")
    except BaseException:
        if workflow_data and workflow_data["status"] not in FINISHED:
            awx.request(f"workflow_jobs/{workflow}/cancel/", {})
        raise

    awx_steps = {}
    for node in nodes:
        name = node["identifier"]
        resource = "workflow_approvals" if name == "approval" else "jobs"
        job = awx.request(f"{resource}/{node['job']}/")
        result = [] if name == "approval" else awx.job_output(node["job"])
        awx_steps[name] = {key: job[key] for key in ("id", "status", "started", "finished")}
        awx_steps[name]["output"] = result
    stopped_line = next(line for line in awx_steps["recover"]["output"] if line.startswith("Stopped "))
    stopped = datetime.fromisoformat(stopped_line.split(" at ", 1)[1].replace("Z", "+00:00")).timestamp()
    mark("stop", "AWX stopped the CPU workers", stopped)
    mark("verify", "AWX verified the service and stopped workload")
    cleared = next((item["time"] for item in alerts if item["state"] == "inactive" and item["time"] > stopped), None)
    deadline = stopped + 100
    while cleared is None and time.time() < deadline:
        if observe()["state"] == "inactive":
            cleared = time.time()
        else:
            time.sleep(2)
    if cleared is None:
        raise RuntimeError("Latency alert did not clear after AWX recovery")
    mark("clear", "Prometheus latency alert cleared", cleared)
    while time.time() < cleared + 27:
        if observe()["state"] != "inactive":
            raise RuntimeError("The alert returned during the recovery observation")
        time.sleep(2)
    end = mark("end", "Completed the recovery observation")
    raw = subprocess.check_output(ssh + ["capture"], text=True, timeout=15)
    rows = [json.loads(line) for line in raw.splitlines()]
    capture = {
        "schema": 1, "rate_per_second": 4, "window_seconds": 20, "threshold_ms": THRESHOLD_MS,
        "alert_for_seconds": 15, "keep_firing_seconds": 30, "scrape_seconds": 5, "start": start, "end": end,
        "events": sorted(events, key=lambda event: event["time"]),
        "alert_transitions": alerts, "nagios": [check for t, check in sorted(checks.items()) if start <= t <= end],
        "prometheus": query_series(start, end),
        "requests": [row for row in rows if start <= row["started"] <= end],
        "awx": {"version": version, "workflow": workflow, "status": workflow_data["status"], "steps": awx_steps},
    }
    output.write_text(json.dumps(capture, indent=2) + "\n")
    try:
        capture["grafana"] = Grafana().save(start, end, THRESHOLD_MS, capture["events"])
    except Exception as error:
        print(f"Capture saved; Grafana publishing needs attention: {error}", flush=True)
        raise
    output.write_text(json.dumps(capture, indent=2) + "\n")
    print(f"Verified {len(capture['requests'])} request samples and {len(capture['nagios'])} Nagios checks.", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("target", help="User and address of the QuoteLab VM")
    args = parser.parse_args()
    directory = args.directory.resolve()
    ssh = operator_ssh(directory, args.target)
    monitor_ssh = ssh[:-1] + ["-N", "-o", "ExitOnForwardFailure=yes",
                              "-L", "127.0.0.1:19817:127.0.0.1:9817",
                              "-L", "127.0.0.1:18787:127.0.0.1:8087", args.target]
    with ExitStack() as stack:
        stack.enter_context(background(monitor_ssh, directory / "monitor-forward.log"))
        awx = AWX()
        version = awx.wait_ready()
        objects = json.loads((directory / "awx-objects.json").read_text())
        stack.enter_context(install_monitoring(directory))
        time.sleep(12)
        try:
            record_incident(awx, objects, ssh, directory / "capture.json", version)
        except BaseException:
            subprocess.run(ssh + ["stop"], timeout=15, check=False)
            raise


if __name__ == "__main__":
    main()
