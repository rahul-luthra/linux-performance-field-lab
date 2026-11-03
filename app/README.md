# QuoteLab application experiment

A small Java HTTP service running a deterministic, intentionally CPU-heavy quote calculation. It uses the JDK HTTP server and no external Java libraries. It is a teaching application, not a production pricing system.

## Install on an Oracle Linux lab VM

Requires two CPUs, Python 3.9+, a JDK 17+ compiler, an OpenJDK 17 runtime, curl, sysstat and perf. On a fresh Oracle Linux 9 lab, install the distribution packages with signature checking enabled:

```sh
sudo dnf install java-17-openjdk-devel python3 curl sysstat perf
cd app
sh install.sh
cd ..
```

The tested VM already had a Java 26 compiler and sysstat. Only the Oracle-repository headless OpenJDK 17 runtime, perf and their dependencies were installed: approximately 200 MB combined installed package size. The pre-existing Java 26 runtime failed in this restricted service environment; the successful measured runs used the distribution's OpenJDK 17 runtime. The service references its explicit runtime path, avoiding a change to other applications' launch commands.

Installation writes the class/source to `/opt/linux-performance-field-lab/quotelab` and the unit to `/etc/systemd/system/quotelab.service`. It starts the app but does not enable it at boot. Health readiness is checked before installation reports success.

The app binds only to loopback port 8087, runs under a dynamic non-root user, has a 64 MiB maximum Java heap and 256 MiB service memory limit, and uses read-only system/home restrictions. It is not intended for direct public deployment.

```sh
curl http://127.0.0.1:8087/health
curl -i http://127.0.0.1:8087/quote
```

`/quote` runs 1,200,000 deterministic calculation steps and returns the same rounded result. Headers expose computation wall time and thread CPU time. These timings exclude HTTP-server executor/socket queues, response formatting, and network transport. Errors are tested with `/missing` and POST to `/quote`.

## Reproduce the measurements

From the project root:

```sh
python3 app/run_app_lab.py --isolated-lab --out results/app-run1
python3 app/run_app_lab.py --isolated-lab --out results/app-run2
python3 app/run_app_lab.py --isolated-lab --out results/app-mitigated --cap-background-cpu
python3 app/analyze_app.py
```

Each invocation requires a new output directory and takes about 95 seconds: a 20-second warmup plus a 75-second experiment. Five functional checks run first. The request generator schedules 4 arrivals/s independently of previous request completions, with eight client workers, a three-second HTTP timeout and explicit rejection records if the concurrency cap is reached. This avoids silently reducing offered traffic when requests slow. It remains a small co-located load generator, not a production capacity benchmark.

The three phases are 20 seconds baseline, 30 seconds with four competing CPU processes, and 25 seconds recovery. The analysis uses central windows 2–18, 22–48 and 52–73 seconds to reduce boundary effects. Raw data retains every arrival and host sample. One-second host sampling produces 74 completed intervals over 75 seconds because reads have overhead and the final partial interval is omitted.

The mitigated run uses a transient systemd service with `CPUQuota=100%`, meaning one logical CPU's execution time on a two-CPU machine. The noise runs as the invoking user, has 128 MiB memory and 16-task limits, ends after 30 seconds, and is automatically collected. Its CPU quota and throttling counters are recorded during the run. Ordinary tests do not change the Java app's resource settings.

The app runs without root; root is used to install/manage the service, attach perf to its separate user, and create the transient quota service. The runner stops observers and reaps the workload. Interruptions should be followed by checking for remaining lab workers/transient units before another run.

## Profiling and interpretation

Per-phase perf files attach to the Java PID and record task-clock, context switches, migrations and page faults. Their 18/28/23-second windows are not identical to the trimmed analysis windows. Do not compare system-wide task-clock directly with execution utilization: system-wide clock events can include idle tasks. The collected files are process-scoped.

JFR starts with the Java service using `settings=profile`; recordings are limited to 16 MB on disk. To save a recording after a test:

```sh
sudo systemctl stop quotelab
sudo cp /var/lib/quotelab/recording.jfr results/java-recording.jfr
sudo chown "$(id -un):$(id -gn)" results/java-recording.jfr
jfr print --json --events jdk.ExecutionSample,jdk.GarbageCollection results/java-recording.jfr > results/java-profile-events.json
python3 app/analyze_app.py
```

The `jfr` tool requires a JDK installation. Full recordings and raw JFR exports are excluded from the public release; only a narrow method-count summary is included. The supplied summary covers the first two experiments and warmup, not the separately restarted mitigation recording. Execution samples identify running code, not time waiting for a scheduler. The evidence supports CPU contention, but is not a direct off-CPU trace or complete GC analysis.

## Stop and restart

The delivered VM is left with the app installed and stopped after testing. It is not enabled at boot.

```sh
sudo systemctl start quotelab
sudo systemctl stop quotelab
sudo systemctl status quotelab
```

Java's normal SIGTERM exit code 143 is explicitly treated as a successful service stop. No firewall ports, SELinux enforcement, boot parameters, or global perf restrictions were changed.
