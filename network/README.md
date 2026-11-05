# Reproduce the Linux network investigation

[Interactive report](https://rahul-luthra.github.io/linux-performance-field-lab/network.html) · [Case study](../NETWORK_CASE_STUDY.md) · [Measured summary](../results/network/summary.json)

The measured setup uses two Oracle Linux 9.7 VMs on one physical host, each with two logical CPUs and about 1.5 GiB RAM. The original application VM is the client; the former NFS VM hosts a small in-memory HTTP service and iperf3. No third VM is needed. The Windows controller holds the SSH key; no inter-VM private key is installed.

## Prerequisites and scope

This is an opt-in isolated lab: it temporarily changes a network queue, adds two single-client firewall rules, starts bounded services and captures headers of synthetic test traffic. It assumes SSH account `rahul` with UID/GID 1000, passwordless sudo, interface `enp0s3`, public firewalld zone, cgroup v2/systemd, Python 3.9+, tcpdump, tc/iproute and iperf3. Inspect and adjust these assumptions before using another machine. SELinux remains enforcing. Traffic is HTTP/TCP on a trusted lab LAN; DNS, TLS and production application behavior are outside scope.

Check `df -h /` and available memory first. The measured client/server had about 1.3/1.8 GiB free (95%/93% filesystem usage). We required at least 512 MiB free; application payloads are generated in memory and packet capture is short text output, so no bulk payload files are saved. Existing files were not deleted to free space. iperf3 3.9-17.el9_8.1 was installed from the configured Oracle package repository on both VMs; tcpdump 4.99.0 was already present.

On both VMs create `/home/rahul/network-field-lab/network`. Copy the root `monitor.py` into `/home/rahul/network-field-lab` and this directory's Python files into its `network` subdirectory. The runtime root is fixed in `run_lab.py`; change it consistently for another environment. Keep SSH host verification enabled; the moved VMs' ED25519 keys matched the previously saved identities.

If replaying the original NFS setup after an IP-address change, `preflight.py` refreshes only its specific export, source-restricted port-2049 rule and fstab entry, with backups. Run on the server first and then the client:

```sh
sudo python3 network/preflight.py --role server --client CLIENT_IP --server SERVER_IP --previous-client OLD_CLIENT_IP --previous-server OLD_SERVER_IP
# On the client, use --role client with the same four address arguments.
```

Replace all address labels with real IPv4 addresses. This helper expects the previously configured `/srv/nfs/perf-lab` export. For unchanged addresses, pass the current addresses as previous ones too. It is specific to this repository's earlier NFS lab; a fresh network-only environment should record equivalent preflight checks without invoking its NFS migration. The measured migration restored ordinary-user share access and preserved its existing synchronous, root-squashed NFSv4 policy.

## Execute the protocol

Start with fresh case-output directories. The controller refuses to overwrite existing case directories. Preserve old evidence first; use a new runtime directory (and update the controller's base) for another complete cohort. It does not delete prior measurements.

From the operator workstation:

```sh
python network/run_lab.py --client CLIENT_IP --server SERVER_IP --key /path/to/private-key --known-hosts /path/to/known_hosts
```

The intended ten-case sequence is: baseline; two 50-ms server-egress delay cases; recovery; two 1% random-loss cases; recovery; 5-Mbit/s reply bandwidth limit; 100-ms handler pause; final recovery. Each case changes one factor. Every normal mode must be checked for absence of residual delay/loss/rate before interpreting it.

The measured first cohort exposed a reset bug: same-kind `tc qdisc replace` retained an omitted rate setting on this kernel. Its runs 09/10 therefore still had the previous 5-Mbit/s cap. Both are retained and visibly marked as excluded from single-factor attribution. The final source deletes/recreates the isolated netem leaf on each case, records before/after queue snapshots, and does not rely on omitted options to clear state. Two corrected cases were then run using:

```sh
python network/run_lab.py --client CLIENT_IP --server SERVER_IP --key /path/to/private-key --known-hosts /path/to/known_hosts --corrected-tail
```

That option adds cases 11/12 without overwriting the first cohort. It is an audit/recovery option for this measured history; a fresh run with the final code should use the normal ten-case protocol. An initial corrected-tail launch stopped before measurement because a stopped iperf transient unit remained failed/loaded; the controller now resets its failed unit state before starting. No outcome data came from that failed launch.

## What is measured

`serve.py` serves fixed 1-KiB and 512-KiB in-memory payloads on TCP 8090. Its optional 100-ms sleep is measured separately as handler elapsed time and thread CPU time; the sleep is application waiting, not CPU stress. It binds only the lab address. The service runs as `rahul`, with 192-MiB memory, 64-task and 900-second runtime limits, NoNewPrivileges, read-only system files and a private temporary directory. iperf3 uses the same bounds on TCP 5201.

`client.py` performs eight warmup requests, then offers 100 small requests at five per second with up to eight workers. Each opens a new TCP connection with a five-second socket-operation timeout; no DNS/TLS is included. It records connect/header/body/end-to-end times, scheduling lag, handler timings, response size and expected bytes/CRC32. New connections mean server-egress delay can affect both SYN-ACK and response exchanges. Five separate 512-KiB downloads follow. Warmup is excluded and bulk transfers are analyzed separately.

The reported HTTP percentiles are nearest-rank values from successful responses whose scheduled arrival lies in [2,18) seconds: 80 arrivals per complete case. All failures remain in error denominators. A small sample can miss rare failures; missing timings remain unknown. `analyze_network.py` reports total correctness counts separately and embeds request/host data into a standalone report.

After HTTP/bulk, an eight-second reverse TCP iperf3 test offers at most 100 Mbit/s. Received throughput and sender retransmissions come from its JSON. This is a bounded diagnostic workload, not maximum-link-capacity certification. TCP retransmissions count resent segments, not unique lost packets. Baseline and delay-only retries demonstrate why retry counts alone do not prove deliberate loss.

`observe.py` records both hosts' counters and `ss -tin` about once per second for at most 50 seconds, ending earlier at the controller's stop marker. Socket output is filtered to the two test ports. Early observers were launched before that source filter was tightened; the export additionally strips all non-test connection records from every case. TCP RTT summary uses only server-side port-5201 observations, including iperf control and data sockets. Those repeated samples are correlated and belong to the separate throughput test, not the HTTP requests. CPU means select the approximate central HTTP window using UTC snapshots, with no claim of atomic clock alignment.

Four pings per case are an independent ICMP control. The fault intentionally affects only IPv4 TCP server responses from source ports 8090/5201 to the single client. Ping, SSH and NFS do not enter that fault queue. Therefore healthy ping does not disprove a problem in this selected application traffic.

A tcpdump transient unit records at most 400 packets or 48 seconds, with a 64-byte snapshot and no payload print/hex mode. Exported journal text shows packet-header metadata; raw pcap/payload files are not generated. The early packet limit may finish capture before bulk/iperf; it is supporting evidence, not a complete conversation or a source of full-session loss rates.

## Fault injection and safety bounds

`impair.py` verifies the initial fq_codel parameters and saves its quantum. It creates a priority tree with an isolated netem leaf for the two selected ports. Other traffic uses a separate fq_codel leaf. Delay, loss and rate are applied server-egress only. Initial runs reused the same leaf so raw counters accumulate; analysis differences consecutive saved counters. Corrected runs recreate it and have explicit before/after counters. Interface segmentation/checksum/receive offloads remain as found and are recorded. Software queue packet/drop units may differ from physical wire packets; sender-egress netem is not a perfect model of an actual network path.

A 15-minute independent systemd timer restores the original fq_codel policy if the controller fails. Its finally block also restores the queue, stops both services, and removes runtime firewall rules. The two single-client firewall rules also expire after 900 seconds. The timer does not itself delete the state file, so an interrupted run requires inspecting the restored queue and saved state before another setup. The measured restored quantum is 1514, matching this run's preflight; the prior NFS session used a different recorded quantum.

## Export, verify and publish

After cleanup, on each VM:

```sh
python3 network/finish.py --role client   # use server on the server
python3 network/export_evidence.py --role client --client CLIENT_IP --server SERVER_IP
```

Download `results/network-client.zip` and `results/network-server.zip`, then extract both into the repository's `results` directory. Export is a named text-file allowlist: lab addresses/hostname strings become role labels, and SSH/NFS socket records are omitted. No keys, credentials, packet payloads or raw pcaps are included. Keep the original raw runtime evidence on the VMs for audit.

```sh
python3 -m unittest discover -s network -p test_network.py -v
python3 network/analyze_network.py
python3 build_pages.py
```

Open `network-report.html` offline or use `docs/network.html` on GitHub Pages. The report includes all twelve measured runs, explicitly marks the two protocol deviations, and offers request-JSON downloads. The main branch also includes raw de-identified evidence and summaries. The existing tagged review release remains an older snapshot.

`finish.py` verifies restored fq_codel, absent test processes/listeners/state and continued ordinary-user NFS access, and records final disk/SELinux/firewall/service state. Temporary test services/firewall rules are removed; iperf3 remains installed and the existing NFS share remains mounted. This lab creates no large synthetic disk files. Disk expansion/cleanup is still useful future maintenance for these nearly full VMs. Client CPU varied substantially: early central HTTP windows averaged roughly 54–79%, versus about 6% in the corrected tail. This background activity limits attribution of every tail-latency difference; no natural client CPU root cause was established.

## References

- [netem manual and limitations](https://man7.org/linux/man-pages/man8/tc-netem.8.html)
- [ESnet iperf3 invocation, pacing, reverse mode and JSON output](https://software.es.net/iperf/invoking.html)
- [Linux I/O counter definitions used by the existing host collector](https://www.kernel.org/doc/html/latest/admin-guide/iostats.html)
