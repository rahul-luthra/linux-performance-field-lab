# Following a save request through Linux and NFS

**Question:** when an application saves slowly, is it using CPU, waiting on local storage, waiting on the NFS server, or waiting on the network?

[Explore the interactive evidence](https://rahul-luthra.github.io/linux-performance-field-lab/storage.html), [inspect the summaries](results/storage/summary.json), or [reproduce the study](storage/README.md).

## Workload and environment

Two Oracle Linux 9.7 VMs, each with two logical CPUs and approximately 1.5 GiB RAM, share one physical host. One runs a small Java 17 HTTP application; the other exports an NFSv4.2 directory. Each save writes a 64-KiB record into a bounded 16-MiB file and calls `FileChannel.force(false)` before responding. The export is synchronous and the client uses a hard TCP mount. These settings preserve the same application synchronization policy, but do not establish equal physical durability for local and remote files. No power-loss test was performed.

Each case has 32 warmup requests, followed by 120 offered arrivals at four per second. The central 26 seconds supply 104 requests for HTTP percentiles; NFS counters cover the complete measurement window. Percentiles use nearest rank. Client concurrency is bounded at eight, with a three-second HTTP timeout. Both VMs contribute one-second host/device samples and independent iostat logs; the client also records nfsiostat and per-mount RPC counter snapshots. The client and load generator share a VM, so scheduling lag is retained as another possible source of latency.

## Measured results

All **1,200 measured requests** returned the expected response and checksum. Client final-block readbacks matched in all ten cases; independent server readbacks matched for all nine NFS cases. These are integrity observations, not crash-recovery guarantees.

| Case, in execution order | HTTP p95 ms | Force p95 ms | WRITE mean RTT ms | Server disk R/W await ms | Background 8-KiB writes/s |
|---|---:|---:|---:|---:|---:|
| local-baseline | 25.889 | 6.865 | n/a | n/a | n/a |
| nfs-baseline | 20.068 | 11.419 | 7.842 | 1.497 | n/a |
| nfs-delay-a | 46.119 | 34.053 | 30.600 | 1.531 | n/a |
| nfs-delay-b | 60.224 | 54.577 | 30.508 | 1.378 | n/a |
| nfs-recovery | 21.789 | 10.946 | 8.700 | 1.271 | n/a |
| nfs-server-io | 30.684 | 16.447 | 9.667 | 1.020 | 849.766 |
| nfs-io-limited | 61.658 | 55.797 | 14.383 | 3.023 | 19.904 |
| nfs-server-io-repeat | 246.375 | 240.216 | 130.983 | 18.572 | 65.871 |
| nfs-io-limited-repeat | 199.183 | 190.034 | 103.508 | 23.908 | 21.268 |
| nfs-final-recovery | 235.437 | 190.684 | 101.858 | 36.397 | n/a |

The local case does not use the NFS server; unrelated server activity is not an explanation for local response time.

## Investigation and findings

The early network experiment gives the strongest causal evidence. We introduced a 20-ms packet delay only for NFS replies from server TCP port 2049 to the client. WRITE RPC RTT increased from approximately 8 to 31 ms in both repetitions while server device R/W await stayed around 1.3–1.5 ms. HTTP p95 increased from 20 to 46/60 ms, then recovered to 22 ms after the delay was removed. This supports the deliberately injected network-path delay as the explanation for that part of the experiment. Application `force` time includes more than one layer; neither it nor client iowait is a direct disk-latency measurement.

The I/O experiment demonstrates why a mitigation must be verified. A two-worker background workload performs random 8-KiB direct synchronized writes to a separate 64-MiB file. A cgroup limit of 50 block write IOPS substantially reduces its completed file writes. It does **not** prove that the application's latency improves: the first capped run became slower, the repeated pair improved modestly, and the final quiet baseline remained slow. Server disk busy time was about 88–90% in unrestricted runs, yet a smaller busy percentage did not guarantee a smaller application tail.

The uncapped writer's achieved rate also fell from about 850 to 66 file writes/s between repetitions. The final quiet WRITE RTT remained approximately 102 ms. This substantial late baseline drift prevents a clean attribution of the repeated I/O comparison. Virtual/backing storage, filesystem/journal work and host scheduling are candidate explanations requiring additional tracing; none was proved as the root cause. The server root filesystem was 93% used after cleanup, another recorded condition to address in a follow-up, not proof of causation.

No WRITE RPC retransmissions or major timeouts were recorded. There were no separate COMMIT operations in these windows. Stable WRITE processing can avoid a separate COMMIT; its absence alone does not prove durable storage. RPC means and HTTP tail percentiles describe different populations and cannot be subtracted to assign precise time to every layer.

## Mitigation and next verification

For the injected network case, removing the delay restored early response times. In an actual incident, investigate path latency and server response time separately before changing storage or adding CPUs.

For the disk case, treat background I/O throttling as a candidate policy with a measured cost to background work. Do not advertise it as a successful latency fix from this dataset. The next investigation should first obtain a stable quiet baseline, reclaim or expand the nearly full lab filesystem, record physical-host/backing-device activity, and repeat randomized baseline/uncapped/capped blocks. Trace NFS service processing, filesystem synchronization/flushes, and scheduling when the long tail appears. Recheck integrity and recovery after any change. Keep the synchronous export and hard-mount policy rather than trading away semantics for a better chart.

Local p95 of 26 ms versus NFS p95 of 20 ms is a short-run observation, not a claim that NFS is intrinsically faster. Both virtual disks and their caches ultimately depend on the same physical host. This four-request/s workload is a diagnostic exercise, not a throughput-capacity benchmark.

## Interview explanation

“The application was taking longer to save a small record. I measured the time at the application, the network-file requests and the storage server together. When I deliberately delayed the network replies, saves became slower even though the server's disk timing stayed almost the same. Removing that delay brought the early results back. That showed how to distinguish network waiting from disk waiting.

“I then added competing disk writes and tried restricting them. The restriction reduced background work, but response times did not improve consistently, and even the final quiet test was slow. I kept that result and marked the underlying drift unresolved. My next step would be to stabilize and inspect the backing storage before claiming a fix.”

## Evidence and scope

Raw data is under [results/storage](results/storage); [client setup checks](results/storage/client/setup.json) and [server setup checks](results/storage/server/setup.json) record the final state. Lab addresses/hostnames in exported text are replaced with role labels. No private keys, authentication tokens, synthetic data files, JVM dumps or compiled binaries are published.

The export and firewall allow one client, use root squashing and retain SELinux enforcement. `sec=sys` trusts client-supplied identities; this is a trusted-LAN lab, not an encrypted or Kerberos-authenticated storage deployment. Privileged setup and fault injection require sudo; application and background-writer processes run as the ordinary lab account. See [the exact method and references](storage/README.md).

After measurement, the original network queue policy was restored, the rollback timer was stopped, and bounded data files were removed. NFS service and the persistent client mount remain configured for future labs.
