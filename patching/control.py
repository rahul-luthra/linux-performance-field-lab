"""Controller-side snapshot and verification for the two disposable targets."""
import argparse
import base64
import json
from pathlib import Path
import subprocess
import time


PORTS = {"patch-canary": 2321, "patch-peer": 2322}
REMOTE_STATUS = """
import json
from pathlib import Path
import subprocess
from urllib.request import urlopen
with urlopen("http://127.0.0.1:8080/quote", timeout=3) as response:
    quote = json.load(response)
version = subprocess.check_output(["dpkg-query","-W","tzdata"], text=True).split()[-1]
boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
print(json.dumps({"node":quote["node"], "quote":quote["quote"], "version":version, "boot":boot}))
"""


class Controller:
    def __init__(self, args):
        self.host = args.host
        self.windows = ["ssh", "-F", args.windows_profile, "-o", "ConnectTimeout=18", "windows-devops"]
        self.client = [
            "ssh", "-i", str(args.identity), "-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes",
            "-o", "StrictHostKeyChecking=yes", "-o", "ConnectTimeout=8",
            "-o", f"UserKnownHostsFile={args.known_hosts}",
        ]

    def target(self, name):
        return self.client + ["-p", str(PORTS[name]), f"labpatch@{self.host}"]

    def status(self, name, wait=0):
        deadline = time.monotonic() + wait
        while True:
            try:
                result = subprocess.run(self.target(name) + ["python3 -"], input=REMOTE_STATUS.encode(),
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=13)
            except subprocess.TimeoutExpired:
                result = None
            if result is not None and result.returncode == 0:
                data = json.loads(result.stdout)
                assert data["node"] == name
                return data
            if time.monotonic() >= deadline:
                error = result.stderr.decode(errors="replace")[:240] if result is not None else "SSH timed out"
                raise RuntimeError(f"{name} status did not become available: {error}")
            time.sleep(2)

    def snapshot(self, name, action):
        poweroff = subprocess.run(self.target(name) + ["sudo -n systemctl poweroff"], timeout=15)
        if poweroff.returncode not in (0, 255):
            raise RuntimeError(f"Graceful shutdown failed for {name}")
        script = (
            "$ErrorActionPreference='Stop'; $ProgressPreference='SilentlyContinue'; "
            "$stage=Join-Path $env:USERPROFILE 'patch-rollout-lab'; "
            f"& (Join-Path $stage 'snapshot.ps1') -Name '{name}' -Action '{action}'; exit 0"
        )
        encoded = base64.b64encode(script.encode("utf-16le")).decode()
        command = f"powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -EncodedCommand {encoded}"
        reply = subprocess.check_output(self.windows + [command], timeout=110).decode(errors="replace")
        value = next(json.loads(line) for line in reply.splitlines() if line.startswith("{"))
        assert value["node"] == name and value["action"] == action
        return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True)
    parser.add_argument("--windows-profile", required=True)
    parser.add_argument("--identity", type=Path, required=True)
    parser.add_argument("--known-hosts", type=Path, required=True)
    parser.add_argument("--baseline-version", default="2024a-2ubuntu1")
    parser.add_argument("--patched-version", default="2026e-0ubuntu0.24.04.1")
    parser.add_argument("--out", type=Path)
    parser.add_argument("action", choices=("take", "reset", "recover"))
    args = parser.parse_args()
    control = Controller(args)
    baseline = args.baseline_version
    if args.action == "recover":
        canary_before = control.status("patch-canary")
        peer = control.status("patch-peer")
        assert canary_before["quote"] == 0 and canary_before["version"] == args.patched_version
        assert peer["quote"] == 42 and peer["version"] == baseline
        started = time.monotonic()
        snapshot = control.snapshot("patch-canary", "restore")
        canary = control.status("patch-canary", wait=95)
        assert canary["quote"] == 42 and canary["version"] == baseline and canary["boot"] != canary_before["boot"]
        result = {"snapshot": snapshot["snapshot"], "canary_version": canary["version"],
                  "canary_previous_version": canary_before["version"], "peer_version": peer["version"],
                  "canary_quote": canary["quote"], "canary_boot_changed": True,
                  "vbox_seconds": snapshot["seconds"], "operator_seconds": round(time.monotonic() - started, 3)}
        if args.out:
            args.out.write_text(json.dumps(result) + "\n")
        print(json.dumps(result), flush=True)
        return

    for name in PORTS:
        before = control.status(name, wait=55)
        if args.action == "take":
            assert before["quote"] == 42 and before["version"] == baseline
        action = "take" if args.action == "take" else "restore"
        result = control.snapshot(name, action)
        after = control.status(name, wait=95)
        assert after["quote"] == 42 and after["version"] == baseline and after["boot"] != before["boot"]
        print(json.dumps({**result, "version": after["version"], "quote": after["quote"]}), flush=True)


if __name__ == "__main__":
    main()
