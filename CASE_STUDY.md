# High load, modest CPU: an evidence-led Linux investigation

**An illustrative case study using simulated evidence. No production incident or measured remediation is claimed.**

## The question

A Linux server has a high load average. Should it receive more CPU capacity?

My first step would be to establish application impact and the affected time window: latency percentiles, request rate, errors, and recent changes. Host metrics guide investigation; they do not by themselves establish customer impact. This lab intentionally starts with host signals, so application impact remains unknown.

## Read the evidence

Open `showcase.html`, choose the I/O investigation, and select an interval between 21 and 60. The synthetic host has four logical CPUs. Load is around 15 while CPU execution is about 28%. I/O pressure is around 43%, read/write await around 72 ms, and average device queue around 14.4. Multiple tasks are blocked on I/O.

The CPU is doing relatively little execution while work is stalled on I/O. Load alone would have pointed us at the wrong resource if interpreted as a CPU percentage. The kernel describes both runnable and uninterruptible work in Linux load accounting. Pressure adds evidence of stalled work; per-device latency and queues help narrow the investigation.

The working hypothesis is **I/O contention or a slow I/O path**. These signals do not identify the responsible process, prove device failure, or distinguish local storage from all possible filesystem dependencies.

## Test competing explanations

| Explanation | Evidence that would strengthen or weaken it |
|---|---|
| CPU contention | Per-core activity and CPU pressure. Modest aggregate CPU can still conceal one busy core; inspect before dismissing. |
| Local storage contention | Device latency/queues and I/O PSI aligned in time; process I/O aligned with the affected application. |
| Memory reclaim driving I/O | Memory PSI, reclaim counters, major faults, and swap-in/out rates. Swap occupancy alone is insufficient. |
| Network filesystem delay | Mount type, mount/client statistics, blocked-task stacks, network health, and server-side evidence. Local diskstats may miss the path. |
| Container quota or memory limit | Workload cgroup `cpu.max`, `cpu.stat`, `memory.events` and cgroup pressure, even if the host has spare resources. |
| Hardware or platform problem | Kernel errors, storage service metrics, device health and hypervisor signals. |

## Choose an intervention only after attribution

If process-level evidence showed a non-critical batch task competing with the service for the same storage, I would test pausing or reducing that task's concurrency in the lab. I would record the change time, keep application demand comparable, and compare latency, throughput, errors, PSI, device await, and queues before and after. I would restore the workload if the change harmed throughput or failed to improve the intended symptom.

Other findings require different actions: a storage service limit, failed path, remote filesystem, excessive application sync writes, and reclaim pressure are separate diagnoses. Adding CPUs is not justified by this evidence alone.

The supplied trace returns to a designed baseline after interval 60. **That transition is illustrative, not proof of a successful intervention.** To claim a fix, attach real captures, exact intervention timing, controlled workload details, application measurements, and preferably a repeat experiment.

## What makes this useful as a portfolio piece

The value is the reasoning a reviewer can inspect: what was observed, which explanation it supports, what remains unknown, and which measurement would resolve it. The collector and tests expose the arithmetic behind the charts. The CPU lab gives a separate, bounded route to obtain real evidence rather than presenting synthetic charts as operational experience.

References: [Linux /proc](https://www.kernel.org/doc/html/latest/filesystems/proc.html), [PSI](https://www.kernel.org/doc/html/latest/accounting/psi.html), [I/O statistics](https://www.kernel.org/doc/html/latest/admin-guide/iostats.html), [USE method](https://www.brendangregg.com/usemethod.html).
