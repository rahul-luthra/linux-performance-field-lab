# Reproduce the local storage / NFS investigation

[Live report](https://rahul-luthra.github.io/linux-performance-field-lab/storage.html) · [Measured findings](../STORAGE_CASE_STUDY.md) · [Summary](../results/storage/summary.json)

This is an opt-in two-VM lab. It changes NFS, firewall, fstab, transient systemd services and the server's network queue. Use isolated machines with no important workloads. These scripts are tailored to the measured Oracle Linux 9 environment, not a general installer.

## Prerequisites and layout

- Two reachable Linux VMs, SSH user `rahul`, matching UID/GID 1000, passwordless sudo, Python 3.9+, Java 17 JDK, nfs-utils, sysstat, iproute/tc, systemd/cgroup v2 and firewalld. Required tools were already installed in the measured environment; no package download was necessary for this extension.
- The measured NIC is `enp0s3`, firewall zone `public`, backing block device `/dev/sda`. Inspect and adjust these assumptions before replaying. I/O control depends on cgroup/kernel/device support. `network.py` requires the signed `sch_netem` and `sch_prio` kernel modules; it loads them before injection.
- Client application classes live at `/opt/linux-performance-field-lab/storage`; runtime scripts/evidence at `/home/rahul/nfs-storage-lab`. Copy `monitor.py` to that runtime root and all files in this directory into its `storage` subdirectory on both VMs.
- Keep the operator's SSH private key on the controller. The VMs do not need an inter-VM private key. Validate both host fingerprints out of band and use a dedicated known-hosts file. Clones need unique network identity, machine ID and SSH host keys; this was corrected on the new clone before testing. The new NFS VM was switched to headless boot to free RAM.

Replace `SERVER_IP` and `CLIENT_IP` in the following commands with your own lab addresses. Do not literally use these labels.

## Set up the share

On the server, from the runtime root:

```sh
sudo python3 storage/setup_nfs.py server --server SERVER_IP --client CLIENT_IP
```

On the client:

```sh
sudo python3 storage/setup_nfs.py client --server SERVER_IP --client CLIENT_IP
sudo mkdir -p /opt/linux-performance-field-lab/storage
sudo javac -d /opt/linux-performance-field-lab/storage storage/StorageLab.java
```

The server exports `/srv/nfs/perf-lab` to one client with `rw,sync,root_squash,no_subtree_check,sec=sys`. It uses NFSv4 only and opens TCP 2049 only for that client. The client mounts it at `/mnt/perf-lab-nfs` using NFSv4.2, hard/TCP and nosuid/nodev/noexec, with `_netdev,nofail` in fstab. The negotiated measured rsize/wsize were 262144 bytes. A preexisting different mount/configuration needs manual review: the setup script does not reconcile arbitrary existing infrastructure.

On this measured host SELinux stayed enforcing; its existing `nfs_export_all_rw` boolean was already enabled. The script does not disable SELinux or alter that boolean. Matching numeric identities are required. Ordinary-user write/read was verified; a direct root-owned write was denied by root squashing and directory permissions. Root squashing is not protection against a privileged allowed client impersonating UID 1000. `sec=sys` provides neither encryption nor strong client-user authentication.

## Run the measured protocol

Use a fresh runtime output directory and no existing case data files. The harness refuses to overwrite prior cases, and Java uses CREATE_NEW for its data file. Preserve old evidence first; remove only the known test data using the cleanup command below before replaying. A fresh clone of the runtime directory can be used with `run_all.py --remote-root /home/rahul/another-lab`; install the same scripts and monitor there on both machines.

From the operator's workstation, with this repository available:

```sh
python storage/run_all.py --client CLIENT_IP --server SERVER_IP --key /path/to/private-key --known-hosts /path/to/known_hosts
python storage/run_all.py --client CLIENT_IP --server SERVER_IP --key /path/to/private-key --known-hosts /path/to/known_hosts --repeat-io
```

The first command executes seven cases: local baseline, NFS baseline, two 20-ms server-egress NFS-delay runs, recovery, competing I/O and capped competing I/O. The second adds unrestricted/capped repetitions and a final quiet recovery. The original evidence is sequential, not randomized. Each process has a finite runtime. A 12-minute independent systemd timer restores the network queue if the controller is interrupted. The controller also restores it in `finally`. Hard mounts can still leave a process waiting during a real server outage; this lab injects delay, not outages.

The application listens only on loopback port 8089. A transient unit runs it as `rahul`, with a 32-MiB JVM heap, 192-MiB cgroup memory limit and 100-second runtime. It creates a 256-record ring file (16 MiB); each 64-KiB record includes an increasing sequence and CRC32. A synchronized handler writes and calls `force(false)` before returning timing/checksum headers. A new file is initialized before each measurement; warmup is excluded.

Arrivals are scheduled at four per second rather than waiting for the previous response. There are 120 measured arrivals and eight maximum client workers, with three-second request timeouts. All request outcomes and scheduling lag are saved; failures remain in denominators. HTTP p95 uses the central [2,28)-second scheduled-arrival window, 104 arrivals per measured case. It is a nearest-rank percentile of successful responses; inspect error counts alongside it.

The server background writer uses two workers, random aligned 8-KiB O_DIRECT/O_DSYNC writes, a preinitialized 64-MiB file, 128-MiB memory limit and bounded 40/45-second process/service deadlines. The limited case sets `IOWriteIOPSMax=/dev/sda 50`. Block IOPS differ from application write calls: an 8-KiB write can split into multiple block writes. Recorded `io.max`, `io.stat`, write counts and elapsed time are retained. The limit is an experimental intervention, not an assumed fix.

Network injection uses a priority queue/filter scoped to IPv4 NFS replies from TCP source port 2049 to the one client. Both baseline and delayed cases use the same queue hierarchy, with 0 versus 20 ms netem delay. SSH and unrelated traffic are not selected. `network.py` rejects unrecognized initial queue policies and saves/restores the expected fq_codel policy, including its MTU-derived quantum. It is specific to this single-interface lab topology.

## Evidence and analysis

Client per-mount `/proc/self/mountstats` deltas preserve operation counts, transmissions, major timeouts, cumulative queue, RTT and execution milliseconds. The analyzer divides cumulative deltas by completed operations; no completions means unknown timing, not zero latency. Reset counters are omitted. Negative retransmission differences caused by in-flight work remain unknown. RPC snapshots cover the full measured request window, independently of the trimmed HTTP window.

Both VMs retain host JSON and iostat text; the client adds nfsiostat and the server adds nfsd counters. CPU/PSI, device read/write await, flush counters, queue and busy time help separate layers. Device R/W await is completion-weighted across intervals; flushes are reported separately. Busy percentage is not a universal saturation threshold. UTC alignment is approximate, not atomic or proof of one-way delay. First local/NFS baseline observers predated explicit end-qdisc capture; network snapshots are absent there. The baseline NFS independent server readback was collected after the cohort and before data cleanup; all later NFS readbacks were captured by the finish hook.

On each VM, export text evidence with role labels instead of addresses:

```sh
python3 storage/check_setup.py --role client --cleanup-data  # client only
python3 storage/export_evidence.py --role client --client-address CLIENT_IP --server-address SERVER_IP
# On server, use --role server for both commands.
```

Download the two `results/storage-client.zip` / `storage-server.zip` archives. Extract them under the repository's `results` directory, then:

```sh
python3 -m unittest discover -s storage -p test_storage.py -v
python3 storage/analyze_storage.py
python3 build_pages.py
```

Open `storage-report.html` locally or publish the generated `docs/storage.html` with the other Pages files. The static report has embedded data, experiment controls and request-JSON downloads; it does not expose either VM. `build_release.py` uses named public-file allowlists. Synthetic .bin files, compiled .class files, keys and raw JVM dumps are excluded.

## Cleanup and remaining setup

`check_setup.py --cleanup-data` removes only known 16-MiB case files and the 64-MiB background file after validating exact expected sizes. It records share access, root-write denial, SELinux, NFS/firewall policy and restored queue state. It leaves the NFS service/export, firewall rule and persistent mount configured for future labs. Save/export the evidence before removing a runtime folder. The measured cleanup removed 16 MiB client-local and 208 MiB server-side synthetic files. No application or background workload remains running.

To retire the share later, unmount it on the client and remove its single fstab entry; remove the specific server export/config files and the single source-restricted firewall rule. Do not stop a shared NFS service or remove unrelated rules without checking its other consumers. Keep original configuration backups and inspect the final state.

## Limits and references

Same physical host, short sequential cases, small offered workload, client-side load generation, caches, nearly full server filesystem and late baseline drift limit generalization. `force(false)` on a remote file has no Java-specification physical-device guarantee. Checksums/readbacks do not establish crash durability. We did not prove a natural storage fault or a successful disk-latency mitigation.

- [Oracle Linux NFS server setup](https://docs.oracle.com/en/operating-systems/oracle-linux/9/nfs/configuring-nfs-server.html)
- [Export options](https://docs.oracle.com/en/operating-systems/oracle-linux/9/nfs/editing-exports-file_task.html)
- [Linux I/O statistics](https://www.kernel.org/doc/html/latest/admin-guide/iostats.html)
- [cgroup v2 I/O controls](https://docs.kernel.org/admin-guide/cgroup-v2.html)
- [tc-netem](https://man7.org/linux/man-pages/man8/tc-netem.8.html)
- [Java FileChannel.force contract](https://docs.oracle.com/en/java/javase/17/docs/api/java.base/java/nio/channels/FileChannel.html#force(boolean))
