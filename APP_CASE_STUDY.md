# Why p95 latency rose from 92 ms to 411 ms on a two-CPU Linux VM

**A measured lab investigation connecting Linux CPU contention to Java request latency.**

## The problem and the application

An endpoint can continue to return successful responses at the expected request rate while its tail latency becomes much worse. I built QuoteLab to investigate that behavior on a small Linux VM.

QuoteLab is a Java HTTP service with a deterministic quote-calculation endpoint. Its purpose is to produce a visible, repeatable CPU demand without a database, framework downloads, or a large memory footprint. The calculation is deliberately synthetic; the service, traffic, contention and timings are real measurements.

The VM has two logical CPUs and approximately 1.5 GiB RAM, running Oracle Linux 9.7. The app used OpenJDK 17, two HTTP executor threads, a 64 MiB Java heap cap and a 256 MiB service memory cap. Its maximum observed service memory peak across the first two runs was approximately 75.1 MiB. It bound only to loopback and ran as a non-root dynamic service user.

## Define the experiment before interpreting charts

The request generator offered four arrivals every second, independent of previous completion times. Each run warmed the JVM for 20 seconds, then recorded:

1. Twenty seconds of baseline traffic.
2. Thirty seconds with four competing CPU worker processes.
3. Twenty-five seconds of recovery after those workers ended.

Two unrestricted runs tested reproducibility. A third run kept the same offered request rate and worker count but capped the background workload to one logical CPU's worth of execution using a transient systemd service. Each run made 300 measured requests. Five functional checks and approximately 80 warmup requests per run were separate from those 300.

The raw data records all arrivals, response status, JSON result, actual HTTP duration, client scheduling lag, server computation wall/thread-CPU times, host samples and experiment events. Analysis trims two seconds from each phase boundary. Those stable windows contain 64 baseline, 104 contention and 84 recovery arrivals per run. Percentiles use nearest rank over successful requests; p99 from these small samples is descriptive.

## The measured result

| Experiment | Baseline p95 | Competing workload p95 | Recovery p95 |
|---|---:|---:|---:|
| First run, unrestricted noise | 92.0 ms | 410.7 ms | 102.4 ms |
| Repeat, unrestricted noise | 113.4 ms | 306.1 ms | 126.0 ms |
| Background limited to one CPU | 90.6 ms | 176.7 ms | 107.1 ms |

**All 900 measured requests succeeded.** Stable-window successful completions remained four per second in every phase. In the unrestricted runs, mean host execution reached 100% and the sampler observed approximately 6.3 runnable tasks. End-to-end p95 latency rose by 4.46× in the first run and 2.70× in the repeat.

The first run's one-minute load averaged 1.41 during contention and 1.76 during recovery. Load's smoothing makes it unsuitable as the only detector for this short application slowdown. In the repeat, recovery load averaged 2.50 even though mean execution had fallen to about 30.5%.

## Explain the slowdown with several kinds of evidence

In the first run, average handler wall time increased from **76.5 to 274.3 ms**, while handler thread CPU time increased from **73.5 to 89.3 ms**. The wall-time increase was much larger than the increase in actual computation time. The repeat showed the same relationship: wall time increased from 88.5 to 257.3 ms and thread CPU time from 77.2 to 83.2 ms.

The client shared the VM and was also scheduled under contention. Its p95 scheduling lag increased from 1.9 to 15.7 ms in the first run. That is a confound worth measuring, but it does not explain away the server-side increase of roughly 198 ms in average handler wall time. HTTP duration excludes the client's pre-dispatch scheduling lag; the raw data also retains latency measured from the scheduled arrival.

Per-core mpstat, process-level pidstat, the runnable count, and process-scoped perf counters accompany the capture. Java Flight Recorder sampled 247 execution stacks across startup/warmup and the first two experiments; **211 included `QuoteLab.quote`**, and 209 had `Math.log1p` as the top frame. This locates the deliberate CPU computation. The sample distribution is not a wall-time percentage or an off-CPU measurement.

Together, controlled CPU interference, host saturation, runnable work, server wall-versus-CPU timing, and recovery support CPU contention as the main explanation. They do not uniquely allocate every millisecond among preemption, runtime activity, CPU/cache effects and other waits. Handler CPU cost also increased during contention, so the slowdown was not purely extra waiting with perfectly constant CPU cost.

## Test a mitigation and state its cost

I placed the same four background workers in a transient systemd service with `CPUQuota=100%`. On this VM that permits one logical CPU's execution time, rather than the full capacity of both CPUs. It does not pin workers to a particular core.

The recorded quota was `CPUQuotaPerSecUSec=1s`. At the mid-workload observation, 147 of 149 quota periods had been throttled, confirming that the cap was active. Mean host execution during the stable contention window was about 75%; p95 response time was 176.7 ms. That was approximately 42–57% lower than the two unrestricted contention runs, as an observed cross-run comparison.

This is a **partial mitigation**. Of 104 stable-window requests during contention, 22 exceeded the illustrative 150 ms budget, versus all 104 in each unrestricted run. There was one capped run, background conditions varied, and the experiment was not randomized. The result supports further testing rather than a universal improvement claim.

The cap reduces CPU available to the background job. The worker script runs for a fixed wall time and does not count useful completed operations, so I have not quantified that job's throughput loss. A production decision would balance both workloads' objectives and test the chosen limit under representative demand.

## Operational choices and limitations

Dependencies came from Oracle's signed repositories with signature checking retained. The app used no downloaded third-party Java libraries. It ran with filesystem, privilege, task and memory restrictions. No external port was opened, no SELinux enforcement or global perf policy was relaxed, and no boot parameter or reboot was needed.

The VM had `CONFIG_PSI=y` and `CONFIG_PSI_DEFAULT_DISABLED=y`; pressure files were absent. The report preserves those values as unavailable. The filesystem was over 90% full, so this experiment did not inject storage or memory pressure. Background activity was not fully controlled, and the client, observers and app shared the VM. Profiling itself has overhead. No production customer impact, fleet scalability or general capacity limit is established.

The Java 26 runtime initially failed to initialize under the service restrictions. Successful tests used the distribution's OpenJDK 17 runtime. Java's normal SIGTERM exit code 143 was subsequently configured as a successful systemd stop; the final service lifecycle was checked. The app was left installed but stopped, with no background test processes remaining.

## Inspect and reproduce

Open `app-report.html` to compare all three measured runs, then inspect `results/app-run1`, `results/app-run2` and `results/app-mitigated`. Each contains the raw request/host capture, derived summary, five functional checks and independent observation logs. Source and installation instructions are in `app/README.md`.

The public package contains a narrow Java profile summary. Full JFR files remain separate because JVM recordings can contain more environment detail than is needed to assess the result.

This case study demonstrates installation, service isolation, controlled load generation, Linux counter interpretation, application timing, profiling, mitigation and honest verification. A reviewer can inspect how each conclusion follows from preserved evidence.
