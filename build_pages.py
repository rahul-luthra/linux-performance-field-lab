"""Export generated reports to GitHub Pages with shared relative navigation."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPORTS = [
    ('app-report.html', 'index.html', 'Java application'),
    ('memory-report.html', 'memory.html', 'Memory investigation'),
    ('storage-report.html', 'storage.html', 'Storage &amp; NFS'),
    ('network-report.html', 'network.html', 'Network investigation'),
    ('reliability-report.html', 'reliability.html', 'Service reliability'),
    ('showcase.html', 'showcase.html', 'Linux scenarios'),
    ('results/cpu-lab.html', 'cpu-lab.html', 'CPU run 1'),
    ('results/repeat/cpu-lab.html', 'cpu-lab-repeat.html', 'CPU run 2'),
    ('results/smoke-report.html', 'smoke-report.html', 'Collector check'),
]


def build():
    docs = ROOT / 'docs'
    docs.mkdir(exist_ok=True)
    for source, destination, _ in REPORTS:
        links = []
        for _, filename, label in REPORTS:
            active = ' aria-current="page"' if filename == destination else ''
            links.append(f'<a href="{filename}"{active}>{label}</a>')
        links.append('<a href="https://github.com/rahul-luthra/linux-performance-field-lab">Source &amp; methodology</a>')
        navigation = '<nav class="bar" aria-label="Report navigation">' + ''.join(links) + '</nav>'
        html = (ROOT / source).read_text(encoding='utf-8')
        assert '<main>' in html, source
        (docs / destination).write_text(html.replace('<main>', '<main>' + navigation, 1), encoding='utf-8')
    (docs / '.nojekyll').write_text('')


if __name__ == '__main__':
    build()
    print('Exported nine linked GitHub Pages reports.')
