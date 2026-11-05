# The application is slow: network waiting or application waiting?

[Explore the interactive measurements](https://rahul-luthra.github.io/linux-performance-field-lab/network.html) · [Raw summaries](results/network/summary.json) · [Reproduction guide](network/README.md)

## Problem and approach

A slow request can come from network round trips, retransmission/recovery, a bandwidth bottleneck, or work inside the application. We created each condition on an isolated two-VM lab and compared independent observations before choosing an explanation. The goal is diagnostic reasoning with verified recovery, not a claim that a production fault was discovered.

Both Oracle Linux 9.7 VMs have two logical CPUs and about 1.5 GiB RAM, sharing one physical host. The server hosts a Python in-memory HTTP service and iperf3; the client schedules requests and runs the separate throughput tests. Each HTTP response contains known bytes and a checksum. No application disk access, DNS or TLS is in the request path.

## Measured results

There are **12 measured runs: ten valid single-factor experiments and two retained audit runs**. All **1,200 small responses and 60 bulk downloads** passed response-size, known-content and CRC checks. Each run has 100 offered small requests at five per second; HTTP percentiles use 80 central-window arrivals. Five separate 512-KiB downloads follow; the bulk figure is their median. An eight-second reverse TCP iperf3 test then offers at most 100 Mbit/s.

| Run | HTTP p95 ms | Handler p95 ms | Bulk median ms | iperf received Mbit/s | Sender retries | netem drop delta |
|---|---:|---:|---:|---:|---:|---:|
| 01-baseline | 30.95 | 0.29 | 49.90 | 100.13 | 14 | 0 |
| 02-delay-a | 272.40 | 0.36 | 372.74 | 62.98 | 901 | 0 |
| 03-delay-b | 213.37 | 0.42 | 478.88 | 58.23 | 1539 | 0 |
| 04-delay-recovery | 14.61 | 0.28 | 24.70 | 100.48 | 81 | 0 |
| 05-loss-a | 92.04 | 0.83 | 46.31 | 100.46 | 935 | 58 |
| 06-loss-b | 214.05 | 0.55 | 70.91 | 100.13 | 782 | 62 |
| 07-loss-recovery | 22.31 | 0.29 | 52.91 | 99.61 | 11 | 0 |
| 08-bandwidth | 18.86 | 0.30 | 884.73 | 4.81 | 0 | 0 |
| 09-slow-handler **audit only** | 128.22 | 105.13 | 887.12 | 4.81 | 0 | 0 |
| 10-final-recovery **audit only** | 22.50 | 0.65 | 885.52 | 4.80 | 0 | 0 |
| 11-slow-handler-corrected | 110.21 | 102.21 | 19.38 | 100.50 | 2 | 0 |
| 12-final-recovery-corrected | 8.83 | 0.44 | 19.59 | 100.42 | 1 | 0 |

Runs 09/10 retained an unintended 5-Mbit/s rate and are excluded from single-factor attribution. Runs 11/12 are their corrected repetitions. Keeping these measurements makes the protocol correction reviewable.

## Findings and controlled causes

**Delay:** a 50-ms server-egress delay raised the median sampled iperf socket RTT from about 4.6 to 56.1 ms in both repetitions. HTTP p95 rose from 31 to 272/213 ms, while measured handler elapsed p95 remained below 0.5 ms. Removing the delay restored HTTP p95 to 15 ms and throughput to about the offered 100-Mbit/s ceiling. New TCP connections and separate header/body sends incur multiple exchanges, so a 50-ms one-direction intervention does not imply exactly 50 ms added to the complete request. The full HTTP tail also contains scheduling and other waits.

**Loss:** the two 1% random-loss runs recorded 58 and 62 new software-queue drops, with 935 and 782 iperf sender retransmissions. HTTP p95 was 92 and 214 ms. Throughput still reached approximately the offered 100-Mbit/s ceiling; that does not mean every request avoided retransmission waiting. Recovery p95 was 22 ms. A random configuration is not a promise that exactly 1% of observed physical packets will be lost, especially with segmentation offloads.

**Bandwidth:** the 5-Mbit/s response-rate limit reduced received iperf throughput to 4.81 Mbit/s. The 512-KiB download median grew to 885 ms, compared with 53 ms in the preceding recovery. Small-request p95 remained around 19 ms. This is the useful distinction: a large transfer can be bandwidth-limited while a small message still completes quickly. The iperf socket RTT also rose under its sustained load; queueing under that test is different from idle propagation delay.

**Application waiting:** after clearing all network faults, a deliberate 100-ms handler pause produced handler elapsed p95 of 102 ms and HTTP p95 of 110 ms. Thread CPU time stayed small, so this was an application wait rather than CPU exhaustion. Sampled iperf socket RTT was 2.24 ms and received throughput 100.50 Mbit/s. Removing the pause returned HTTP p95 to 8.83 ms, handler elapsed p95 to 0.44 ms and bulk median to 19.59 ms. These corrected runs separate the application wait from the earlier residual rate limit.

## Investigation lessons and protocol correction

The independent queue snapshots caught an implementation assumption: on this kernel, replacing a netem queue with a same-kind configuration retained its prior rate when the rate option was omitted. The intended application-pause and final-recovery cases therefore still had a 5-Mbit/s cap, visible both in `qdisc.txt` and their 4.8-Mbit/s throughput. They could not support a clean single-factor conclusion.

The fix was to delete and recreate only the isolated fault queue between cases, leaving the unrelated-traffic branch intact. The corrected runs retain explicit before/after snapshots showing no delay, loss or rate, plus normal throughput. The final source includes this correction and a separate tail-rerun option. It also resets stopped transient-unit failure state so an earlier iperf stop does not prevent a new launch. One attempted rerun stopped before measurement for that reason; it generated no request dataset.

Retransmissions also occurred in baseline and delay-only runs (14 and 901/1539 respectively), even though their recorded netem drop deltas were zero. Sender retries alone therefore do not prove a configured loss fault or establish where a packet was lost. VM networking, offloads, timing/reordering and TCP behavior require further investigation before assigning those extra retries a natural root cause. Here the known injection settings and queue drop evidence support the controlled loss interpretation.

ICMP ping was outside the fault filter. Its averages ranged roughly 0.7–5.3 ms, influenced by the host conditions, while selected TCP traffic could be much slower. A successful ping establishes limited reachability; it cannot establish that this application's selected traffic is healthy.

## Limits and what the evidence does not settle

The load generator shares the client VM. Its central-window CPU average was roughly 54–79% in early cases and about 6% in the corrected tail. That substantial background variation limits attribution of every HTTP percentile difference. Neither the background CPU cause nor a natural network failure was established. Both VMs share a physical host; the experiment does not reproduce independent physical links or isolate every virtualization effect.

Socket RTT summaries combine server-side iperf control/data socket observations, sampled about once per second; repeated observations are correlated. They describe a separate later throughput window, not the same population as the small HTTP responses. Host snapshots use approximate UTC alignment. Interface/global metrics are contextual, not proof about only one connection.

Both VMs retain their original offload settings, documented in preflight. Faults act at server egress on software packets, not at a physical receiver; netem/TSQ/offload effects limit realism. The 100-Mbit/s offered-rate ceiling is intentional resource bounding, not a measured maximum link rate. Twelve short sequential runs and 80 central requests per case cannot characterize rare-failure probabilities or a production tail distribution. Loss runs are stochastic and not randomized against contemporaneous baselines.

## Mitigation and verification

For each deliberately injected condition, remove that condition and check the corresponding evidence again: RTT for delay, queue drops/retries and request tails for loss, throughput/bulk completion for a bandwidth cap, and handler timing for an application pause. Do not use a healthy ping, a single throughput number or a lower CPU chart as the only acceptance check.

In a real incident, validate the affected endpoints/ports, compare request timing with per-socket TCP behavior, inspect both hosts, and trace the layer supported by the evidence. Avoid tuning arbitrary TCP/kernel parameters until a specific bottleneck is demonstrated. Preserve failed or confounded trials; correct the protocol and repeat them.

## Interview explanation

“The application was slow, so I measured three things separately: how long the request took, how long the application itself spent handling it, and how TCP and bulk transfers behaved.

“When I delayed network replies, TCP round-trip time grew while the application handler stayed fast. When I limited bandwidth, large downloads slowed much more than small requests. When I paused the application, its own timing grew even though the network measurements stayed healthy. Those different patterns helped identify which layer was waiting.

“I also found that my test tool had left a bandwidth limit behind. I caught it by checking the actual queue settings and throughput, kept the affected results clearly marked, fixed the reset and repeated the tests. After the test faults were removed, the final response p95 was about nine milliseconds.”

## Setup, evidence and cleanup

Disk checks found about 1.3 GiB free on the client and 1.8 GiB on the server (95%/93% used). The lab uses in-memory responses and bounded text/header logs, so no old files were deleted or bulk test files written. Disk capacity remains a future maintenance task, not a proved cause of these network results.

The moved VMs' SSH identities matched the saved keys. Their existing NFS export/firewall/fstab references were updated to the new addresses, with backups. Final ordinary-user read/write verification passed and the share remains mounted at `/mnt/perf-lab-nfs`.

The HTTP/iperf services ran as the ordinary lab user under finite memory/task/runtime limits. Sudo was used for the single-client temporary firewall rules, transient services, packet-header capture and scoped queue changes. A rollback timer and expiring rules limited interruption risk. After measurement, both services/listeners and observers were stopped, temporary rules/state removed, and the original fq_codel policy restored with quantum 1514. SELinux stayed enforcing. iperf3 remains installed; no test workload is left running.

[Client preflight](results/network/preflight-client.json), [server preflight](results/network/preflight-server.json), [client cleanup](results/network/cleanup-client.json) and [server cleanup](results/network/cleanup-server.json) record the state. All HTTP/iperf, host, scoped socket, queue and short header evidence is under [results/network](results/network). Exports replace addresses/hostname strings with role labels and omit unrelated connection records, keys, credentials and payloads. The static report never connects to the VMs.

Nine analysis/integrity tests passed on Windows and Linux; see [Linux test output](results/network-tests.txt). They check failure denominators, missing data, percentile boundaries, iperf metric selection, socket/queue scope, ping parsing and a real loopback small/bulk/slow-handler response path. See [the guide and primary references](network/README.md) for commands and scope.
