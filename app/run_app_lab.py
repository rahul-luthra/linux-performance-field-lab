#!/usr/bin/env python3
"""Bounded open-loop HTTP exercise: 4 arrivals/s; 20s baseline, 30s CPU contention, 25s recovery."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from monitor import snapshot, derive

URL = 'http://127.0.0.1:8087'


def utc():
    return datetime.now(timezone.utc).isoformat()


def phase_at(seconds):
    return 'baseline' if seconds < 20 else 'contention' if seconds < 50 else 'recovery'


def fetch(path='/quote', method='GET'):
    with urlopen(Request(URL + path, method=method), timeout=3) as response:
        return response.status, response.headers, json.loads(response.read())


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--isolated-lab', required=True, action='store_true')
    parser.add_argument('--out', default='results/app-run1')
    parser.add_argument('--cap-background-cpu', action='store_true', help='Place noise in a transient user service capped to one logical CPU')
    args = parser.parse_args()
    out = Path(args.out)
    if out.exists():
        parser.error('Use a new output directory to preserve prior measurements')
    out.mkdir(parents=True)
    tests = []
    for path in ('/health', '/quote', '/quote'):
        status, headers, body = fetch(path)
        assert status == 200
        if path == '/quote':
            assert body['quote'] == 101.052403 and body['iterations'] == 1200000
            assert float(headers['X-Handler-Cpu-Ms']) > 0
        tests.append({'path': path, 'status': status, 'body': body})
    for path, method, expected in [('/missing', 'GET', 404), ('/quote', 'POST', 405)]:
        try:
            fetch(path, method)
            raise AssertionError('Expected HTTP error')
        except HTTPError as exc:
            assert exc.code == expected
            tests.append({'path': path, 'method': method, 'status': exc.code})
    (out / 'functional-tests.json').write_text(json.dumps(tests, indent=2))
    print('Five functional checks passed. Warming the JVM for 20 seconds.', flush=True)
    warm_until = time.monotonic() + 20
    warm_requests = 0
    while time.monotonic() < warm_until:
        began = time.monotonic()
        fetch()
        warm_requests += 1
        time.sleep(max(0, .25 - (time.monotonic() - began)))

    pid = int(subprocess.check_output(['systemctl', 'show', '-p', 'MainPID', '--value', 'quotelab'], text=True).strip())
    assert pid > 0
    env = dict(os.environ, LC_ALL='C', TZ='UTC')
    observers, handles, futures, requests, samples, events = [], [], [], [], [], []
    stop = threading.Event()
    workload = None
    noise_unit = 'quotelab-noise-' + str(os.getpid())
    permits = threading.BoundedSemaphore(8)
    start = time.monotonic()
    start_utc = utc()

    def sample_host():
        old = snapshot()
        while not stop.wait(1):
            new = snapshot()
            item = derive(old, new)
            item['elapsed_s'] = round(new['mono'] - start, 4)
            item['phase'] = phase_at(item['elapsed_s'] - item['interval_s'] / 2)
            samples.append(item)
            old = new

    def request_one(index, scheduled):
        actual = time.monotonic()
        row = {'index': index, 'scheduled_s': scheduled, 'phase': phase_at(scheduled),
               'started_utc': utc(), 'scheduler_lag_ms': round(max(0, actual - start - scheduled) * 1000, 3)}
        try:
            status, headers, body = fetch()
            row.update(status=status, quote=body.get('quote'), handler_wall_ms=float(headers['X-Handler-Wall-Ms']), handler_cpu_ms=float(headers['X-Handler-Cpu-Ms']))
        except Exception as exc:
            row.update(status=0, error=type(exc).__name__ + ': ' + str(exc))
        finally:
            row['latency_ms'] = round((time.monotonic() - actual) * 1000, 3)
            row['scheduled_latency_ms'] = round(row['latency_ms'] + row['scheduler_lag_ms'], 3)
            requests.append(row)
            permits.release()

    def observer(command, name):
        handle = (out / name).open('w')
        handles.append(handle)
        process = subprocess.Popen(command, stdout=handle, stderr=subprocess.STDOUT, env=env)
        observers.append(process)
        return process

    sampler = threading.Thread(target=sample_host, daemon=True)
    try:
        observer(['vmstat', '-w', '-t', '1', '80'], 'vmstat.txt')
        observer(['mpstat', '-P', 'ALL', '1', '80'], 'mpstat.txt')
        observer(['pidstat', '-u', '-p', str(pid), '1', '80'], 'pidstat-java.txt')
        sampler.start()
        with ThreadPoolExecutor(max_workers=8) as executor:
            for index in range(300):
                scheduled = index / 4
                time.sleep(max(0, start + scheduled - time.monotonic()))
                if index in (0, 80, 200):
                    phase = phase_at(scheduled)
                    events.append({'event': phase + '_begin', 'time': utc(), 'elapsed_s': round(time.monotonic() - start, 4)})
                    print('Starting ' + phase, flush=True)
                    if index == 80:
                        command = [sys.executable, str(Path(__file__).resolve().parent.parent / 'lab_cpu.py'), '--isolated-lab', '--workers', '4', '--seconds', '30']
                        if args.cap_background_cpu:
                            command = ['sudo', '-n', 'systemd-run', '--unit=' + noise_unit, '--collect', '--wait', '--quiet', '--service-type=exec',
                                       '--property=User=' + __import__('pwd').getpwuid(os.getuid()).pw_name,
                                       '--property=CPUQuota=100%', '--property=MemoryMax=128M', '--property=TasksMax=16'] + command
                        workload = subprocess.Popen(command)
                        events.append({'event': 'workload_launched', 'pid': workload.pid, 'time': utc()})
                    duration = 18 if index == 0 else 28 if index == 80 else 23
                    observer(['sudo', '-n', 'perf', 'stat', '-x', ';', '-p', str(pid), '-e', 'task-clock,context-switches,cpu-migrations,page-faults', '--', 'sleep', str(duration)], 'perf-' + phase + '.txt')
                if index == 140 and args.cap_background_cpu:
                    properties = subprocess.check_output(['systemctl', 'show', noise_unit, '-p', 'CPUQuotaPerSecUSec', '-p', 'ControlGroup'], text=True)
                    group = next(line.split('=', 1)[1] for line in properties.splitlines() if line.startswith('ControlGroup='))
                    counters = (Path('/sys/fs/cgroup') / group.lstrip('/') / 'cpu.stat').read_text()
                    events.append({'event': 'noise_quota_verified', 'time': utc(), 'properties': properties, 'cpu_stat': counters})
                if permits.acquire(blocking=False):
                    futures.append(executor.submit(request_one, index, scheduled))
                else:
                    requests.append({'index': index, 'scheduled_s': scheduled, 'phase': phase_at(scheduled), 'status': 0, 'error': 'client concurrency cap reached'})
            for future in futures:
                future.result()
        time.sleep(max(0, start + 75 - time.monotonic()))
    finally:
        stop.set()
        if sampler.is_alive():
            sampler.join(timeout=5)
        if workload is not None:
            if workload.poll() is None:
                workload.wait(timeout=5)
            events.append({'event': 'workload_reaped', 'returncode': workload.returncode, 'time': utc()})
        for process in observers:
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=5)
        for handle in handles:
            handle.close()
        system = subprocess.check_output(['systemctl', 'show', 'quotelab', '-p', 'MemoryCurrent', '-p', 'MemoryPeak', '-p', 'CPUUsageNSec', '-p', 'ActiveState'], text=True)
        data = {'schema_version': 1, 'synthetic': False, 'started_utc': start_utc, 'finished_utc': utc(),
                'metadata': {'arrival_rate_rps': 4, 'planned_requests': 300, 'duration_s': 75, 'warmup_requests': warm_requests,
                             'warmup_seconds': 20, 'workers': 4, 'stress_seconds': 30, 'http_timeout_s': 3,
                             'client_concurrency_cap': 8, 'java_pid': pid, 'illustrative_latency_target_ms': 150,
                             'background_cpu_quota': '100% = one logical CPU on this 2-CPU VM' if args.cap_background_cpu else 'unlimited',
                             'service_properties_after': system, 'observer_returncodes': [p.returncode for p in observers],
                             'client_location': 'same VM via loopback; client scheduling lag is recorded separately',
                             'latency_definition': 'HTTP duration from client execution to complete JSON response; server headers measure handler computation wall/thread-CPU, excluding socket/executor queues'},
                'events': events, 'requests': sorted(requests, key=lambda r: r['index']), 'samples': samples}
        (out / 'app-capture.json').write_text(json.dumps(data, indent=2, allow_nan=False))
        assert len(requests) == 300, 'Incomplete arrival record'
        assert workload is not None and workload.returncode == 0
        print(f'Saved {len(requests)} arrivals and {len(samples)} host intervals to {out}', flush=True)


if __name__ == '__main__':
    main()
