"""HTTP/GC experiment: 15s quiet, 25s allocation/reuse, 15s recovery at four arrivals/s."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import argparse
import json
import os
from pathlib import Path
import pwd
import subprocess
import sys
import threading
import time
from urllib.request import urlopen

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def get(path):
    with urlopen('http://127.0.0.1:8088' + path, timeout=3) as response:
        return response.status, response.headers, json.loads(response.read())


def utc(): return datetime.now(timezone.utc).isoformat()
def phase(seconds): return 'baseline' if seconds < 15 else 'allocation' if seconds < 40 else 'recovery'


def run_case(base, name, strategy):
    directory = base / name
    directory.mkdir()
    config = {'name': name, 'mode': 'pressure', 'heap_mib': 32, 'memory_max_mib': 192,
              'heap_dump': False, 'seconds': 85, 'out': str(directory)}
    config_file = directory / 'config.json'
    config_file.write_text(json.dumps(config, indent=2))
    unit = 'mempressure-' + str(os.getpid()) + '-' + name
    user = pwd.getpwuid(os.getuid()).pw_name
    command = ['sudo', '-n', 'systemd-run', '--unit=' + unit, '--wait', '--quiet', '--service-type=exec',
               '--property=User=' + user, '--property=MemoryMax=192M', '--property=MemorySwapMax=0',
               '--property=OOMPolicy=continue', '--property=RuntimeMaxSec=100', '--property=TasksMax=48',
               '--property=NoNewPrivileges=yes', '--property=PrivateTmp=yes', '--property=ProtectSystem=strict',
               '--property=ProtectHome=read-only', '--property=ReadWritePaths=' + str(directory),
               sys.executable, str(HERE / 'supervise.py'), str(config_file)]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    requests, controls, futures = [], [], []
    permits = threading.BoundedSemaphore(8)
    try:
        for _ in range(60):
            if process.poll() is not None: raise RuntimeError('Service failed before readiness: ' + process.stdout.read())
            try:
                status, _, metrics = get('/metrics')
                if status == 200: break
            except Exception: pass
            time.sleep(.25)
        else: raise RuntimeError('Service did not become ready')
        print(name + ': warmup', flush=True)
        for _ in range(60):
            began = time.monotonic()
            status, _, body = get('/quote')
            assert status == 200 and body['quote'] == 101.052403 and body['checksum'] == 0
            time.sleep(max(0, .25 - (time.monotonic() - began)))
        start, started_utc = time.monotonic(), utc()

        def request_one(index, scheduled):
            actual = time.monotonic()
            row = {'index': index, 'scheduled_s': scheduled, 'phase': phase(scheduled),
                   'scheduler_lag_ms': round(max(0, actual - start - scheduled) * 1000, 3)}
            try:
                status, headers, body = get('/quote')
                row.update(status=status, quote=body['quote'], checksum=body['checksum'],
                           handler_wall_ms=float(headers['X-Handler-Wall-Ms']), handler_cpu_ms=float(headers['X-Handler-Cpu-Ms']))
            except Exception as exc: row.update(status=0, error=type(exc).__name__ + ': ' + str(exc))
            finally:
                row['latency_ms'] = round((time.monotonic() - actual) * 1000, 3)
                requests.append(row)
                permits.release()

        with ThreadPoolExecutor(max_workers=8) as executor:
            for index in range(220):
                scheduled = index / 4
                time.sleep(max(0, start + scheduled - time.monotonic()))
                if index in (0, 60, 160):
                    setting = strategy if index == 60 else 'quiet'
                    status, _, metrics = get('/mode?value=' + setting)
                    assert status == 200 and metrics['strategy'] == setting
                    controls.append({'time': utc(), 'elapsed_s': round(time.monotonic() - start, 4), 'strategy': setting})
                    print(name + ': ' + phase(scheduled), flush=True)
                if permits.acquire(blocking=False): futures.append(executor.submit(request_one, index, scheduled))
                else: requests.append({'index': index, 'scheduled_s': scheduled, 'phase': phase(scheduled), 'status': 0, 'error': 'client cap'})
            for future in futures: future.result()
        time.sleep(max(0, start + 55 - time.monotonic()))
        data = {'name': name, 'synthetic': False, 'strategy': strategy, 'started_utc': started_utc,
                'finished_utc': utc(), 'load_start_monotonic': start,
                'metadata': {'heap_mib': 32, 'service_limit_mib': 192, 'retained_cache_mib': 16,
                             'scratch_mib_per_request': 64, 'rate_rps': 4, 'seconds': 55, 'warmup_requests': 60,
                             'client_location': 'same VM via loopback', 'client_cap': 8, 'request_timeout_s': 3,
                             'note': 'reuse clears/touches the same 64 MiB logical scratch volume using a per-worker 1 MiB buffer; allocation and memory-locality costs both change'},
                'controls': controls, 'requests': sorted(requests, key=lambda r: r['index'])}
        (directory / 'http.json').write_text(json.dumps(data, indent=2))
    finally:
        (directory / 'stop').touch()
        try: output = process.communicate(timeout=15)[0]
        except subprocess.TimeoutExpired:
            subprocess.run(['sudo', '-n', 'systemctl', 'stop', unit], capture_output=True)
            output = process.communicate(timeout=10)[0]
        (directory / 'unit-command.txt').write_text(' '.join(command) + '\n' + output)
        state = subprocess.run(['systemctl', 'show', unit, '-p', 'Result', '-p', 'ExecMainStatus', '-p', 'ActiveState'], capture_output=True, text=True)
        (directory / 'unit-result.txt').write_text(state.stdout)
        subprocess.run(['sudo', '-n', 'systemctl', 'reset-failed', unit], capture_output=True)
    result = json.loads((directory / 'capture.json').read_text())
    assert result['stopped_by_harness'] and result['event_deltas'].get('oom_kill', 0) == 0, 'Unexpected service death'
    assert len(requests) == 220
    print(name + ': saved 220 arrivals', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--isolated-lab', required=True, action='store_true')
    parser.add_argument('--out', default='results/memory/pressure')
    args = parser.parse_args()
    base = (ROOT / args.out).resolve()
    if base.exists(): parser.error('Use a new output directory')
    base.mkdir(parents=True)
    for name, strategy in [('allocation-a', 'allocate'), ('allocation-b', 'allocate'), ('reuse-corrected', 'reuse')]:
        available = next(int(line.split()[1]) for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith('MemAvailable:'))
        if available < 600 * 1024: raise RuntimeError('Less than 600 MiB available; abort')
        run_case(base, name, strategy)
        time.sleep(2)


if __name__ == '__main__': main()
