# Linux performance investigation runbook

## Start with the service

Establish what became slow, when, for whom, and under which workload. Check application latency distribution, throughput, errors and deployment/change history. Compare against a baseline with similar traffic. Align clocks before joining evidence.

## Triage host resources

Use utilization, saturation and errors as a checklist, adapted from [Brendan Gregg's USE method](https://www.brendangregg.com/usemethod.html). No single chart completes the investigation.

| Resource | Initial evidence | Follow-up / known gaps |
|---|---|---|
| CPU | Execution, steal, CPU PSI, runnable tasks | `mpstat -P ALL 1 5`; `pidstat -u 1 5`; cgroup CPU throttling; hardware/kernel errors |
| Memory | Available memory, memory PSI, swap occupancy | `vmstat 1 5` swap-in/out; major faults, reclaim; per-process growth; OOM logs and cgroup `memory.events` |
| Storage | Per-device await, queue, throughput, busy time; I/O PSI | `iostat -xz 1 5`; `pidstat -d 1 5`; kernel/device errors; filesystem and remote mount path |
| Network | Interface throughput, errors and drops | Link capacity, `ss -s`, TCP retransmits and connection queues; remote dependency timing |
| Filesystems | Not collected by this prototype | `df -h`; `df -i`; mount types and read-only/error states; avoid broad commands if mounts may be hung |

`vmstat`, `iostat`, `pidstat` and `mpstat` may need packages. The first `vmstat`/`iostat` report can reflect averages since boot; use subsequent interval rows. Permissions and namespaces affect visibility. Do not assume a host's CPU count equals a container's usable CPU entitlement.

The report uses CPU busy >85% with CPU PSI some >5%, I/O PSI some >5%, and available memory <10% with memory PSI some >1% as **illustrative per-interval triage rules**. They have no persistence or application correlation and are not production paging rules. Absent pressure values do not become zero.

## Alerts I would design for an actual service

Page on a sustained service-level symptom with an actionable response and owner. Add resource signals as context; resource-only signals often belong in tickets or capacity planning. Define sample cadence, evaluation window, minimum traffic, treatment of missing data, recovery hysteresis, and deduplication. Calibrate against observed normal and incident windows instead of copying this demo's thresholds.

Evaluate both missed incidents and noisy alerts against labelled history. Test telemetry loss separately. Avoid paging merely because free memory is low, load exceeds CPU count, or a parallel storage device reports high busy time.

## Verify and preserve evidence

Record the hypothesis, source measurements, exact change and time, expected effect, and rollback. Compare equivalent pre/post workloads, including service latency, throughput and errors. Preserve raw JSON alongside the generated report. Repeat the experiment if feasible. State remaining uncertainty and avoid claiming causation from coincident lines alone.
