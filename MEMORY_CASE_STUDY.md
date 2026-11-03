# Available host RAM, failed Java app: identify which memory limit was reached

**Measured Linux/JVM memory investigation · 3 November 2026.**

This follows the CPU-contention investigation using the same two-CPU Oracle Linux 9.7 VM and OpenJDK 17.0.21. A separate loopback-only teaching service reuses QuoteLab's calculation and adds bounded heap retention, direct-buffer retention and temporary scratch allocation. The faults are deliberately injected; the failures, counters, GC logs and timings are measured.

## Start with the right question

Available host RAM, Java heap capacity and a service's cgroup memory allowance are different budgets. A Java process can exhaust either of the latter two while the host still has ample available memory. I tested each boundary separately, reproduced each failure twice, then changed only the relevant limit for its finite workload.

| Test | Java heap cap | Service cap | Observation |
|---|---:|---:|---|
| Heap retention, repeated twice | 32 MiB | 192 MiB | JVM reported `Java heap space`, exited with code 3; cgroup OOM-kill delta stayed 0 |
| Same 48 MiB retained-heap target | 96 MiB | 192 MiB | Allocation target completed; app remained responsive until the harness stopped it |
| Direct-buffer retention, repeated twice | 32 MiB | 96 MiB | Java was killed by signal 9; same-cgroup OOM-kill delta increased by 1 |
| Same 80 MiB direct-buffer target | 32 MiB | 192 MiB | Allocation target completed; app remained responsive until the harness stopped it |

The two Linux memory-limit kills occurred while sampled host available memory never fell below approximately **832 and 824 MiB**, respectively. Cgroup peak charge reached 96 MiB in each case. JVM heap remained a separate 32 MiB budget, and neither native-memory failure printed a Java heap-space error.

The heap failures stopped after retaining about 28 MiB of explicit arrays, before the 48 MiB target. Objects, HTTP machinery and other heap use also need room; the entire heap is not available to the explicit retained arrays. A heap dump of about 33 MiB was captured for the first failure and retained privately. It was not analyzed to claim a leak. The finite retained workload and source establish a sizing mismatch, not evidence of unbounded retention.

## Preserve evidence after the process dies

A small Python supervisor runs in the same test cgroup as Java and polls its memory charge, `memory.events`, host available memory and `/metrics`. It remains alive briefly after Java exits so the final cgroup counters can be saved before the empty cgroup disappears. `OOMPolicy=continue` allows this diagnostic design; the group-kill setting was observed as zero.

The cgroup limit therefore includes **both Java and the supervisor**, plus charged file cache. It is not a Java-process RSS limit. The first heap-failure cgroup peaked at about 131 MiB while writing its dump; the no-dump repeat peaked at about 63 MiB. Those peaks should not be interpreted as identical workloads or as a leak.

The diagnostic wrapper records Java's actual return code separately. Python reports signal 9 as `-9`; a shell would conventionally report 137. The healthy corrected cases were deliberately stopped at the end of a 20-second observation window and returned 143 after SIGTERM. They did not spontaneously exit. The wrapper's own successful unit result does not prove its Java child survived; child status and cgroup counters are the evidence here.

The classifier requires both signal termination and a same-cgroup OOM-kill increment for the Linux OOM conclusion. A SIGKILL with no such evidence remains inconclusive. The configured JVM's code-3 exit plus the heap-space message and zero cgroup kills support the Java heap conclusion. Missing counters remain unknown.

## Measure allocation pressure without killing the app

The next experiment used a 32 MiB heap, 192 MiB service limit, 16 MiB retained cache and two HTTP workers. After 60 warmup requests, the client scheduled four arrivals per second for 55 seconds:

1. Fifteen seconds of the normal quote calculation.
2. Twenty-five seconds additionally clearing/touching 64 MiB of scratch storage per request.
3. Fifteen seconds of the normal quote calculation again.

Two runs allocated fresh 1 MiB arrays for the scratch work. A third reused one 1 MiB buffer per HTTP worker, clearing/touching the same logical volume and producing the same checksum. The client used eight workers, a three-second HTTP timeout and explicit admission/error records; it did not wait for a response before scheduling the next arrival.

All **660 measured requests** returned the expected quote and phase-appropriate checksum. Central windows trim two seconds from either side of each phase, leaving 44/84/44 requests. GC deltas span the first-to-last available JVM samples inside each stable window, approximately 20.5–20.8 seconds in the middle phase. They are aggregate collection counters, not a per-request pause attribution.

| HTTP experiment | Baseline p95 | Middle p95 | Recovery p95 | Middle GC count | Middle GC time delta |
|---|---:|---:|---:|---:|---:|
| Fresh arrays A | 95.9 ms | 149.5 ms | 176.3 ms | 1,063 | 2,187 ms |
| Fresh arrays B | 96.5 ms | 130.7 ms | 92.7 ms | 1,076 | 1,991 ms |
| Reusable buffers | 87.6 ms | 110.0 ms | 106.4 ms | 4 | 22 ms |

Reuse reduced the observed middle-window GC counter time by about 99% relative to the allocating runs. Middle-phase p95 was about 16–26% lower across these runs. It remained higher than that run's baseline. This is one reuse trial and two allocation trials, not a randomized benchmark or universal improvement claim.

Both allocation and memory-locality costs change with reuse. Handler CPU time during the middle phase was about 87.7/82.0/84.2 ms across the three runs, so CPU cost did not simply fall in step with total GC time. The result supports buffer reuse for this workload, while the evidence does not isolate every mechanism behind the latency change.

## Keep the anomaly visible

Fresh-array run A did not show latency recovery: its recovery p95 was 176.3 ms despite no GC-counter increase in that window. Mean handler CPU time rose to about 111.6 ms, compared with 73.2 ms at baseline, while host execution also varied. The repeated allocation run recovered to 92.7 ms.

That discrepancy is preserved in the report. These measurements do not determine whether CPU/JIT/cache/platform behavior or another factor caused the first run's elevated tail. A focused follow-up would inspect per-thread/JIT and platform evidence. It would be incorrect to assign that recovery latency to GC merely because the preceding phase allocated heavily.

## Scope, privileges and cleanup

All nine test units ran one at a time, with service limits of 96 or 192 MiB, cgroup swap disabled, bounded runtimes, task limits and non-root Java/supervisor processes. Before each run, the harness required at least 600 MiB host available memory. Sudo was used to install inspected class files and create/manage the transient cgroups. No host swap setting, boot parameter, SELinux setting or existing application service was changed. No network port was opened externally.

The userland did not support a direct `MemoryOOMGroup` transient-unit property, so the final harness observes the kernel's default `memory.oom.group=0` instead of assigning that property. PSI files were unavailable on the host. GC logs and JVM/cgroup metrics supplied the relevant evidence.

The client, observer and Java service share the VM. Sampling, HTTP metrics and GC logging have overhead. These small Serial-GC lab runs do not establish production capacity or the behavior of another collector. Corrections were observed only for bounded targets/windows; increasing a limit would not repair a real unbounded leak.

Every Java child and supervisor ended, and no memory-lab listener remains. The binary heap dump remains on the VM; the public package contains only text evidence and narrow summaries. The original CPU/Java study is preserved.

## Inspect and reproduce

- [Interactive memory investigation](https://rahul-luthra.github.io/linux-performance-field-lab/memory.html)
- `results/memory/faults/`: six captures, application/GC logs, cgroup counters and summaries.
- `results/memory/pressure/`: three HTTP captures, JVM/cgroup samples, GC logs and derived windows.
- `memory/MemoryLab.java`: bounded workload source, reusing `app/QuoteLab.java`.
- [Reproduction and privilege details](memory/README.md).

Definitions: [Linux cgroup memory control](https://docs.kernel.org/admin-guide/cgroup-v2.html), [Java memory diagnostics](https://docs.oracle.com/en/java/javase/17/troubleshoot/troubleshooting-memory-leaks.html), [JVM command options](https://docs.oracle.com/en/java/javase/17/docs/specs/man/java.html).
