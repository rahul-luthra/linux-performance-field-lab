"""Record one AWX rollout under continuous client traffic."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import Request, urlopen

from incident.awx_lab import AWX
from patching.awx_rollout import TERMINAL, action_events


NODES = ["patch-canary", "patch-peer"]


def read_awx(awx, path):
    for attempt in range(4):
        try:
            return awx.request(path)
        except (TimeoutError, URLError):
            if attempt == 3:
                raise
            time.sleep(3)


def pool(config, node=None, state=None):
    url = config["pool_url"] + "/pool"
    body = None
    method = "GET"
    if node:
        url += "/" + node
        body = json.dumps({"state": state}).encode()
        method = "PUT"
    request = Request(url, data=body, method=method,
                      headers={"Authorization": "Bearer " + config["token"], "Content-Type": "application/json"})
    with urlopen(request, timeout=8) as response:
        return json.load(response)["active"]


def collect(awx, objects, config, directory, fault):
    timeline = []

    def mark(name, timestamp=None, **fields):
        timeline.append({"event": name, "time": time.time() if timestamp is None else timestamp, **fields})
        print(name, flush=True)

    start = time.time()
    mark("baseline")
    time.sleep(8)
    assert pool(config) == NODES
    endpoint = f"workflow_job_templates/{objects['workflow']}/launch/"
    marker = f"patch-lab-{time.time_ns()}"
    try:
        launch = awx.request(endpoint, {"extra_vars": {"inject_fault": fault, "patch_run_marker": marker}})
    except (TimeoutError, URLError):
        launch = None
        for _ in range(8):
            items = read_awx(awx, f"workflow_job_templates/{objects['workflow']}/workflow_jobs/?order_by=-id")["results"]
            launch = next((item for item in items if marker in json.dumps(item.get("extra_vars", ""))), None)
            if launch:
                break
            time.sleep(4)
        if not launch:
            raise RuntimeError("AWX did not confirm a timed-out workflow launch")
    workflow = launch["id"]
    if launch.get("ignored_fields"):
        raise RuntimeError("AWX ignored a requested workflow option")
    mark("workflow", job=workflow)
    deadline = time.monotonic() + 820
    approved = False
    approval_requested = None
    last = {}
    seen = {}
    while time.monotonic() < deadline:
        status = read_awx(awx, f"workflow_jobs/{workflow}/")
        nodes = read_awx(awx, f"workflow_jobs/{workflow}/workflow_nodes/")["results"]
        for node in nodes:
            name = node["identifier"]
            job = node["job"]
            if not job:
                continue
            summary = node.get("summary_fields", {}).get("job", {})
            outcome = summary.get("status")
            if seen.get(name) != outcome:
                print(f"AWX {name} #{job}: {outcome}", flush=True)
                seen[name] = outcome
            if outcome in TERMINAL and name not in last:
                resource = "workflow_approvals" if name == "approval" else "jobs"
                details = read_awx(awx, f"{resource}/{job}/")
                if name == "approval":
                    evidence = []
                else:
                    for attempt in range(3):
                        try:
                            evidence = action_events(awx, job)
                            break
                        except (TimeoutError, URLError):
                            if attempt == 2:
                                raise
                if name == "preflight" and outcome == "successful" and not evidence:
                    continue
                last[name] = {key: details[key] for key in ("id", "status", "started", "finished")}
                timeline.extend(evidence)
                if name == "approval" and outcome == "successful" and not approved:
                    stamp = datetime.fromisoformat(details["finished"].replace("Z", "+00:00")).timestamp()
                    mark("approved", timestamp=stamp)
                    approved = True
            if name == "approval" and outcome == "pending" and not approved:
                ready = {event["node"] for event in timeline if event["event"] == "preflight"}
                if ready != set(NODES):
                    continue
                if approval_requested is None or time.monotonic() - approval_requested > 45:
                    approval_requested = time.monotonic()
                    try:
                        awx.request(f"workflow_approvals/{job}/approve/", {})
                    except (TimeoutError, URLError, RuntimeError):
                        print("Approval response was delayed; checking the existing approval job.", flush=True)
        if status["status"] in TERMINAL:
            break
        time.sleep(3)
    else:
        awx.request(f"workflow_jobs/{workflow}/cancel/", {})
        raise RuntimeError("AWX did not complete within the lab window")

    if not approved:
        raise RuntimeError(f"Workflow {workflow} never passed the approval gate: {last}")
    recovery = None
    if fault:
        if (last.get("canary", {}).get("status") != "failed" or
            last.get("containment", {}).get("status") != "successful" or
            any(node["job"] for node in nodes if node["identifier"] == "peer")):
            raise RuntimeError(f"The failure path did not isolate the canary: {last}")
        assert pool(config) == ["patch-peer"]
        assert any(event["event"] == "application_check" and event["node"] == "patch-canary"
                   and int(event["quote"]) == 0 for event in timeline)
        mark("awaiting_snapshot_restore")
        flag = directory / "restore.json"
        deadline = time.monotonic() + 160
        while time.monotonic() < deadline and not flag.exists():
            time.sleep(2)
        if not flag.exists():
            raise RuntimeError("The operator did not report a verified snapshot restore")
        recovery = json.loads(flag.read_text())
        assert recovery["snapshot"] == "pre-patch-baseline"
        assert recovery["canary_version"] == recovery["peer_version"] == config["package"]["patch_from"]
        assert recovery["canary_quote"] == 42 and recovery["canary_boot_changed"]
        assert pool(config) == ["patch-peer"]
        assert pool(config, "patch-canary", "ready") == NODES
        mark("restored_and_rejoined", node="patch-canary")
    else:
        if status["status"] != "successful" or any(last.get(name, {}).get("status") != "successful"
                                                   for name in ("canary", "peer")):
            raise RuntimeError(f"Normal workflow did not patch both targets: {last}")
        assert pool(config) == NODES
    time.sleep(10)
    mark("end")
    return {"start": start, "end": timeline[-1]["time"], "workflow": workflow, "status": status["status"],
            "jobs": last, "timeline": sorted(timeline, key=lambda row: row["time"]), "restore": recovery}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("scenario", choices=("normal", "failed"))
    args = parser.parse_args()
    directory = args.directory.resolve()
    config = json.loads((directory / "config.json").read_text())
    objects = json.loads((directory / "objects.json").read_text())
    raw = directory / f"{args.scenario}-requests.jsonl"
    stop = directory / f"{args.scenario}.stop"
    if stop.exists():
        stop.unlink()
    if args.scenario == "failed" and (directory / "restore.json").exists():
        raise RuntimeError("Remove the previous restore acknowledgement before retrying the trial")
    probe = Path(__file__).with_name("probe.py")
    with subprocess.Popen([sys.executable, str(probe), config["pool_url"], str(raw), str(stop)]) as client:
        try:
            result = collect(AWX(), objects, config, directory, args.scenario == "failed")
        finally:
            stop.touch()
            try:
                client.wait(timeout=8)
            except subprocess.TimeoutExpired:
                client.terminate()
                client.wait(timeout=8)
    result["requests"] = [row for line in raw.read_text().splitlines()
                          if result["start"] <= (row := json.loads(line))["time"] <= result["end"]]
    result["package"] = config["package"]
    result["awx_version"] = objects["awx_version"]
    (directory / f"{args.scenario}.json").write_text(json.dumps(result, indent=2) + "\n")
    print(f"Captured {len(result['requests'])} client observations for the {args.scenario} trial.", flush=True)


if __name__ == "__main__":
    main()
