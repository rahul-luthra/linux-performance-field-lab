"""Run isolated memory fault/correction services. Requires sudo and an otherwise idle lab VM."""
import argparse
import json
import os
from pathlib import Path
import pwd
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--isolated-lab', action='store_true', required=True)
    parser.add_argument('--out', default='results/memory/faults')
    args = parser.parse_args()
    out = (ROOT / args.out).resolve()
    if out.exists(): parser.error('Output directory exists; preserve prior measurements')
    out.mkdir(parents=True)
    user = pwd.getpwuid(os.getuid()).pw_name
    cases = [('heap-32-a', 'heap', 32, 192, True), ('heap-32-b', 'heap', 32, 192, False),
             ('heap-96-corrected', 'heap', 96, 192, False),
             ('limit-96-a', 'direct', 32, 96, False), ('limit-96-b', 'direct', 32, 96, False),
             ('limit-192-corrected', 'direct', 32, 192, False)]
    results = []
    for index, (name, mode, heap, cap, dump) in enumerate(cases):
        values = {p[0].rstrip(':'): int(p[1]) for line in Path('/proc/meminfo').read_text().splitlines() if len(p := line.split()) > 1}
        if values['MemAvailable'] < 600 * 1024: raise RuntimeError('Less than 600 MiB available: abort before the next isolated test')
        directory = out / name
        directory.mkdir()
        config = {'name': name, 'mode': mode, 'heap_mib': heap, 'memory_max_mib': cap,
                  'heap_dump': dump, 'seconds': 20, 'out': str(directory)}
        config_path = directory / 'config.json'
        config_path.write_text(json.dumps(config, indent=2))
        unit = 'memlab-' + str(os.getpid()) + '-' + str(index)
        command = ['sudo', '-n', 'systemd-run', '--unit=' + unit, '--wait', '--quiet', '--service-type=exec',
                   '--property=User=' + user, '--property=MemoryMax=' + str(cap) + 'M', '--property=MemorySwapMax=0',
                   '--property=OOMPolicy=continue', '--property=RuntimeMaxSec=40',
                   '--property=TasksMax=48', '--property=NoNewPrivileges=yes', '--property=PrivateTmp=yes',
                   '--property=ProtectSystem=strict', '--property=ProtectHome=read-only', '--property=ReadWritePaths=' + str(directory),
                   sys.executable, str(HERE / 'supervise.py'), str(config_path)]
        print('Starting ' + name, flush=True)
        run = subprocess.run(command, capture_output=True, text=True, timeout=50)
        (directory / 'unit-command.txt').write_text(' '.join(command) + '\n' + run.stdout + run.stderr)
        state = subprocess.run(['systemctl', 'show', unit, '-p', 'Result', '-p', 'ExecMainStatus', '-p', 'ActiveState'], capture_output=True, text=True)
        (directory / 'unit-result.txt').write_text(state.stdout)
        if not (directory / 'capture.json').exists():
            raise RuntimeError('Supervisor produced no capture: ' + run.stdout + run.stderr)
        capture = json.loads((directory / 'capture.json').read_text())
        results.append({'name': name, 'java_returncode': capture['java_returncode'], 'events': capture['event_deltas'],
                        'allocation_complete': capture['allocation_complete'], 'host_available_after_mib': capture['host_available_after_mib']})
        print(json.dumps(results[-1]), flush=True)
        subprocess.run(['sudo', '-n', 'systemctl', 'reset-failed', unit], capture_output=True)
        time.sleep(1)
    (out / 'overview.json').write_text(json.dumps(results, indent=2))


if __name__ == '__main__': main()
