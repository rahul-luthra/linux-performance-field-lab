"""Build the patching portfolio page from two recorded trials."""
from collections import Counter
from html import escape
import json
from math import ceil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "results" / "patching"
SOURCE = Path(__file__).with_name("report-template.html")


def percentile(values):
    ordered = sorted(values)
    return round(ordered[ceil(len(ordered) * 0.95) - 1], 2)


def find(trial, event, node=None):
    return next(row for row in trial["timeline"]
                if row["event"] == event and (node is None or row.get("node") == node))


def summarize(trial, failed):
    requests = trial["requests"]
    sent = [row for row in requests if row["status"] != "skipped"]
    good = [row for row in sent if row["valid"]]
    sent_times = sorted(row["time"] for row in sent)
    counts = Counter(row["node"] for row in good)
    assert all(counts[name] > 0 for name in ("patch-canary", "patch-peer"))
    assert trial["jobs"]["preflight"]["status"] == trial["jobs"]["approval"]["status"] == "successful"
    assert find(trial, "patched", "patch-canary")["rebooted"]
    before, after = trial["package"]["patch_from"], trial["package"]["patch_to"]
    assert find(trial, "patched", "patch-canary")["version"] == after
    check = find(trial, "application_check", "patch-canary")
    assert int(check["status"]) == 200
    assert int(check["quote"]) == (0 if failed else 42)
    canary_end = find(trial, "restored_and_rejoined" if failed else "rejoined", "patch-canary")["time"]
    canary_start = find(trial, "drain", "patch-canary")["time"]

    def traffic_while_drained(node, start, end):
        other = {"patch-canary": "patch-peer", "patch-peer": "patch-canary"}[node]
        valid = [row for row in good if start + 1 <= row["time"] < end - 2]
        assert valid and all(row["node"] == other for row in valid)
        return len(valid)

    canary_window = traffic_while_drained("patch-canary", canary_start, canary_end)
    peer_window = None
    recovery = None
    if failed:
        assert trial["jobs"]["canary"]["status"] == "failed"
        assert trial["jobs"]["containment"]["status"] == "successful"
        assert "peer" not in trial["jobs"]
        restore = trial["restore"]
        assert restore["canary_previous_version"] == after
        assert restore["canary_version"] == restore["peer_version"] == before
        assert restore["canary_quote"] == 42 and restore["canary_boot_changed"]
        assert any(row["node"] == "patch-canary" and row["time"] >= canary_end for row in good)
        recovery = {"failure_to_rejoin_seconds": round(canary_end - check["time"], 1), **restore}
    else:
        assert trial["status"] == trial["jobs"]["canary"]["status"] == trial["jobs"]["peer"]["status"] == "successful"
        peer_start = find(trial, "drain", "patch-peer")["time"]
        peer_end = find(trial, "rejoined", "patch-peer")["time"]
        assert canary_end < peer_start
        assert find(trial, "patched", "patch-peer")["version"] == after
        assert find(trial, "patched", "patch-peer")["rebooted"]
        peer_window = traffic_while_drained("patch-peer", peer_start, peer_end)
    return {
        "requests": len(sent), "valid": len(good), "errors": len(sent) - len(good),
        "skipped": len(requests) - len(sent), "p95_ms": percentile(row["elapsed_ms"] for row in good),
        "max_probe_gap_seconds": round(max(b - a for a, b in zip(sent_times, sent_times[1:])), 2),
        "duration_seconds": round(trial["end"] - trial["start"], 1), "by_node": dict(counts),
        "canary_drain_seconds": round(canary_end - canary_start, 1), "peer_quotes_while_canary_drained": canary_window,
        "canary_quotes_while_peer_drained": peer_window, "recovery": recovery,
        "workflow": trial["workflow"], "jobs": trial["jobs"],
    }


def timeline_data(trial):
    start = trial["start"]
    interval = 5
    buckets = [[tick, 0, 0, 0] for tick in range(0, ceil(trial["end"] - start) + 1, interval)]
    for row in trial["requests"]:
        index = int((row["time"] - start) // interval)
        column = {"patch-canary": 1, "patch-peer": 2}.get(row["node"], 3) if row["valid"] else 3
        buckets[index][column] += 1
    visible = {"baseline", "workflow", "approved", "drain", "patched", "application_check", "rejoined",
               "contained", "awaiting_snapshot_restore", "restored_and_rejoined", "end"}
    return {
        "buckets": buckets,
        "events": [{**row, "time": round(row["time"] - start, 2)}
                   for row in trial["timeline"] if row["event"] in visible],
    }


def build():
    trials = {name: json.loads((EVIDENCE / f"{name}.json").read_text()) for name in ("normal", "failed")}
    assert trials["normal"]["package"] == trials["failed"]["package"]
    summary = {name: summarize(trial, name == "failed") for name, trial in trials.items()}
    evidence = {name: {**summary[name], **timeline_data(trial)} for name, trial in trials.items()}
    normal, failed = summary["normal"], summary["failed"]
    restore = failed["recovery"]
    package = trials["normal"]["package"]
    fields = {
        "NORMAL_REQUESTS": f"{normal['valid']:,} / {normal['requests']:,}",
        "FAILED_REQUESTS": f"{failed['valid']:,} / {failed['requests']:,}",
        "RECOVERY": f"{restore['failure_to_rejoin_seconds']:.0f} s",
        "PACKAGE": package["patch_package"], "FROM": package["patch_from"], "TO": package["patch_to"],
        "NORMAL_ERRORS": str(normal["errors"]), "FAILED_ERRORS": str(failed["errors"]),
        "NORMAL_SKIPPED": str(normal["skipped"]), "FAILED_SKIPPED": str(failed["skipped"]),
        "MAX_GAP": f"{max(normal['max_probe_gap_seconds'], failed['max_probe_gap_seconds']):.2f}",
    }
    html = SOURCE.read_text(encoding="utf-8")
    for key, value in fields.items():
        html = html.replace(f"@@{key}@@", escape(value))
    data = json.dumps(evidence, separators=(",", ":")).replace("<", r"\u003c")
    html = html.replace("@@DATA@@", data)
    assert "@@" not in html
    (ROOT / "patching-report.html").write_text(html, encoding="utf-8")
    (EVIDENCE / "summary.json").write_text(json.dumps({"package": package, **summary}, indent=2) + "\n")


if __name__ == "__main__":
    build()
