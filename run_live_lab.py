#!/usr/bin/env python3
"""Run a bounded, opt-in Linux CPU experiment with independent observer logs."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import resource
import shlex
import shutil
import statistics
import subprocess
import sys
import time
from monitor import snapshot, derive, build_report


def utc():
    return datetime.now(timezone.utc).isoformat()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--isolated-lab', action='store_true', required=True)
    parser.add_argument('--out-dir', default='results')
    args = parser.parse_args()
    if platform.system() != 'Linux':
        parser.error('Linux is required')
    if (os.cpu_count() or 1) != 2:
        parser.error('This experiment protocol expects a 2-vCPU VM')
    out = Path(args.out_dir)
    out.mkdir(exist_ok=True, parents=True)
    files, observers, events, samples, timings = [], [], [], [], []
    workload = None
    release = dict(line.split('=', 1) for line in Path('/etc/os-release').read_text().splitlines() if '=' in line and not line.startswith('#'))
    metadata = {'os': ' '.join(shlex.split(release.get('PRETTY_NAME', 'Linux'))),
                'kernel': platform.release(), 'python': platform.python_version(),
                'logical_cpus': os.cpu_count(), 'affinity_cpus': sorted(os.sched_getaffinity(0)),
                'started_utc': utc(), 'workers': 4, 'workload_seconds': 30,
                'baseline_intervals': 15, 'total_intervals': 75,
                'pressure_available': {r: Path('/proc/pressure/' + r).exists() for r in ('cpu', 'memory', 'io')},
                'observer_tools': {tool: shutil.which(tool) for tool in ('vmstat', 'mpstat', 'pidstat')},
                'filesystem_available_mib': round(shutil.disk_usage('.').free / 1048576, 1)}
    # Probe only CPU control settings, not environment variables or arbitrary proc command lines.
    cpu_controls = {}
    for name in ('cpu.max', 'cpu.stat', 'cpuset.cpus.effective'):
        try:
            cpu_controls[name] = (Path('/sys/fs/cgroup') / name).read_text().strip()
        except OSError:
            cpu_controls[name] = None
    metadata['cgroup_root_cpu_controls'] = cpu_controls
    metadata['note'] = 'Host-scoped lab, no application latency/throughput measured. Root cgroup controls do not establish all ancestor/workload constraints.'
    cpu_before = time.process_time()
    try:
        env = dict(os.environ, LC_ALL='C', TZ='UTC')
        for tool, arguments in [('vmstat', ['-w', '-t', '1', '77']), ('mpstat', ['-P', 'ALL', '1', '76']), ('pidstat', ['-u', '-p', 'ALL', '1', '76'])]:
            if shutil.which(tool):
                handle = (out / (tool + '.txt')).open('w')
                files.append(handle)
                observers.append(subprocess.Popen([tool] + arguments, stdout=handle, stderr=subprocess.STDOUT, env=env))
        previous = snapshot()
        for index in range(75):
            if index == 15:
                events.append({'event': 'workload_launch_requested', 'time': utc(), 'after_interval': index})
                workload = subprocess.Popen([sys.executable, 'lab_cpu.py', '--isolated-lab', '--workers', '4', '--seconds', '30'])
            running_before = workload is not None and workload.poll() is None
            time.sleep(1)
            started = time.perf_counter()
            current = snapshot()
            sample = derive(previous, current)
            timings.append((time.perf_counter() - started) * 1000)
            running_after = workload is not None and workload.poll() is None
            if index < 15:
                phase = 'baseline'
            elif running_before and running_after:
                phase = 'workload'
            elif running_before:
                phase = 'transition'
                events.append({'event': 'workload_exit_observed', 'time': utc(), 'returncode': workload.returncode, 'interval': index+1})
            else:
                phase = 'recovery'
            sample['phase'] = phase
            samples.append(sample)
            previous = current
            if index in (14, 29, 44, 59, 74):
                print(f'{index+1}/75 intervals: {phase}, CPU={sample["cpu_busy_pct"]}%', flush=True)
    finally:
        if workload is not None:
            if workload.poll() is None:
                workload.terminate()
            workload.wait(timeout=10)
        for process in observers:
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=10)
        for handle in files:
            handle.close()
        metadata['finished_utc'] = utc()
        metadata['recorder_cpu_seconds'] = round(time.process_time() - cpu_before, 4)
        metadata['recorder_max_rss_kib'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        metadata['sample_compute_median_ms'] = round(statistics.median(timings), 3) if timings else None
        metadata['workload_returncode'] = workload.returncode if workload is not None else None
        data = {'schema_version': 1, 'synthetic': False, 'title': 'Measured: four CPU workers on a 2-vCPU Linux VM',
                'description': 'Actual Linux measurements: 15 baseline intervals, a 30-second four-worker CPU workload, then recovery. PSI was unavailable on this VM; independent vmstat and mpstat logs accompany this capture.',
                'metadata': metadata, 'events': events, 'samples': samples}
        (out / 'cpu-lab.json').write_text(json.dumps(data, indent=2, allow_nan=False))
        build_report(data, out / 'cpu-lab.html')
        if len(samples) != 75 or metadata['workload_returncode'] != 0:
            raise RuntimeError('Incomplete experiment; inspect saved capture')


if __name__ == '__main__':
    main()
