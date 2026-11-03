# Validation record

Validated on 3 November 2026 on Windows and a remote Oracle Linux 9.7 VM.

- `python -m unittest -v`: all 14 fixture-based tests passed on Windows.
- `python3 -m unittest -v`: all 14 tests passed on Oracle Linux / Python 3.9.25, in 0.092 seconds. Raw output: `results/unit-tests.txt`.
- Live CLI smoke test: three half-second Linux intervals captured; report generation succeeded on Linux.
- First CPU exercise: all 75 intervals saved; workload exited with code 0; independent vmstat and per-core mpstat logs collected.
- Repeat exercise: another 75 intervals saved; workload exited with code 0; vmstat, per-core mpstat and process-level pidstat logs collected.
- Measured CPU results cross-checked with independent tools; stable workload windows agreed at 100% on both runs. See `results/summary.json` and `results/repeat/summary.json` for pairing details and caveats.
- `python make_demo.py`: rebuilt the four scenario data sets and self-contained report.
- Headless Microsoft Edge browser checks cover the measured capture and all four simulated investigations, all 75 measured slider intervals, unavailable PSI labels, recovery phase labels, JSON download, and page layout at 320, 375 and 768 pixels.
- Desktop report screenshot inspected visually; saved as `preview.png`.

The Linux VM did not expose `/proc/pressure/*`. Live PSI behavior remains unverified; fixture tests cover its parsing/arithmetic and missing/reset handling. Live storage/memory/network fault injection was not performed. The four teaching scenarios remain explicitly synthetic. No application performance improvement or full monitoring-overhead benchmark is claimed.

The original collector-only exercises used no sudo, service changes or package installation. Test files and captures were written to a dedicated home-directory folder. All CPU workers and observer processes ended; final process checks found none of the lab processes running. Header hostnames in the distributed mpstat/pidstat logs are redacted; originals remain on the VM. SSH keys and connection files are excluded from the release archive.

## Java application extension

- Installed the generated QuoteLab service, plus Oracle-repository OpenJDK 17 headless runtime and perf, with signature checks retained. Dependencies were approximately 200 MB installed. No external Java libraries were downloaded.
- Verified loopback binding on port 8087, a separate dynamic non-root service user, a 64 MiB heap cap, a 256 MiB service memory cap and restricted filesystem/privilege settings.
- Three measured application runs: two with unrestricted background CPU work and one with a transient one-CPU quota. Each recorded 300 scheduled requests and 74 completed host intervals, with five passing functional checks before each run. All 900 measured requests returned successful, expected JSON responses.
- Preserved request arrival/scheduling/HTTP/handler timings, host samples, phase events, mpstat, vmstat, Java pidstat and process-scoped perf logs.
- Mitigation quota checked during execution: one CPU per second, with 147 of 149 observed periods throttled. The quota service ended and was collected.
- JFR summary for the first two runs: 247 sampled execution stacks, 211 containing QuoteLab.quote. Narrow public summary included; raw JVM recordings/exports excluded from public release.
- Five additional analysis tests cover nearest-rank percentiles, missing data, failures, correct-response validation and completion-window attribution. They pass on Windows and Linux. Linux output is `results/app-analysis-tests.txt`.
- The systemd unit was corrected to recognize Java's expected SIGTERM status 143; the final installation/readiness/start/stop check returned `Result=success`, `ActiveState=inactive`, `UnitFileState=disabled`.
- Final app is installed and stopped; it is not enabled at boot. No firewall port, SELinux enforcement, global perf policy or boot setting was changed.

The application report passed headless Edge checks for all three experiment selections, exact p95 values against the derived summaries, phase/comparison tables, profile counts, 300-request evidence download, identical GitHub Pages export, and page layouts at 320, 375 and 768 pixels, with no JavaScript errors. The desktop screenshot was inspected and saved as `app-preview.png`. These are controlled lab results, not a production capacity or monitoring-overhead benchmark.
