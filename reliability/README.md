# Reproduce the Linux service reliability lab

The frontend listens on loopback TCP 8190 on the client VM. The price dependency listens on TCP 8191 on the second VM. The probe also runs on the frontend VM, so the quote timing includes the remote dependency call and local frontend handling. It excludes a remote client's trip to the frontend. Both services use Python's standard library and run as the ordinary lab user.

Use two isolated Linux VMs with Python 3.9 or later, systemd and firewalld. The controller expects an SSH account named `rahul`, noninteractive sudo on each VM, the server's public firewall zone, verified host keys, and free test ports. Point it at the two IPv4 addresses from a machine with OpenSSH and Python.

```sh
python reliability/run_lab.py --client CLIENT_IP --server SERVER_IP --key /path/to/key --known-hosts /path/to/known_hosts --out results/reliability/replay.json
```

The controller uses run-specific transient units with a 240-second runtime cap. A runtime firewalld rule allows TCP 8191 from the client alone and expires after 300 seconds. In the cleanup block the controller stops its services, removes the rule and deletes its staged files. The recorded evidence confirms both test ports are closed and the rule is absent. The controller rejects an occupied port or a preexisting matching firewall rule.

The six phases use 24 quote requests at four per second and six concurrent liveness probes each. The initial frontend uses a 1,500 ms dependency socket timeout. The controller injects a 650 ms sleep in the dependency, stops and then starts the dependency in a fresh transient unit, and repeats the slow scenario with a 200 ms timeout. It ends by clearing the delay. The dependency's socket timeout applies to blocking operations on the dependency connection. The separate 250 ms lab target is measured by the quote probe from request start to response completion.

Capture includes request IDs, response codes, body validation, latency, scheduler lag, systemd state and filtered journal output. The controller redacts the two lab IP addresses from the journal. The report builder checks each probe result against the corresponding journal entry, confirms that one frontend PID was active at both boundaries of every phase, and verifies cleanup. p95 uses nearest rank across all quote outcomes. A response meets the lab target only if it is HTTP 200, contains the expected quote, and arrives within 250 ms.

The published evidence is in [capture.json](../results/reliability/capture.json). To build the published report, run from the repository root:

```sh
python reliability/build_report.py
python build_pages.py
```

For a replay, preserve the published capture and substitute the replay file in a separate checkout before rebuilding. See the [case study](../RELIABILITY_CASE_STUDY.md), [systemd-run documentation](https://www.freedesktop.org/software/systemd/man/latest/systemd-run.html), and [firewall-cmd documentation](https://firewalld.org/documentation/man-pages/firewall-cmd.html).
