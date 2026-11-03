# When load average hides a short CPU spike

**Measured Linux lab experiment · 3 November 2026 · no root privileges.**

## The question

Would an alert that only fires when one-minute load exceeds the number of CPUs detect a short period of CPU contention?

The first run demonstrates why that rule can miss a problem. CPU execution reached 100% and the independent runnable queue exceeded the two available CPUs, while one-minute load remained below 2 throughout the workload. After the workload ended, CPU execution dropped promptly while load decayed more slowly.

## Environment and protocol

- Oracle Linux Server 9.7, kernel `6.12.0-200.74.27.1.el9uek.x86_64`, Python 3.9.25.
- Two logical CPUs with affinity to CPUs 0–1; approximately 1.5 GiB RAM.
- Standard user account. No packages installed, kernel settings changed, or services restarted.
- Root filesystem was 95% full, with approximately 1.1 GiB available. No disk or memory stress was performed.
- CPU/memory/I/O PSI files were absent. Their values remain unavailable rather than zero.
- Fifteen approximately one-second baseline intervals, then four CPU worker processes bounded to 30 seconds, followed by recovery through interval 75. The baseline was quiet but not idle.
- `vmstat` and per-core `mpstat` observed the full run. A repeat additionally recorded process CPU with `pidstat`.

The first run began at **09:53:25.755 UTC** and finished at **09:54:41.354 UTC**. Workload launch was requested at 09:53:40.869; successful process exit was observed at 09:54:12.149. These are controller observations, not exact worker scheduling timestamps.

## First-run measurements

| Metric | Baseline, 15 intervals | Workload, 30 intervals | Recovery, 29 intervals |
|---|---:|---:|---:|
| Mean CPU executing | 12.05% | 99.45% | 10.99% |
| Mean one-minute load | 0.058 | 0.971 | 1.202 |
| Maximum one-minute load | 0.07 | 1.61 | 1.48 |
| Mean available memory | 59.56% | 58.97% | 58.71% |
| Mean CPU steal | 0% | 0% | 0% |

One shutdown interval is labelled transition and excluded from these phase summaries. The first workload interval includes process startup and recorded 83.5% CPU; subsequent full workload intervals recorded 100%.

## Cross-check the evidence

The analysis trims two intervals from either edge of each phase to reduce startup/shutdown and observer alignment effects. `mpstat` timestamps have one-second resolution; the comparison matches the nearest endpoint within 0.75 seconds. This is a consistency check, not proof of clock-perfect samples.

| Stable phase | Collector CPU mean | mpstat CPU mean | Mean absolute difference |
|---|---:|---:|---:|
| Baseline, 11 pairs | 11.80% | 11.84% | 1.24 percentage points |
| Workload, 26 pairs | 100.00% | 100.00% | 0.00 percentage points |
| Recovery, 25 pairs | 11.09% | 11.16% | 1.36 percentage points |

During the stable workload window, independent `vmstat` reported an average of **4.23 runnable tasks**, with a maximum of 6. That supports CPU contention on this two-CPU VM. The collector's runnable count includes the collector itself at its own snapshot time; it need not equal vmstat's independently sampled value.

Swap occupancy was already approximately 857.6 MiB before the exercise. Stable-window swap-out was zero; a small swap-in peak of 16 KiB/s occurred during the workload. Occupancy alone would have been a poor basis for declaring active memory exhaustion. Without memory PSI, this experiment cannot quantify memory stall time.

## Repeat and process attribution

A second 75-interval run, **09:56:25.818–09:57:41.340 UTC**, reproduced the pattern. Mean CPU execution was **13.01% baseline, 99.85% workload, and 14.98% recovery**. The workload window had 29 intervals, followed by one transition interval and 30 recovery intervals. Maximum load during the workload was **1.76**, again below two.

In the stable workload window, both the collector and mpstat reported 100% across 25 matched intervals; per-core mpstat reported 100% on each CPU. Independent vmstat averaged **4.16 runnable tasks**. Four Python processes in pidstat dominated the injected-workload window:

| PID | Mean process CPU, 25 observations |
|---|---:|
| 10748 | 45.48% |
| 10749 | 45.97% |
| 10750 | 46.97% |
| 10751 | 44.89% |

These pidstat percentages use one logical CPU as 100%, so their sum is not directly comparable to the host-wide 0–100% scale. Host totals also include kernel work. The pidstat log exposes process names and PIDs, not Python command arguments; the controlled launch and time alignment support attribution, but a direct saved parent-child PID mapping was not recorded.

Available memory was lower before the repeat (about 46.5% versus 59.6% in the first baseline), and the recovery CPU baseline was higher. Background conditions were not identical. These are two corroborating lab runs, not a controlled statistical benchmark.

## Interpretation

CPU execution plus an independent runnable queue can reveal contention before one-minute load crosses a simplistic threshold. Load also lags recovery. A diagnosis should use several signals with clear time windows and should preserve unavailable evidence.

Stopping the deliberately bounded workload restored CPU execution to its earlier range. This is recovery from an injected workload, **not a production optimization or proof of improved application latency**. No application latency, errors, throughput, CPU stall time, or customer impact was measured. Background activity and tool sampling also contribute to the observed values.

The collector recorded 0.3017 process CPU seconds, a 17,012 KiB maximum resident set, and a 5.657 ms median snapshot/derivation time during the first run. These are recorder-only observations from one VM, excluding observer and workload processes; they do not establish total monitoring overhead.

## Inspect and reproduce

- `showcase.html`: measured CPU capture first, then separately labelled synthetic investigations.
- `results/cpu-lab.json`: raw samples, phase labels, metadata and workload events.
- `results/summary.json`: reproducible phase statistics and observer pairings.
- `results/mpstat.txt`, `results/vmstat.txt`: independent observation logs; first vmstat row is since boot and excluded from analysis.
- `results/unit-tests.txt`: 14 passing Linux tests.
- `results/repeat/`: repeat evidence, including process attribution with pidstat.

Run `python3 run_live_lab.py --isolated-lab` on an isolated two-CPU Linux VM, then `python3 analyze_results.py`. A repeat can use `--out-dir results/repeat`. The runner records 75 intervals; it does not enforce identical background workload or hypervisor conditions.

For definitions, see [Linux /proc accounting](https://www.kernel.org/doc/html/latest/filesystems/proc.html) and [Linux PSI](https://www.kernel.org/doc/html/latest/accounting/psi.html).
