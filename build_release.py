"""Build a shareable archive using explicit public-file allowlists; excludes SSH material."""
from pathlib import Path
import re
from zipfile import ZipFile, ZIP_DEFLATED
from monitor import build_report


ROOT = Path(__file__).parent
PUBLIC = ['.gitignore', 'README.md', 'CASE_STUDY.md', 'LIVE_RESULTS.md', 'RUNBOOK.md', 'VALIDATION.md',
          'monitor.py', 'test_monitor.py', 'lab_cpu.py', 'run_live_lab.py', 'analyze_results.py',
          'make_demo.py', 'build_release.py', 'report-template.html', 'showcase.html', 'demo-data.json', 'preview.png',
          'app-report.html', 'APP_CASE_STUDY.md', 'PUBLISHING.md', 'app-preview.png', 'docs/index.html', 'docs/.nojekyll',
          'docs/about.html', 'docs/quotelab.html', 'docs/site.css',
          'incident-report.html', 'docs/incident.html', 'incident/README.md', 'incident/report-template.html',
          'docs/incident-awx.png', 'docs/incident-grafana.png',
          'incident/build_report.py', 'incident/probe.py', 'incident/load.py', 'incident/run.py',
          'incident/monitoring.py', 'incident/awx_lab.py', 'incident/workflow.yml', 'incident/alert.yml',
          'incident/nagios.cfg', 'incident/operator-command.sh', 'incident/target-command.sh',
          'results/incident/capture.json', 'results/incident/summary.json',
          'patching-report.html', 'docs/patching.html', 'patching/README.md', 'patching/report-template.html',
          'docs/patching-normal-awx.png', 'docs/patching-failed-awx.png',
          'patching/build_report.py', 'patching/make_seed.py', 'patching/create_vms.ps1', 'patching/snapshot.ps1',
          'patching/control.py', 'patching/backend.py', 'patching/patch-demo.service', 'patching/pool.py',
          'patching/probe.py', 'patching/awx_rollout.py', 'patching/run.py', 'patching/rollout.yml', 'patching/audit.yml',
          'results/patching/normal.json', 'results/patching/failed.json', 'results/patching/summary.json',
          'app/QuoteLab.java', 'app/quotelab.service', 'app/install.sh', 'app/run_app_lab.py', 'app/analyze_app.py',
          'app/test_analysis.py', 'app/README.md', 'app/app-report-template.html', 'VIEWING_REPORTS.md', 'app-latency-preview.png',
          'build_pages.py', 'docs/showcase.html', 'docs/cpu-lab.html', 'docs/cpu-lab-repeat.html', 'docs/smoke-report.html',
          'memory-report.html', 'docs/memory.html', 'MEMORY_CASE_STUDY.md', 'memory-preview.png',
          'memory/MemoryLab.java', 'memory/supervise.py', 'memory/run_memory_lab.py', 'memory/run_pressure_lab.py',
          'memory/analyze_memory.py', 'memory/test_memory.py', 'memory/README.md', 'memory/report-template.html',
          'storage-report.html', 'docs/storage.html', 'storage-preview.png', 'STORAGE_CASE_STUDY.md',
          'storage/StorageLab.java', 'storage/setup_nfs.py', 'storage/telemetry.py', 'storage/noise.py',
          'storage/network.py', 'storage/run_case.py', 'storage/server_case.py', 'storage/run_all.py',
          'storage/export_evidence.py', 'storage/check_setup.py', 'storage/analyze_storage.py',
          'storage/test_storage.py', 'storage/report-template.html', 'storage/README.md',
          'NETWORK_CASE_STUDY.md', 'network-report.html', 'docs/network.html', 'network-preview.png',
          'network/serve.py', 'network/client.py', 'network/impair.py', 'network/preflight.py',
          'network/observe.py', 'network/run_lab.py', 'network/analyze_network.py', 'network/test_network.py',
          'network/export_evidence.py', 'network/finish.py', 'network/report-template.html', 'network/README.md',
          'RELIABILITY_CASE_STUDY.md', 'reliability-report.html', 'docs/reliability.html',
          'reliability/service.py', 'reliability/probe.py', 'reliability/run_lab.py',
          'reliability/build_report.py', 'reliability/report-template.html', 'reliability/README.md',
          'results/reliability/capture.json']
EVIDENCE = ['cpu-lab.json', 'cpu-lab.html', 'summary.json', 'unit-tests.txt', 'mpstat.txt', 'vmstat.txt',
            'pidstat.txt', 'smoke-capture.json', 'smoke-report.html']


def prepare():
    import json
    for directory in (ROOT / 'results', ROOT / 'results/repeat', ROOT / 'results/app-run1', ROOT / 'results/app-run2', ROOT / 'results/app-mitigated'):
        for name in ('mpstat.txt', 'pidstat.txt', 'pidstat-java.txt'):
            path = directory / name
            if path.exists():
                lines = path.read_text().splitlines(keepends=True)
                if lines and lines[0].startswith('Linux '):
                    lines[0] = re.sub(r'\([^)]*\)', '(lab-vm)', lines[0], count=1)
                    path.write_text(''.join(lines), encoding='utf-8')
        capture = directory / 'cpu-lab.json'
        if capture.exists():
            build_report(json.loads(capture.read_text()), directory / 'cpu-lab.html')
    from incident.build_report import build as build_incident
    build_incident()
    from patching.build_report import build as build_patching
    build_patching()
    from build_pages import build
    build()


def package():
    files = [ROOT / name for name in PUBLIC]
    files += [directory / name for directory in (ROOT / 'results', ROOT / 'results/repeat') for name in EVIDENCE if (directory / name).exists()]
    app_evidence = ['app-capture.json', 'summary.json', 'functional-tests.json', 'vmstat.txt', 'mpstat.txt', 'pidstat-java.txt',
                    'perf-baseline.txt', 'perf-contention.txt', 'perf-recovery.txt']
    files += [ROOT / 'results' / run / name for run in ('app-run1', 'app-run2', 'app-mitigated') for name in app_evidence]
    files += [ROOT / 'results/java-profile-summary.json', ROOT / 'results/app-analysis-tests.txt']
    memory_names = {'capture.json', 'config.json', 'http.json', 'summary.json', 'overview.json',
                    'application.log', 'gc.log', 'gc.log.0', 'gc.log.1', 'unit-command.txt', 'unit-result.txt'}
    files += [path for path in (ROOT / 'results/memory').rglob('*') if path.is_file() and path.name in memory_names]
    files += [ROOT / 'results/memory-tests.txt']
    storage_names = {'capture.json', 'host.json', 'unit-result.txt', 'iostat.txt', 'nfsiostat.txt',
                     'mountstats-before.txt', 'mountstats-after.txt', 'controller.json', 'noise.json',
                     'network.json', 'network-filter.txt', 'nfsd-before.txt', 'nfsd-after.txt',
                     'server-verification.json', 'setup.json', 'summary.json'}
    files += [path for path in (ROOT / 'results/storage').rglob('*') if path.is_file() and path.name in storage_names]
    files += [ROOT / 'results/storage-tests.txt']
    network_names = {'requests.json', 'iperf.json', 'ping.txt', 'packet-headers.txt', 'qdisc.txt',
                     'qdisc-before.txt', 'filter.txt', 'host.json', 'sockets.txt', 'observer.log',
                     'preflight-client.json', 'preflight-server.json', 'cleanup-client.json', 'cleanup-server.json', 'summary.json'}
    files += [path for path in (ROOT / 'results/network').rglob('*') if path.is_file() and path.name in network_names]
    files += [ROOT / 'results/network-tests.txt']
    missing = [p.name for p in files if not p.exists()]
    if missing:
        raise FileNotFoundError(missing)
    destination = ROOT.parent / 'linux-performance-field-lab.zip'
    with ZipFile(destination, 'w', ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, 'linux-performance-field-lab/' + path.relative_to(ROOT).as_posix())
    with ZipFile(destination) as archive:
        names = archive.namelist()
        assert all('/ssh/' not in n and 'known_hosts' not in n and 'id_rsa' not in n and 'session_key' not in n for n in names)
        assert not any(n.endswith(('.jfr', '.hprof')) or n.endswith('java-profile-events.json') for n in names)
        assert archive.testzip() is None
    print(f'Packaged {len(files)} public files; SSH keys and connection files excluded.')


if __name__ == '__main__':
    prepare()
    package()
