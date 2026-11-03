"""Summarize recorded evidence; nearest-second tool comparisons are approximate."""
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import statistics


def mean(values):
    return round(statistics.mean(values), 3) if values else None


def analyze(root):
    data = json.loads((root / 'cpu-lab.json').read_text())
    stats = {}
    for phase in ('baseline', 'workload', 'transition', 'recovery'):
        rows = [s for s in data['samples'] if s['phase'] == phase]
        stats[phase] = {'intervals': len(rows)}
        for name in ('cpu_busy_pct', 'load1', 'procs_running', 'mem_available_pct', 'cpu_iowait_pct', 'cpu_steal_pct', 'swap_used_mib'):
            values = [s[name] for s in rows if s[name] is not None]
            stats[phase][name] = {'mean': mean(values), 'min': min(values) if values else None, 'max': max(values) if values else None}
    tool_rows, core_rows = [], []
    for line in (root / 'mpstat.txt').read_text().splitlines():
        p = line.split()
        if len(p) == 12 and re.fullmatch(r'\d\d:\d\d:\d\d', p[0]) and p[1] == 'all':
            values = list(map(float, p[2:]))
            tool_rows.append((p[0], round(100 - values[3] - values[6] - values[9], 2)))
        elif len(p) == 12 and re.fullmatch(r'\d\d:\d\d:\d\d', p[0]) and p[1].isdigit():
            values = list(map(float, p[2:]))
            core_rows.append((p[0], p[1], round(100 - values[3] - values[6] - values[9], 2)))
    pairs = []
    for s in data['samples']:
        stamp = datetime.fromisoformat(s['time'])
        # Tool timestamps have one-second precision. Treat each as an interval endpoint.
        candidates = [(abs((stamp - datetime.combine(stamp.date(), datetime.strptime(t, '%H:%M:%S').time(), timezone.utc)).total_seconds()), t, v) for t, v in tool_rows]
        if candidates:
            delta, stamp_tool, value = min(candidates)
            if delta <= .75:
                pairs.append({'sample_utc': s['time'], 'phase': s['phase'], 'mpstat_time_utc': stamp_tool,
                              'endpoint_skew_s': round(delta, 4), 'collector_busy_pct': s['cpu_busy_pct'],
                              'mpstat_busy_pct': value, 'absolute_difference_pp': round(abs(value - s['cpu_busy_pct']), 3)})
    # Exclude startup/shutdown boundary effects by reporting steady phases separately.
    vmstat = []
    for line in (root / 'vmstat.txt').read_text().splitlines():
        p = line.split()
        if len(p) >= 19 and p[0].isdigit():
            vmstat.append({'time': p[-2] + 'T' + p[-1] + '+00:00', 'runnable': int(p[0]), 'blocked': int(p[1]), 'swap_in_kib_s': int(p[6]), 'swap_out_kib_s': int(p[7])})
    # First vmstat row is since boot; do not treat it as an interval.
    vmstat = vmstat[1:]
    observer = {}
    for phase in ('baseline', 'workload', 'recovery'):
        window = [s for s in data['samples'] if s['phase'] == phase]
        # Trim two intervals from either end to avoid observer offset and workload edges.
        stable = window[2:-2]
        valid = {s['time'] for s in stable}
        paired = [p for p in pairs if p['sample_utc'] in valid]
        if stable:
            start, end = stable[0]['time'], stable[-1]['time']
            rows = [r for r in vmstat if start <= r['time'] <= end]
        else:
            rows = []
        observer[phase] = {'matched_mpstat_intervals': len(paired),
                           'collector_cpu_mean_pct': mean([p['collector_busy_pct'] for p in paired]),
                           'mpstat_cpu_mean_pct': mean([p['mpstat_busy_pct'] for p in paired]),
                           'mean_absolute_difference_pp': mean([p['absolute_difference_pp'] for p in paired]),
                           'vmstat_rows': len(rows), 'vmstat_runnable_mean': mean([r['runnable'] for r in rows]),
                           'vmstat_runnable_max': max([r['runnable'] for r in rows], default=None),
                           'vmstat_swap_in_max_kib_s': max([r['swap_in_kib_s'] for r in rows], default=None),
                           'vmstat_swap_out_max_kib_s': max([r['swap_out_kib_s'] for r in rows], default=None)}
        tool_times = {p['mpstat_time_utc'] for p in paired}
        observer[phase]['per_core_busy_mean_pct'] = {cpu: mean([value for stamp, core, value in core_rows if core == cpu and stamp in tool_times]) for cpu in sorted({r[1] for r in core_rows})}
        pidstat = root / 'pidstat.txt'
        if pidstat.exists():
            processes = {}
            for line in pidstat.read_text().splitlines():
                p = line.split()
                if len(p) == 10 and p[0] in tool_times and p[2].isdigit() and p[9] == 'python3':
                    processes.setdefault(p[2], []).append(float(p[7]))
            observer[phase]['python_process_cpu_pct'] = {pid: {'intervals': len(v), 'mean': mean(v)} for pid, v in processes.items()}
    result = {'phase_summary': stats, 'independent_observers': observer,
              'comparison_note': 'mpstat busy = 100 - idle - iowait - steal; nearest endpoints within 0.75s. Stable windows trim two samples at each edge. Tool sampling is not atomic or perfectly aligned.',
              'mpstat_pairs': pairs}
    (root / 'summary.json').write_text(json.dumps(result, indent=2))
    print(json.dumps({'phase_summary': stats, 'independent_observers': observer}, indent=2))


if __name__ == '__main__':
    root = Path(__file__).parent / 'results'
    analyze(root)
    if (root / 'repeat' / 'cpu-lab.json').exists():
        analyze(root / 'repeat')
