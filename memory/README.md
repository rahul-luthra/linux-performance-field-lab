# Reproduce the bounded memory investigation

Use an isolated two-CPU Oracle Linux lab VM with OpenJDK 17 runtime, a JDK 17+ compiler, Python 3.9+, cgroup v2 and sudo access. This deliberately causes Java failure and cgroup-local OOM kills. It does not aim to exhaust host memory. Use at least 600 MiB available memory and room for a roughly 33 MiB heap dump plus small logs. The tested VM had about 1.5 GiB RAM.

## Install the inspected classes

From the project root:

```sh
javac --release 17 --add-modules jdk.httpserver -d memory/build memory/MemoryLab.java app/QuoteLab.java
sudo install -d -m 0755 /opt/linux-performance-field-lab/memory
sudo install -m 0644 memory/build/MemoryLab.class memory/build/QuoteLab.class /opt/linux-performance-field-lab/memory/
```

The runtime path in `supervise.py` is Oracle Linux's `/usr/lib/jvm/jre-17-openjdk/bin/java`. Adapt that explicit path if reproducing on another distribution. No external Java libraries are required. Source and class files are separate from the original QuoteLab service.

## Run into new directories

The repository includes the original measured evidence, so use fresh output directories to preserve it:

```sh
python3 memory/run_memory_lab.py --isolated-lab --out results/memory-replay/faults
python3 memory/run_pressure_lab.py --isolated-lab --out results/memory-replay/pressure
python3 memory/analyze_memory.py --evidence results/memory-replay
python3 build_pages.py
python3 -m unittest discover -s memory -v
```

The fault runner performs six cases: two 32-MiB heap failures with a 48-MiB finite heap target; a 96-MiB heap correction; two 96-MiB cgroup failures with an 80-MiB direct-buffer target; and a 192-MiB cgroup correction. Each observes at most 20 seconds, and each service has a 40-second hard timeout. The first heap failure writes a heap dump; the repeat does not.

The HTTP runner performs fresh-array A, fresh-array B and buffer-reuse runs. Each has 60 warmup requests at approximately four/second, then 220 measured arrivals across 15/25/15-second phases. Each service has an 85-second supervisor timeout and a 100-second hard unit timeout. It records client admission/scheduling, status/body correctness, HTTP and handler timing, plus quarter-second JVM and cgroup observations. The reusable version clears/touches the same logical scratch volume but changes allocation and locality costs.

The analysis rewrites `memory-report.html` from the selected evidence. Run `build_pages.py` to refresh the hosted copy. Publishing a replay should include its own environment/timing context and avoid overwriting the original evidence accidentally.

## Why there is a supervisor

Java runs as a child of a small Python supervisor inside the limited test cgroup. The supervisor preserves `memory.events` after Java exits and saves child return codes. It uses `OOMPolicy=continue`, observes `memory.oom.group`, and raises only the Java child's OOM selection score when allowed. The service limit covers the supervisor, Java and charged cache; it is not Java RSS.

Java and Python run as the invoking user. Sudo is required for class installation and transient unit/resource settings. The test unit uses a read-only home/system view with the selected evidence directory writable, no new privileges, private temporary storage, a 48-task cap and no cgroup swap. No global memory or swap setting is changed.

Each server binds only to `127.0.0.1:8088`. `/metrics` exposes heap and GC counters; `/mode` switches only among quiet/allocate/reuse in the HTTP experiment. These are local teaching endpoints and are not suitable for direct internet deployment.

## Cleanup and evidence handling

The harness saves its record before exiting, reaps Java, and resets failed transient units. If interrupted, inspect `systemctl list-units --all 'memlab-*' 'mempressure-*'` and stop the specific remaining unit before retrying. Units also have hard runtime limits. Do not stop unrelated services.

`*.hprof` and local build outputs are ignored by Git. Heap dumps can contain application data; do not upload them as part of the public evidence. The release builder accepts only named text/JSON/GC files from the canonical evidence directories. Full GC logs may contain process virtual addresses from already-ended lab processes; they are not credentials or host network endpoints.

The original runs used private raw directories on the VM. Text-only copies were exported into `results/memory/faults` and `results/memory/pressure`; the capture metadata preserves the original paths and commands. The first unsupported transient-unit property attempt produced no measurement and is not included as an experiment. The final source uses the supported defaults.
