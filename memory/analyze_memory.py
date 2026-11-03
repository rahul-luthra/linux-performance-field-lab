"""Classify measured failures, summarize request/GC windows and generate a standalone report."""
from datetime import datetime
import json
import math
from pathlib import Path
import re
import statistics
import sys

ROOT = Path(__file__).resolve().parent.parent
WINDOWS = {'baseline': (2, 13), 'allocation': (17, 38), 'recovery': (42, 53)}


def avg(values): return round(statistics.mean(values), 3) if values else None
def percentile(values, fraction):
    values = sorted(values)
    return round(values[math.ceil(len(values) * fraction) - 1], 3) if values else None


def counter_delta(first, last, key):
    old, new = first.get(key), last.get(key)
    return new - old if old is not None and new is not None and new >= old else None


def classify(capture, application_log):
    killed = capture.get('event_deltas', {}).get('oom_kill')
    if killed is None: return 'Inconclusive: cgroup OOM counter unavailable'
    if killed > 0 and capture.get('java_returncode') == -9:
        return 'Linux cgroup OOM kill'
    if 'OutOfMemoryError: Java heap space' in application_log and killed == 0 and capture.get('java_returncode') == 3:
        return 'Java heap exhaustion'
    if capture.get('allocation_complete') and capture.get('stopped_by_harness') and killed == 0:
        return 'Bounded allocation completed'
    return 'Inconclusive: inspect evidence'


def summarize_pressure(http, capture):
    result = {}
    for phase, (start, end) in WINDOWS.items():
        arrivals = [r for r in http['requests'] if start <= r['scheduled_s'] < end]
        expected_checksum = 114688 if phase == 'allocation' else 0
        good = [r for r in arrivals if r['status'] == 200 and r.get('quote') == 101.052403 and r.get('checksum') == expected_checksum]
        samples = [s for s in capture['samples'] if start <= s.get('monotonic', -1) - http['load_start_monotonic'] < end]
        jvms = [s for s in samples if 'jvm' in s]
        # Counter deltas span the first to last available metrics samples in the stable window.
        first, last = (jvms[0]['jvm'], jvms[-1]['jvm']) if jvms else ({}, {})
        completed = [r for r in http['requests'] if r['status'] == 200 and r.get('quote') == 101.052403 and
                     r.get('checksum') == (114688 if 15 <= r['scheduled_s'] < 40 else 0) and
                     start <= r['scheduled_s'] + (r['scheduler_lag_ms'] + r['latency_ms']) / 1000 < end]
        result[phase] = {'window_s': [start, end], 'arrivals': len(arrivals), 'successes': len(good),
                         'errors': len(arrivals) - len(good), 'completions_per_s': round(len(completed) / (end-start), 3),
                         'p50_ms': percentile([r['latency_ms'] for r in good], .5),
                         'p95_ms': percentile([r['latency_ms'] for r in good], .95),
                         'p99_ms': percentile([r['latency_ms'] for r in good], .99),
                         'handler_cpu_mean_ms': avg([r['handler_cpu_ms'] for r in good]),
                         'handler_wall_mean_ms': avg([r['handler_wall_ms'] for r in good]),
                         'client_lag_p95_ms': percentile([r.get('scheduler_lag_ms', 0) for r in arrivals], .95),
                         'gc_count_delta': counter_delta(first, last, 'gc_count') if len(jvms) >= 2 else None,
                         'gc_time_delta_ms': counter_delta(first, last, 'gc_ms') if len(jvms) >= 2 else None,
                         'gc_counter_window_s': round(jvms[-1]['monotonic'] - jvms[0]['monotonic'], 3) if jvms else None,
                         'cgroup_mean_mib': avg([s['cgroup_current_bytes']/1048576 for s in samples if s['cgroup_current_bytes'] is not None]),
                         'host_cpu_mean_pct': avg([s['host_cpu_pct'] for s in samples if s.get('host_cpu_pct') is not None])}
    return result


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', default='results/memory')
    args = parser.parse_args()
    evidence = (ROOT / args.evidence).resolve()
    faults = []
    for directory in sorted((evidence / 'faults').iterdir()):
        if not directory.is_dir(): continue
        capture = json.loads((directory / 'capture.json').read_text())
        log = (directory / 'application.log').read_text()
        summary = {'name': capture['name'], 'outcome': classify(capture, log), 'heap_mib': capture['config']['heap_mib'],
                   'service_limit_mib': capture['config']['memory_max_mib'], 'java_returncode': capture['java_returncode'],
                   'oom_kills': capture['event_deltas'].get('oom_kill'), 'allocation_complete': capture['allocation_complete'],
                   'cgroup_peak_mib': round(int(capture['cgroup_peak_bytes'])/1048576, 2) if capture['cgroup_peak_bytes'] else None,
                   'minimum_host_available_mib': min(s['host_available_mib'] for s in capture['samples']),
                   'last_retained_mib': max((s['jvm']['retained_mib'] for s in capture['samples'] if 'jvm' in s), default=None),
                   'evidence': {'exit_code': capture['java_returncode'], 'event_deltas': capture['event_deltas'],
                                'java_heap_error': 'OutOfMemoryError: Java heap space' in log}}
        (directory / 'summary.json').write_text(json.dumps(summary, indent=2))
        faults.append({'summary': summary, 'capture': capture})
    pressure = []
    for directory in sorted((evidence / 'pressure').iterdir()):
        if not directory.is_dir() or not (directory / 'http.json').exists(): continue
        http, capture = [json.loads((directory / name).read_text()) for name in ('http.json', 'capture.json')]
        summary = summarize_pressure(http, capture)
        (directory / 'summary.json').write_text(json.dumps(summary, indent=2))
        pressure.append({'name': directory.name, 'http': http, 'capture': capture, 'summary': summary})
    public = {'faults': faults, 'pressure': pressure}
    (evidence / 'summary.json').write_text(json.dumps({'faults': [f['summary'] for f in faults], 'pressure': {p['name']: p['summary'] for p in pressure}}, indent=2))
    payload = json.dumps(public, allow_nan=False).replace('&', '\\u0026').replace('<', '\\u003c').replace('>', '\\u003e')
    html = (ROOT / 'memory/report-template.html').read_text(encoding='utf-8').replace('__MEMORY_DATA__', payload)
    (ROOT / 'memory-report.html').write_text(html, encoding='utf-8')
    sys.path.insert(0, str(ROOT))
    from build_pages import build
    build()
    print(json.dumps({'faults': [f['summary'] for f in faults], 'pressure': {p['name']: p['summary'] for p in pressure}}, indent=2))


if __name__ == '__main__': main()
