# From Alert to Recovery

[Interactive incident replay](https://rahul-luthra.github.io/linux-performance-field-lab/incident.html) · [Raw capture](../results/incident/capture.json) · [Derived summary](../results/incident/summary.json) · [AWX screenshot](../docs/incident-awx.png) · [Grafana screenshot](../docs/incident-grafana.png)

A constant-rate probe requested quotes while four CPU workers ran on the same two-vCPU Linux VM as QuoteLab. Prometheus evaluated quote latency. Nagios checked the simpler health endpoint. AWX collected process evidence, waited at an approval node, stopped the lab load unit, and verified the service. The operator script watched the alert clear and kept recording through recovery.

## Measured outcome

| Phase | Valid quotes | HTTP p95 | Mean host CPU execution | Java handler wall / CPU time |
|---|---:|---:|---:|---:|
| Baseline | 172 / 172 | 217.4 ms | 38.4% | 164.3 / 152.3 ms |
| Contention | 583 / 583 | 1,768.6 ms | 98.9% | 344.3 / 176.0 ms |
| Recovery | 118 / 118 | 275.6 ms | 47.5% | 179.8 / 166.4 ms |

Prometheus was observed firing 64.1 seconds after load started. AWX workflow 11 diagnosed the workers, passed the approval gate, stopped the load unit, and confirmed that QuoteLab was healthy. The alert was observed clear 49.8 seconds after the unit stopped, including the rule's 30-second hold after the condition dropped away. Nagios reported OK in all 16 captured status snapshots, including four during an observed firing period.

Handler wall time rose much more than actual CPU time. Combined with near-saturated host CPU, four running workers in the diagnostic output, and recovery after removing them, that supports CPU contention as the cause in this run. The healthy baseline briefly crossed the threshold and went pending, then returned to inactive without firing.

## Signals and actions

| Tool | Signal or action |
|---|---|
| Prometheus | Scraped exact nearest-rank p95 over successful quotes completed in the trailing 20 seconds. Evaluated every five seconds with a 500 ms threshold, at least 40 successful samples, and a 15-second hold. Kept firing for 30 seconds after the rule condition dropped away. |
| Grafana | Plotted latency, CPU execution, runnable tasks, and rolling sample count. Annotations recorded the main incident events. |
| Nagios Core | Checked HTTP 200 and the expected body of the health endpoint. The operator requested fresh checks at ten-second intervals through the Nagios command pipe and recorded their status snapshots. |
| AWX | Ran diagnostic, recovery, and verification jobs. The operator script granted workflow approval after finding the active load unit and observing an OK Nagios check during the firing alert. |

## Reproduce the lab

Use two isolated Linux VMs with synchronized clocks. The application VM needs the loopback-only [QuoteLab service](../app/README.md), Python 3, systemd, and an SSH account able to start and stop the named test units. The monitoring VM needs Python 3.9 or later, Prometheus, Grafana, Nagios Core, and [AWX on Kubernetes](https://docs.ansible.com/projects/awx-operator/en/latest/installation/basic-install.html). The scripts use the service names, configuration paths, and AWX deployment names in `awx_lab.py` and `monitoring.py`. Adjust those constants for a different deployment. Verify disk and memory headroom and confirm the AWX execution environment can reach the application VM over SSH.

1. On the application VM, place `probe.py`, `load.py`, `operator-command.sh`, and `target-command.sh` in a private directory owned by the lab account. Make the shell scripts executable. Start QuoteLab and verify that `/health` returns HTTP 200.
2. On the monitoring VM, create a private staging directory and place `awx_lab.py`, `monitoring.py`, `run.py`, `workflow.yml`, `alert.yml`, and `nagios.cfg` there. Generate two separate Ed25519 key pairs named `operator` and `awx` inside that directory. Pin the application VM’s verified Ed25519 host key in `known_hosts`.
3. Authorize the public keys on the application VM with short expiration dates and forced commands. Use `restrict,port-forwarding,permitopen="127.0.0.1:9817",permitopen="127.0.0.1:8087",command="/absolute/lab/path/operator-command.sh"` for the operator key and `restrict,command="/absolute/lab/path/target-command.sh"` for the AWX key. Add the expiration option to each line. Both HTTP endpoints stay on loopback.
4. Start the probe from the application VM's private lab directory.

   ```bash
   sudo systemd-run --collect --unit=quotelab-incident-probe --uid="$(id -u)" \
     --property=RuntimeMaxSec=2400s --property=MemoryMax=96M --property=TasksMax=32 \
     /usr/bin/python3 "$PWD/probe.py" "$PWD/requests.jsonl"
   ```

5. On the monitoring VM, provision the AWX objects from the staging directory with the real target address. The code uses the cluster-only AWX service and reads its administrator credential locally from the Kubernetes secret.

   ```bash
   sudo python3 - 'labuser@lab-address' <<'PY'
   import json
   from pathlib import Path
   import sys
   from awx_lab import AWX
   awx = AWX()
   awx.wait_ready()
   objects = awx.configure(Path.cwd(), sys.argv[1])
   Path("awx-objects.json").write_text(json.dumps(objects))
   PY
   ```

6. Run `sudo python3 run.py "$PWD" labuser@lab-address` from the staging directory. The runner opens two SSH forwards, validates and reloads monitoring configuration, and restores it on exit. It aborts before introducing the load if the alert fires during baseline or is still pending at the end. The worker unit has a five-minute ceiling and both the AWX recovery command and the operator fallback can only stop that unit.
7. Copy the resulting `capture.json` to `results/incident/capture.json`, then run `python incident/build_report.py` and `python build_pages.py` from the repository root. Stop the test units, return QuoteLab to its prior state, remove both temporary authorized keys, and delete the AWX credential and staging keys.

## Interpreting the result

The phase table uses nearest-rank p95 over successful requests that start and finish in each phase. It excludes the first five seconds of baseline and load and begins recovery after the alert clears. Prometheus used a trailing window, so its displayed value can include requests from an earlier phase. Alert firing and clearing are reported as observed by the operator’s polling loop.

The HTTP probe and the app shared a VM. Client scheduling and virtualization can influence end-to-end results, so the capture includes dispatch delay and Java handler wall and CPU times. CPU execution excludes idle, I/O wait, and steal. The alert threshold was chosen after a healthy preflight and checked against the recorded baseline. The measurements describe one controlled incident with synthetic traffic.

All 1,115 recorded quote requests returned HTTP 200 with a valid response. The probe's skipped-offer counter rose by five across the sampled window. The phase table excludes boundary and settling observations.

## AWX preflight findings

The default execution environment tried to pull the moving `latest` tag and stalled. I pinned the workflow to the cached `24.6.1` image with a pull-if-missing policy. A later diagnostic preflight exposed an SSH key formatting error. Preserving the private key’s final newline fixed the AWX credential injection. The pinned, credentialed diagnostic passed before the recorded incident began.

One recovery job also hit the initial 45-second AWX job timeout. I raised the scoped templates to 100 seconds. The transient systemd unit still had its own runtime limit, and the operator stopped the workers when that workflow failed.

The first load trial had no CPU cap. The service’s own health check timed out and the approval gate stayed closed. I stopped the workers and canceled that workflow. A pilot at 125% of one logical CPU produced 470 ms p95 across 126 valid quotes and seven successful health checks. In a later pilot, a 140% cap produced 680 ms p95 across 117 valid quotes and nine successful health checks. I used that cap for the recorded incident and set the lab threshold to 500 ms.
