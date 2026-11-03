"""Keep a small supervisor alive in the lab cgroup to preserve post-Java memory.events."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.request import urlopen
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from monitor import snapshot, derive


def utc():
    return datetime.now(timezone.utc).isoformat()


def host_available():
    values = {p[0].rstrip(':'): int(p[1]) for line in Path('/proc/meminfo').read_text().splitlines() if len(p := line.split()) > 1}
    return round(values['MemAvailable'] / 1024, 2)


def main():
    config = json.loads(Path(sys.argv[1]).read_text())
    out = Path(config['out'])
    group = next(line.split('::', 1)[1] for line in Path('/proc/self/cgroup').read_text().splitlines() if line.startswith('0::'))
    cg = Path('/sys/fs/cgroup') / group.lstrip('/')
    def read(name):
        try: return (cg / name).read_text().strip()
        except OSError: return None
    def events():
        text = read('memory.events')
        return {p[0]: int(p[1]) for line in (text or '').splitlines() if len(p := line.split()) == 2}
    before = events()
    start = time.monotonic()
    data = {'name': config['name'], 'synthetic': False, 'started_utc': utc(), 'config': config,
            'cgroup': group, 'memory_max': read('memory.max'), 'memory_swap_max': read('memory.swap.max'), 'memory_oom_group': read('memory.oom.group'),
            'events_before': before, 'samples': []}
    data['started_monotonic'] = start
    log = (out / 'application.log').open('w')
    command = ['/usr/lib/jvm/jre-17-openjdk/bin/java', '--add-modules', 'jdk.httpserver',
               '-Xms' + str(config['heap_mib']) + 'm', '-Xmx' + str(config['heap_mib']) + 'm',
               '-XX:+UseSerialGC', '-XX:NewRatio=3', '-XX:MaxMetaspaceSize=48m', '-XX:ReservedCodeCacheSize=24m',
               '-XX:MaxDirectMemorySize=128m', '-XX:+ExitOnOutOfMemoryError',
               '-Xlog:gc*:file=' + str(out / 'gc.log') + ':uptime,level,tags:filecount=2,filesize=2M']
    if config.get('heap_dump'):
        command += ['-XX:+HeapDumpOnOutOfMemoryError', '-XX:HeapDumpPath=' + str(out / 'heap.hprof')]
    command += ['-cp', '/opt/linux-performance-field-lab/memory', 'MemoryLab', config['mode']]
    java = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
    # Increase only the child's OOM selection score; never protect it from the OOM killer.
    try: Path('/proc/' + str(java.pid) + '/oom_score_adj').write_text('500')
    except OSError: pass
    data['java_pid'] = java.pid
    data['command'] = command
    stopped_by_harness = False
    previous = snapshot()
    try:
        while java.poll() is None and time.monotonic() - start < config['seconds'] and not (out / 'stop').exists():
            current = snapshot()
            host = derive(previous, current)
            previous = current
            raw = read('memory.current')
            row = {'time': utc(), 'elapsed_s': round(time.monotonic() - start, 4),
                   'cgroup_current_bytes': int(raw) if raw is not None else None,
                   'host_available_mib': host_available(), 'events': events(), 'monotonic': current['mono'],
                   'host_cpu_pct': host['cpu_busy_pct']}
            try:
                with urlopen('http://127.0.0.1:8088/metrics', timeout=.3) as response:
                    row['jvm'] = json.loads(response.read())
            except Exception as exc: row['metrics_error'] = type(exc).__name__
            data['samples'].append(row)
            time.sleep(.25)
        if java.poll() is None:
            stopped_by_harness = True
            java.terminate()
        java.wait(timeout=10)
    finally:
        if java.poll() is None:
            java.kill()
            java.wait()
        log.close()
        data.update(finished_utc=utc(), java_returncode=java.returncode, stopped_by_harness=stopped_by_harness,
                    events_after=events(), cgroup_peak_bytes=read('memory.peak'),
                    host_available_after_mib=host_available())
        data['event_deltas'] = {key: value - before.get(key, 0) for key, value in data['events_after'].items()}
        data['allocation_complete'] = 'ALLOCATION_COMPLETE' in (out / 'application.log').read_text()
        (out / 'capture.json').write_text(json.dumps(data, indent=2))


if __name__ == '__main__': main()
