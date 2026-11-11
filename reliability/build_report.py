"""Verify captured reliability evidence and render the standalone report."""
from collections import Counter
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXPECTED = {
    "healthy": (200, "ok"),
    "slow-dependency": (200, "ok"),
    "dependency-stopped": (503, "dependency_connection_refused"),
    "dependency-restored": (200, "ok"),
    "slow-with-timeout": (504, "dependency_timeout"),
    "final-recovery": (200, "ok"),
}


def summarize(capture):
    events = {}
    for line in capture["journal"].splitlines():
        offset = line.find('{"time":')
        if offset != -1:
            event = json.loads(line[offset:])
            assert event["request_id"] not in events, "Duplicate application log entry"
            events[event["request_id"]] = event
    assert [phase["name"] for phase in capture["phases"]] == list(EXPECTED)
    assert len(events) == 144
    pid = capture["phases"][0]["frontend_before"]["main_pid"]
    assert pid > 0
    for phase in capture["phases"]:
        name = phase["name"]
        status, cause = EXPECTED[name]
        rows, live = phase["requests"], phase["liveness"]
        assert len(rows) == 24 and len(live) == 6
        assert all(row["correct"] for row in live), name
        for state in (phase["frontend_before"], phase["frontend_after"]):
            assert state == {"active_state": "active", "main_pid": pid}, name
        dependency_state = "inactive" if name == "dependency-stopped" else "active"
        assert phase["dependency"]["active_state"] == dependency_state, name
        for row in rows:
            event = events[row["request_id"]]
            assert row["status"] == event["status"] == status, name
            assert event["cause"] == cause and event["timeout_ms"] == phase["timeout_ms"], name
            assert row["correct"] if status == 200 else row["error"] == cause, name
        durations = sorted(row["elapsed_ms"] for row in rows)
        correct = sum(row["correct"] for row in rows)
        within = sum(row["correct"] and row["elapsed_ms"] <= capture["success_threshold_ms"]
                     for row in rows)
        phase["summary"] = {
            "responses": dict(Counter(str(row["status"]) for row in rows)),
            "correct": correct, "within_target": within, "liveness_ok": len(live),
            "p95_ms": durations[math.ceil(0.95 * len(durations)) - 1],
            "max_lag_ms": max(row["lag_ms"] for row in rows),
        }
        phase["journal_events"] = [events[row["request_id"]] for row in rows]
    cleanup = capture["cleanup"]
    for key in ("frontend_listener_absent", "dependency_listener_absent", "temporary_firewall_rule_absent"):
        assert cleanup[key], key
    for state in [cleanup["frontend"], *cleanup["dependencies"]]:
        assert state == {"active_state": "inactive", "main_pid": 0}
    return capture


def main():
    source = ROOT / "results/reliability/capture.json"
    data = summarize(json.loads(source.read_text(encoding="utf-8")))
    template = (ROOT / "reliability/report-template.html").read_text(encoding="utf-8")
    payload = json.dumps(data, allow_nan=False).replace("<", "\\u003c")
    (ROOT / "reliability-report.html").write_text(
        template.replace("__LAB_DATA__", payload), encoding="utf-8")
    for phase in data["phases"]:
        print(phase["name"], phase["summary"])


if __name__ == "__main__":
    main()
