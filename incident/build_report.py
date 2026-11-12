"""Build the static incident replay from the measured, public capture."""
from collections import Counter
from html import escape
import json
from math import ceil
from pathlib import Path
from statistics import mean


ROOT = Path(__file__).resolve().parents[1]
CAPTURE = ROOT / "results/incident/capture.json"
TEMPLATE = Path(__file__).with_name("report-template.html")


def phase_summary(rows):
    correct = [row for row in rows if row["correct"]]
    elapsed = sorted(row["elapsed_ms"] for row in correct)
    assert elapsed, "Each phase must have successful samples"
    return {
        "requests": len(rows),
        "successful": len(correct),
        "p95": round(elapsed[ceil(0.95 * len(elapsed)) - 1], 1),
        "handler_wall": round(mean(row["handler_wall_ms"] for row in correct), 1),
        "handler_cpu": round(mean(row["handler_cpu_ms"] for row in correct), 1),
        "status_counts": dict(Counter(str(row["status"]) for row in rows)),
    }


def summarize(data):
    at = {event["key"]: event["time"] for event in data["events"]}
    assert at["baseline"] < at["load"] < at["firing"] < at["approval"] < at["stop"] < at["clear"] < at["end"]
    assert data["awx"]["status"] == "successful"
    assert all(step["status"] == "successful" for step in data["awx"]["steps"].values())
    ranges = {
        "baseline": [at["baseline"] + 5, at["load"]],
        "incident": [at["load"] + 5, at["stop"]],
        "recovery": [at["clear"], at["end"]],
    }
    phases = {}
    for phase, (start, end) in ranges.items():
        rows = [row for row in data["requests"] if start <= row["started"] and row["finished"] < end]
        cpu = [value for t, value in data["prometheus"]["cpu_percent"] if start <= t < end]
        phases[phase] = {
            **phase_summary(rows), "start": start, "end": end,
            "mean_cpu": round(mean(cpu), 1),
        }
    def observed_state(timestamp):
        return next((item["state"] for item in reversed(data["alert_transitions"])
                     if item["time"] <= timestamp), "inactive")

    checks = [check for check in data["nagios"]
              if at["firing"] <= check["time"] < at["stop"] and observed_state(check["time"]) == "firing"]
    ok_checks = sum(check["state"] == 0 for check in checks)
    assert ok_checks, "Expected at least one Nagios OK check during an observed firing period"
    state_changes = [item for item in data["alert_transitions"] if at["firing"] <= item["time"] < at["stop"]]
    skipped = data["prometheus"]["skipped_total"]
    return {
        "phases": phases,
        "detection_seconds": round(at["firing"] - at["load"], 1),
        "remediation_seconds": round(at["stop"] - at["firing"], 1),
        "clear_seconds": round(at["clear"] - at["stop"], 1),
        "total_seconds": round(at["clear"] - at["load"], 1),
        "nagios_ok_during_alert": ok_checks,
        "nagios_other_during_alert": len(checks) - ok_checks,
        "nagios_total": len(data["nagios"]),
        "skipped_offers": int(skipped[-1][1] - skipped[0][1]),
        "alert_interrupted_before_stop": any(item["state"] == "inactive" for item in state_changes),
    }


def build():
    capture = json.loads(CAPTURE.read_text())
    summary = summarize(capture)
    model = {key: capture[key] for key in ("events", "alert_transitions", "prometheus", "start", "end", "threshold_ms", "awx", "nagios")}
    model.update(summary)
    baseline, incident, recovery = (summary["phases"][phase] for phase in ("baseline", "incident", "recovery"))
    story = {
        "FINDING": f"In this run, p95 rose from {baseline['p95']:,.0f} to {incident['p95']:,.0f} ms. "
                   f"Nagios reported OK on {summary['nagios_ok_during_alert']} checks while the latency alert was firing and the workers were still active.",
        "RECOVERY": f"AWX stopped the lab CPU workers after an approval step. "
                    f"The alert cleared {summary['clear_seconds']:.0f} seconds later, and stable recovery p95 was {recovery['p95']:,.0f} ms.",
        "DIAGNOSIS": f"Mean host CPU execution rose from {baseline['mean_cpu']:.1f}% to {incident['mean_cpu']:.1f}%. "
                     f"Mean Java handler wall time rose from {baseline['handler_wall']:.1f} to {incident['handler_wall']:.1f} ms, "
                     f"while handler CPU time went from {baseline['handler_cpu']:.1f} to {incident['handler_cpu']:.1f} ms. "
                     "The running workers, the gap between wall time and CPU time, and recovery after stopping the workers support CPU contention as the cause in this lab.",
        "BASELINE": f"{baseline['p95']:,.0f} ms",
        "INCIDENT": f"{incident['p95']:,.0f} ms",
        "RECOVERY_VALUE": f"{recovery['p95']:,.0f} ms",
        "DETECTION": f"{summary['detection_seconds']:.0f} s",
        "DISPATCH": f"The probe's skipped-offer counter rose by {summary['skipped_offers']} across the sampled window.",
    }
    html = TEMPLATE.read_text(encoding="utf-8")
    for marker, value in story.items():
        html = html.replace(f"@@{marker}@@", escape(value))
    payload = json.dumps(model, separators=(",", ":"), ensure_ascii=False).replace("<", r"\u003c")
    html = html.replace("@@MODEL@@", payload)
    (ROOT / "incident-report.html").write_text(html, encoding="utf-8")
    (CAPTURE.parent / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")


if __name__ == "__main__":
    build()
