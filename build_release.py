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
          'app/QuoteLab.java', 'app/quotelab.service', 'app/install.sh', 'app/run_app_lab.py', 'app/analyze_app.py',
          'app/test_analysis.py', 'app/README.md', 'app/app-report-template.html', 'VIEWING_REPORTS.md', 'app-latency-preview.png']
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


def package():
    files = [ROOT / name for name in PUBLIC]
    files += [directory / name for directory in (ROOT / 'results', ROOT / 'results/repeat') for name in EVIDENCE if (directory / name).exists()]
    app_evidence = ['app-capture.json', 'summary.json', 'functional-tests.json', 'vmstat.txt', 'mpstat.txt', 'pidstat-java.txt',
                    'perf-baseline.txt', 'perf-contention.txt', 'perf-recovery.txt']
    files += [ROOT / 'results' / run / name for run in ('app-run1', 'app-run2', 'app-mitigated') for name in app_evidence]
    files += [ROOT / 'results/java-profile-summary.json', ROOT / 'results/app-analysis-tests.txt']
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
        assert not any(n.endswith('.jfr') or n.endswith('java-profile-events.json') for n in names)
        assert archive.testzip() is None
    print(f'Packaged {len(files)} public files; SSH keys and connection files excluded.')


if __name__ == '__main__':
    prepare()
    package()
