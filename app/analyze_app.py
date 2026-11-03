"""Analyze raw measurements and build a self-contained application evidence report."""
from collections import Counter
from datetime import datetime
import json
import math
from pathlib import Path
import statistics

ROOT = Path(__file__).resolve().parent.parent
WINDOWS = {'baseline': (2, 18), 'contention': (22, 48), 'recovery': (52, 73)}


def percentile(values, p):
    values = sorted(values)
    return round(values[max(0, math.ceil(p * len(values)) - 1)], 3) if values else None


def avg(values):
    return round(statistics.mean(values), 3) if values else None


def summarize(data):
    result = {}
    for phase, (start, end) in WINDOWS.items():
        arrivals = [r for r in data['requests'] if start <= r['scheduled_s'] < end]
        success = [r for r in arrivals if r['status'] == 200 and r.get('quote') == 101.052403]
        samples = [s for s in data['samples'] if start <= s['elapsed_s'] < end]
        completed = [r for r in data['requests'] if r['status'] == 200 and r.get('quote') == 101.052403 and
                     start <= r['scheduled_s'] + (r['scheduler_lag_ms'] + r['latency_ms']) / 1000 < end]
        result[phase] = {'stable_window_s': [start, end], 'offered_requests': len(arrivals),
                         'successful_requests': len(success), 'errors_or_rejected': len(arrivals) - len(success),
                         'successful_completions_per_second': round(len(completed) / (end - start), 3),
                         'latency_ms': {'mean': avg([r['latency_ms'] for r in success]),
                                        **{f'p{int(p*100)}': percentile([r['latency_ms'] for r in success], p) for p in (.5, .95, .99)}},
                         'handler_wall_mean_ms': avg([r['handler_wall_ms'] for r in success]),
                         'handler_cpu_mean_ms': avg([r['handler_cpu_ms'] for r in success]),
                         'scheduler_lag_p95_ms': percentile([r.get('scheduler_lag_ms', 0) for r in arrivals], .95),
                         'over_illustrative_150ms': sum(r['latency_ms'] > 150 for r in success),
                         'host_cpu_mean_pct': avg([s['cpu_busy_pct'] for s in samples if s['cpu_busy_pct'] is not None]),
                         'runnable_mean': avg([s['procs_running'] for s in samples]),
                         'load1_mean': avg([s['load1'] for s in samples]),
                         'available_memory_mean_pct': avg([s['mem_available_pct'] for s in samples]),
                         'host_intervals': len(samples)}
    return result


def profile_summary(path):
    events = json.loads(path.read_text())['recording']['events']
    stacks = Counter()
    quote_stacks = 0
    execution = 0
    for event in events:
        if event['type'] != 'jdk.ExecutionSample':
            continue
        execution += 1
        frames = (event['values'].get('stackTrace') or {}).get('frames', [])
        methods = [frame.get('method', {}) for frame in frames]
        names = [(method.get('type') or {}).get('name', '?').replace('/', '.') + '.' + method.get('name', '?') for method in methods]
        if names:
            stacks[names[0]] += 1
        quote_stacks += any(name == 'QuoteLab.quote' for name in names)
    return {'execution_samples': execution, 'samples_with_QuoteLab_quote_on_stack': quote_stacks,
            'top_frame_counts': dict(stacks.most_common(10)),
            'scope': 'Sampled Java execution across service recording, including warmup and both experiments. Counts are not elapsed-time percentages or a scheduler/off-CPU profile.'}


def main():
    runs = []
    for name in ('app-run1', 'app-run2', 'app-mitigated'):
        directory = ROOT / 'results' / name
        capture = directory / 'app-capture.json'
        if not capture.exists():
            continue
        data = json.loads(capture.read_text())
        summary = summarize(data)
        (directory / 'summary.json').write_text(json.dumps(summary, indent=2))
        runs.append({'name': name, 'data': data, 'summary': summary})
        print(name, json.dumps(summary, indent=2))
    assert runs, 'No measured captures found'
    public_profile = ROOT / 'results' / 'java-profile-summary.json'
    raw_profile = ROOT / 'results' / 'java-profile-events.json'
    if raw_profile.exists():
        public_profile.write_text(json.dumps(profile_summary(raw_profile), indent=2))
    profile = json.loads(public_profile.read_text()) if public_profile.exists() else None
    payload = json.dumps({'runs': runs, 'profile': profile}, allow_nan=False).replace('&', '\\u0026').replace('<', '\\u003c').replace('>', '\\u003e')
    template = (ROOT / 'app' / 'app-report-template.html').read_text(encoding='utf-8')
    report = template.replace('__APP_DATA__', payload)
    (ROOT / 'app-report.html').write_text(report, encoding='utf-8')
    import sys
    sys.path.insert(0, str(ROOT))
    from build_pages import build
    build()


if __name__ == '__main__':
    main()
