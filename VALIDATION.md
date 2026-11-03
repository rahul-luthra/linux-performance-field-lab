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

## Private review and HTML links (before publication)

All six generated HTML files were opened locally in headless Edge: `app-report.html`, `docs/index.html`, `showcase.html`, `results/cpu-lab.html`, `results/repeat/cpu-lab.html`, and `results/smoke-report.html`. Each rendered charts and its experiment/interval controls without JavaScript errors. The two remaining HTML files are authoring templates with unresolved data placeholders, not finished reports.

GitHub's repository viewer displays these HTML files as source. The private-review update distinguished source, rendered PNG previews, and the downloadable offline review bundle. `VIEWING_REPORTS.md` inventories every generated report. `app-latency-preview.png` was captured directly from the rendered application chart for inline GitHub review. At that stage the repository was private and Pages was off; publication was authorized afterward.

## GitHub Pages publication

The repository is now public and Pages publishes `main` → `/docs` at https://rahul-luthra.github.io/linux-performance-field-lab/ with HTTPS enforced. Six generated pages share relative navigation: the application report, memory investigation, Linux scenarios, first and repeated CPU captures, and collector check. Their root-file counterparts remain usable offline.

`build_pages.py` exports the report copies; application analysis and release preparation invoke it to keep the site in sync. All five hosted URLs returned HTTP 200 in an anonymous Edge browser context. Experiment and interval controls, navigation between application/host reports, 300-request JSON evidence download, and layouts at 320/375/768 pixels passed without JavaScript errors. GitHub reported a successful Pages build. The site visualizes saved measurements and does not connect to the VM.

## Memory/JVM extension

Six allocation cases ran as isolated transient units: two heap-exhaustion cases, one heap-sizing correction, two cgroup memory-limit kills, and one cgroup-limit correction. The heap failures exited with code 3 and explicit heap-space errors with zero cgroup kills. The Linux kills returned signal 9 and incremented the same-cgroup OOM-kill counter by one. Corrected cases completed their finite targets and were intentionally stopped at the observation deadline.

Three 55-second HTTP runs recorded 220 arrivals each after 60 warmup requests. All 660 measured arrivals returned expected quote/checksum values. Two fresh-array runs and a reusable-buffer trial retained raw HTTP, JVM/GC and cgroup measurements. The first run's elevated recovery tail is retained and documented rather than attributed to GC.

Nine new classification/statistics tests passed on Windows and Linux; Linux output is `results/memory-tests.txt`. They cover missing/reset counters, signal-versus-OOM attribution, configured JVM heap error evidence, bounded completion, correct-response/error denominators, GC sampling windows and percentile handling. Local and anonymous live Edge browser checks passed for all six Pages routes, the six fault and three HTTP selections, plotted series, an OOM evidence download, navigation and mobile layouts. All six hosted URLs returned HTTP 200, no JavaScript errors were recorded, and GitHub reported a successful HTTPS Pages build. The memory report screenshot is `memory-preview.png`.

Cleanup checks found no MemoryLab, supervisor or test-runner processes, no port-8088 listener and no remaining memory transient units. Host available memory was about 920 MiB afterward. One approximately 33-MiB heap dump remains only in the VM's raw test directory. Heap dumps, class files and raw JVM recordings are excluded from the release. The original QuoteLab service was not changed or started during this extension. No global swap, kernel/boot, SELinux or network-exposure settings changed.


## Storage / NFS extension

Ten measured cases used two Oracle Linux 9.7 VMs: local/NFS baseline, two controlled NFS reply-delay cases, early recovery, two unrestricted/capped server-I/O pairs, and final quiet recovery. All 1,200 measured requests returned the expected response/checksum; all client readbacks and all nine independent NFS-server readbacks matched. HTTP summaries use 104 central-window arrivals per case; RPC snapshots cover all 120 arrivals. Warmup is excluded.

The deliberate 20-ms reply delay raised WRITE mean RTT from 7.8 to 30.6/30.5 ms; removal returned it to 8.7 ms. The I/O cap reduced background completed writes but did not establish consistent latency improvement. The final quiet HTTP p95 remained 235.4 ms. Late baseline drift is explicitly unresolved, including shared physical-host/backing-storage and nearly full server-filesystem limitations. No natural disk root cause, power-loss durability or successful disk-latency mitigation is claimed.

Ten additional storage-analysis tests pass on Windows and Linux; Linux output is `results/storage-tests.txt`. They check mount selection, RPC units/retransmission/reset/in-flight handling, unknown values, completion-weighted disk await, percentiles and correct-response denominators. All seven local Pages routes passed Edge checks, including ten storage selections, both host charts, RPC values, 120-request evidence download, existing memory/CPU/app controls, eight navigation links per page, and mobile widths 320/375/768 without JavaScript errors. The rendered storage report was inspected and saved as `storage-preview.png`.

Final setup evidence records SELinux enforcing, NFSv4-only server service enabled/active, a single-client export and TCP-2049 firewall rule, a hard NFSv4.2 mount, ordinary-user access and denied direct root writes. The original fq_codel policy was restored (quantum 1464), the rollback timer was inactive and its temporary state removed. Bounded synthetic files removed: 16 MiB client-local and 208 MiB server-side. The persistent share/mount remain available. No test application/background writer remains running. The cloned server received a unique machine ID and SSH host keys and now boots headlessly; private identity backups remain only in its root directory.

Public evidence exports replace lab addresses and sysstat hostname headers with role labels. Named release allowlists exclude SSH files, compiled classes, synthetic binary data, JVM dumps and credentials. The static site does not connect to the VMs.
