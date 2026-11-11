"""Run a bounded reliability experiment over SSH and save de-identified evidence."""
import argparse
import ipaddress
import json
from pathlib import Path
import shlex
import subprocess
import uuid

FRONT_PORT, PEER_PORT = 8190, 8191
SOURCE = Path(__file__).resolve().parent


class Lab:
    def __init__(self, args):
        self.client, self.server = str(args.client), str(args.server)
        self.options = [
            "-i", Path(args.key).resolve().as_posix(), "-o", "BatchMode=yes",
            "-o", "IdentitiesOnly=yes", "-o", "ConnectTimeout=8",
            "-o", "StrictHostKeyChecking=yes",
            "-o", 'UserKnownHostsFile="' + Path(args.known_hosts).resolve().as_posix() + '"',
        ]
        name = "reliability-" + uuid.uuid4().hex[:10]
        self.runtime = "/home/rahul/" + name
        self.front = name + "-front"
        self.peers = [name + "-dependency-a", name + "-dependency-b"]
        self.rule = (f'rule family="ipv4" source address="{self.client}/32" '
                     f'port port="{PEER_PORT}" protocol="tcp" accept')
        self.directories = []
        self.units = []
        self.rule_added = False

    def ssh(self, address, *command, check=True):
        return subprocess.run(
            ["ssh", *self.options, "rahul@" + address, shlex.join(command)],
            check=check, capture_output=True, text=True, timeout=35,
        )

    def setup(self):
        for address, port in [(self.client, FRONT_PORT), (self.server, PEER_PORT)]:
            assert not self.listeners(address, port), f"Lab port {port} already in use"
            self.ssh(address, "mkdir", "-m", "700", self.runtime)
            self.directories.append(address)
            subprocess.run(["scp", *self.options, "service.py", "probe.py",
                            "rahul@" + address + ":" + self.runtime + "/"],
                           cwd=SOURCE, check=True, timeout=35)
        query = self.firewall("query", check=False)
        assert query.returncode == 1 and query.stdout.strip() == "no", "Unexpected firewall state"
        self.rule_added = True
        self.firewall("add", "--timeout=300")

    def firewall(self, operation, *extra, check=True):
        return self.ssh(self.server, "sudo", "-n", "firewall-cmd", "--zone=public",
                        f"--{operation}-rich-rule={self.rule}", *extra, check=check)

    def listeners(self, address, port):
        return self.ssh(address, "ss", "-H", "-ltn", f"sport = :{port}").stdout.strip()

    def setting(self, address, value):
        script = "from pathlib import Path; import sys; Path(sys.argv[1]).write_text(sys.argv[2])"
        self.ssh(address, "python3", "-c", script, self.runtime + "/setting", str(value))

    def launch(self, address, unit, role, bind, port, *extra):
        self.units.append((address, unit))
        self.ssh(address, "sudo", "-n", "systemd-run", "--collect", f"--unit={unit}",
                 "--property=User=rahul", "--property=RuntimeMaxSec=240",
                 "--property=MemoryMax=64M", "--property=TasksMax=32",
                 "--property=NoNewPrivileges=yes", "/usr/bin/python3", self.runtime + "/service.py",
                 role, "--bind", bind, "--port", str(port), "--setting", self.runtime + "/setting",
                 *extra)

    def wait_for_http(self, address, port):
        self.ssh(self.client, "python3", "-B", self.runtime + "/probe.py",
                 "--wait-host", address, "--port", str(port))

    def state(self, address, unit):
        result = self.ssh(address, "systemctl", "show", "-p", "ActiveState", "-p", "MainPID",
                          unit, check=False)
        fields = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
        return dict(active_state=fields.get("ActiveState", "unknown"),
                    main_pid=int(fields.get("MainPID", 0)))

    def phase(self, name, peer, delay, timeout):
        before = self.state(self.client, self.front)
        dependency = self.state(self.server, peer)
        result = self.ssh(self.client, "python3", "-B", self.runtime + "/probe.py",
                          "--phase", name, "--port", str(FRONT_PORT))
        after = self.state(self.client, self.front)
        capture = json.loads(result.stdout)
        print(f"{name}: {sum(row['correct'] for row in capture['requests'])}/24 correct", flush=True)
        return dict(name=name, delay_ms=delay, timeout_ms=timeout, frontend_before=before,
                    frontend_after=after, dependency=dependency, **capture)

    def journal(self, address, *units):
        selector = [arg for unit in units for arg in ("-u", unit)]
        return self.ssh(address, "sudo", "-n", "journalctl", *selector, "--no-pager",
                        "-o", "short-iso", "--utc", "--no-hostname").stdout

    def measure(self):
        self.setting(self.server, 0)
        self.setting(self.client, 1500)
        self.launch(self.server, self.peers[0], "dependency", self.server, PEER_PORT)
        self.wait_for_http(self.server, PEER_PORT)
        self.launch(self.client, self.front, "frontend", "127.0.0.1", FRONT_PORT,
                    "--peer", self.server, "--peer-port", str(PEER_PORT))
        self.wait_for_http("127.0.0.1", FRONT_PORT)
        phases = [self.phase("healthy", self.peers[0], 0, 1500)]
        self.setting(self.server, 650)
        phases.append(self.phase("slow-dependency", self.peers[0], 650, 1500))
        self.ssh(self.server, "sudo", "-n", "systemctl", "stop", self.peers[0])
        phases.append(self.phase("dependency-stopped", self.peers[0], None, 1500))
        self.setting(self.server, 0)
        self.launch(self.server, self.peers[1], "dependency", self.server, PEER_PORT)
        self.wait_for_http(self.server, PEER_PORT)
        phases.append(self.phase("dependency-restored", self.peers[1], 0, 1500))
        self.setting(self.client, 200)
        self.setting(self.server, 650)
        phases.append(self.phase("slow-with-timeout", self.peers[1], 650, 200))
        self.setting(self.server, 0)
        phases.append(self.phase("final-recovery", self.peers[1], 0, 200))
        return phases

    def cleanup(self):
        errors = []
        for address, unit in reversed(self.units):
            try:
                self.ssh(address, "sudo", "-n", "systemctl", "stop", unit, check=False)
            except (OSError, subprocess.SubprocessError) as exc:
                errors.append(str(exc))
        if self.rule_added:
            try:
                self.firewall("remove", check=False)
            except (OSError, subprocess.SubprocessError) as exc:
                errors.append(str(exc))
        for address in self.directories:
            try:
                self.ssh(address, "rm", "-f", "--", *(self.runtime + "/" + name for name in
                                                      ("service.py", "probe.py", "setting")))
                self.ssh(address, "rmdir", "--", self.runtime)
            except (OSError, subprocess.SubprocessError) as exc:
                errors.append(str(exc))
        if errors:
            raise RuntimeError("Cleanup requires inspection: " + "; ".join(errors))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client", type=ipaddress.IPv4Address, required=True)
    parser.add_argument("--server", type=ipaddress.IPv4Address, required=True)
    parser.add_argument("--key", required=True)
    parser.add_argument("--known-hosts", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.client == args.server or args.out.exists():
        parser.error("Use two distinct hosts and a new output file")
    lab = Lab(args)
    try:
        lab.setup()
        phases = lab.measure()
    except subprocess.CalledProcessError as exc:
        raise SystemExit(exc.stderr) from exc
    finally:
        lab.cleanup()
    journal = lab.journal(lab.client, lab.front) + lab.journal(lab.server, *lab.peers)
    for value, label in [(lab.client, "lab-frontend"), (lab.server, "lab-dependency")]:
        journal = journal.replace(value, label)
    evidence = dict(phases=phases, journal=journal, requests_per_second=4,
                    success_threshold_ms=250, cleanup={
                        "frontend_listener_absent": not lab.listeners(lab.client, FRONT_PORT),
                        "dependency_listener_absent": not lab.listeners(lab.server, PEER_PORT),
                        "temporary_firewall_rule_absent":
                            lab.firewall("query", check=False).stdout.strip() == "no",
                        "frontend": lab.state(lab.client, lab.front),
                        "dependencies": [lab.state(lab.server, unit) for unit in lab.peers],
                    })
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
