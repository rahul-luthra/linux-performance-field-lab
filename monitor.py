#!/usr/bin/env python3
"""Read-only Linux sampler and portable offline report builder. Python 3.9+."""
import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import platform
import time


def numbers(text):
    return {line.split()[0].rstrip(':'): int(line.split()[1])
            for line in text.splitlines() if len(line.split()) >= 2}


def pressure(text):
    return {line.split()[0]: {k: float(v) for k, v in
            (pair.split('=') for pair in line.split()[1:])}
            for line in text.splitlines()}


def devices(text):
    return {p[2]: list(map(int, p[3:])) for line in text.splitlines()
            if len(p := line.split()) >= 14}


def networks(text):
    return {name.strip(): list(map(int, fields.split()))
            for line in text.splitlines() if ':' in line
            for name, fields in [line.split(':', 1)]}


def snapshot(root=Path('/proc')):
    warnings = []
    def read(name, optional=False):
        try:
            return (root / name).read_text()
        except OSError as exc:
            if not optional:
                raise RuntimeError(f'Cannot read {root / name}: {exc}') from exc
            warnings.append(f'{name}: unavailable ({exc.strerror})')
            return ''
    stat = read('stat').splitlines()
    cpu = list(map(int, stat[0].split()[1:]))[:8]
    mem = numbers(read('meminfo'))
    load = list(map(float, read('loadavg').split()[:3]))
    gauges = {p[0]: int(p[1]) for line in stat
              if (p := line.split())[0] in ('procs_running', 'procs_blocked')}
    return {'mono': time.monotonic(), 'time': datetime.now(timezone.utc).isoformat(),
            'cpu': cpu, 'cores': sum(line.startswith('cpu') and line[3:4].isdigit() for line in stat),
            'mem': mem, 'load': load, 'gauges': gauges,
            'psi': {r: pressure(read('pressure/' + r, True)) for r in ('cpu', 'memory', 'io')},
            'disk': devices(read('diskstats', True)),
            'net': networks(read('net/dev', True)),
            'warnings': warnings}


def deltas(before, after, indexes):
    if any(after[i] < before[i] for i in indexes):
        return None
    return [after[i] - before[i] for i in indexes]


def derive(a, b):
    dt = b['mono'] - a['mono']
    if dt <= 0:
        raise ValueError('Sample interval must be positive')
    warnings = list(b['warnings'])
    c = deltas(a['cpu'], b['cpu'], range(8)) if a['cores'] == b['cores'] else None
    total = sum(c) if c else 0
    pct = lambda n: round(100 * n / total, 2) if total else None
    if not total:
        warnings.append('CPU counters reset, no ticks, or CPU topology changed: interval unavailable')
    mem = b['mem']
    available = mem.get('MemAvailable')
    psi = {}
    for resource in ('cpu', 'memory', 'io'):
        psi[resource] = {}
        for scope, fields in b['psi'][resource].items():
            # System-wide CPU full has no defined meaning.
            if resource == 'cpu' and scope == 'full':
                continue
            old = a['psi'][resource].get(scope, {}).get('total')
            new = fields.get('total')
            value = None if old is None or new is None or new < old else 100 * (new - old) / (dt * 1e6)
            psi[resource][scope] = round(min(100, value), 2) if value is not None else None
    disk = {}
    for name, new in b['disk'].items():
        old = a['disk'].get(name)
        if old is None:
            continue
        diff = deltas(old, new, (0, 2, 3, 4, 6, 7, 9, 10))
        if diff is None:
            warnings.append(f'{name}: disk counter reset; interval omitted')
            continue
        reads, sectors_r, ms_r, writes, sectors_w, ms_w, busy, weighted = diff
        disk[name] = {'read_mib_s': round(sectors_r * 512 / 1048576 / dt, 3),
                      'write_mib_s': round(sectors_w * 512 / 1048576 / dt, 3),
                      'rw_iops': round((reads + writes) / dt, 2),
                      'rw_await_ms': round((ms_r + ms_w) / (reads + writes), 2) if reads + writes else None,
                      'busy_pct': round(min(100, busy / (dt * 10)), 2),
                      'avg_queue': round(weighted / (dt * 1000), 3)}
    net = {}
    for name, new in b['net'].items():
        old = a['net'].get(name)
        if old is None:
            continue
        diff = deltas(old, new, (0, 2, 3, 8, 10, 11))
        if diff is None:
            warnings.append(f'{name}: network counter reset; interval omitted')
            continue
        rx, re, rd, tx, te, td = diff
        net[name] = {'rx_mib_s': round(rx / 1048576 / dt, 3), 'tx_mib_s': round(tx / 1048576 / dt, 3),
                     'errors_s': round((re + te) / dt, 3), 'drops_s': round((rd + td) / dt, 3)}
    return {'time': b['time'], 'interval_s': round(dt, 4), 'cores': b['cores'],
            'cpu_busy_pct': pct(sum(c[:3]) + c[5] + c[6]) if c else None,
            'cpu_iowait_pct': pct(c[4]) if c else None,
            'cpu_steal_pct': pct(c[7]) if c else None,
            'load1': b['load'][0], **b['gauges'],
            'mem_available_pct': round(100 * available / mem['MemTotal'], 2) if available is not None else None,
            'cached_mib': round(mem.get('Cached', 0) / 1024, 2),
            'swap_used_mib': round((mem.get('SwapTotal', 0) - mem.get('SwapFree', 0)) / 1024, 2),
            'psi': psi, 'disk': disk, 'net': net, 'warnings': warnings}


def build_report(data, destination):
    # Escape HTML-sensitive characters so imported metadata cannot close the script element.
    payload = json.dumps(data, allow_nan=False).replace('&', '\\u0026').replace('<', '\\u003c').replace('>', '\\u003e')
    template = Path(__file__).with_name('report-template.html').read_text(encoding='utf-8')
    Path(destination).write_text(template.replace('__CAPTURE_DATA__', payload), encoding='utf-8')


def positive(value):
    n = float(value)
    if not math.isfinite(n) or n <= 0:
        raise argparse.ArgumentTypeError('must be finite and greater than zero')
    return n


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    c = sub.add_parser('capture', help='Sample a Linux host without root')
    c.add_argument('--samples', type=int, default=60)
    c.add_argument('--interval', type=positive, default=1)
    c.add_argument('--out', default='capture.json')
    r = sub.add_parser('report', help='Create a self-contained HTML report')
    r.add_argument('capture')
    r.add_argument('--out', default='report.html')
    args = parser.parse_args()
    if args.command == 'report':
        build_report(json.loads(Path(args.capture).read_text(encoding='utf-8')), args.out)
        print(f'Report written to {args.out}')
        return
    if platform.system() != 'Linux':
        parser.error('Live collection requires Linux; report generation works on any OS')
    if args.samples < 1:
        parser.error('--samples must be at least 1')
    data = {'schema_version': 1, 'title': 'Linux host capture', 'synthetic': False,
            'description': 'Read-only host counters. No application latency collected. Host name omitted.', 'samples': []}
    try:
        previous = snapshot()
        for _ in range(args.samples):
            time.sleep(args.interval)
            current = snapshot()
            data['samples'].append(derive(previous, current))
            previous = current
    except KeyboardInterrupt:
        print('Stopped; saving completed intervals.')
    except (RuntimeError, ValueError) as exc:
        parser.exit(1, str(exc) + '\n')
    Path(args.out).write_text(json.dumps(data, indent=2, allow_nan=False), encoding='utf-8')
    print(f'Saved {len(data["samples"])} intervals to {args.out}')


if __name__ == '__main__':
    main()
