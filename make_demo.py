"""Deterministic illustrative traces, not measurements or benchmark results."""
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
from monitor import build_report


def make_case(kind, title, description):
    samples = []
    for i in range(90):
        active = 20 <= i < 60
        wobble = math.sin(i * .6)
        cpu, load, available, cp, io, mp, latency, queue, busy, blocked = 24, 1.4, 62, .2, .3, .1, 1.2, .08, 8, 0
        if active and kind == 'cpu':
            cpu, load, cp = 96 + wobble, 11 + wobble, 32 + wobble
        if active and kind == 'io':
            cpu, load, io, latency, queue, busy, blocked = 28, 15 + wobble, 43 + wobble, 72 + wobble, 14.4, 94, 12
        if active and kind == 'memory':
            available, mp, io, cpu = 4 + wobble, 26 + wobble, 16, 49
        if kind == 'cache':
            available, cpu = 44 + wobble, 18
        samples.append({'time': (datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=i+1)).isoformat(),
                        'interval_s': 1, 'cores': 4, 'cpu_busy_pct': round(cpu, 2),
                        'cpu_iowait_pct': 38 if active and kind == 'io' else 1,
                        'cpu_steal_pct': 0, 'load1': round(load, 2),
                        'procs_running': 12 if active and kind == 'cpu' else 2, 'procs_blocked': blocked,
                        'mem_available_pct': round(available, 2), 'cached_mib': 9800 if kind == 'cache' else 2200,
                        'swap_used_mib': 1800 if active and kind == 'memory' else 0,
                        'psi': {'cpu': {'some': round(cp, 2)}, 'io': {'some': round(io, 2), 'full': round(io/3, 2)},
                                'memory': {'some': round(mp, 2), 'full': round(mp/4, 2)}},
                        'disk': {'vda': {'rw_iops': 200 if active and kind == 'io' else 65,
                                         'rw_await_ms': round(latency, 2), 'avg_queue': queue, 'busy_pct': busy,
                                         'read_mib_s': 2, 'write_mib_s': 4}},
                        'net': {'eth0': {'rx_mib_s': .6, 'tx_mib_s': 1.2, 'errors_s': 0, 'drops_s': 0}}, 'warnings': []})
    return {'schema_version': 1, 'synthetic': True, 'title': title,
            'description': description + ' Illustrative 90-second trace: intervals 21–60 show the scenario; other intervals show a baseline. These are hand-designed signals, not a physics simulation.', 'samples': samples}


if __name__ == '__main__':
    root = Path(__file__).parent
    cases = [make_case('io', 'High load, modest CPU: follow the I/O stalls', 'Does adding CPU address work waiting on storage?'),
             make_case('cpu', 'CPU contention: execution plus waiting', 'High utilization becomes more meaningful when runnable work also waits.'),
             make_case('memory', 'Memory pressure: look beyond a used-memory chart', 'Low available memory and stalled work warrant investigation of reclaim and limits.'),
             make_case('cache', 'Healthy cache: avoid a false memory alarm', 'Large filesystem cache with available memory and negligible pressure is not evidence of exhaustion.')]
    data = {'schema_version': 1, 'cases': cases}
    (root / 'demo-data.json').write_text(json.dumps(data, indent=2), encoding='utf-8')
    measured = root / 'results' / 'cpu-lab.json'
    if measured.exists():
        build_report({'schema_version': 1, 'cases': [json.loads(measured.read_text(encoding='utf-8'))] + cases}, root / 'showcase.html')
    else:
        build_report(data, root / 'showcase.html')
    print('Created demo-data.json and showcase.html')
