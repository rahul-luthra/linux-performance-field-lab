"""Export the lab reports with the portfolio navigation and case summaries."""
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parent
GITHUB = 'https://github.com/rahul-luthra/linux-performance-field-lab'
REPORTS = {
    'patching.html': 'patching-report.html',
    'incident.html': 'incident-report.html',
    'quotelab.html': 'app-report.html',
    'memory.html': 'memory-report.html',
    'storage.html': 'storage-report.html',
    'network.html': 'network-report.html',
    'reliability.html': 'reliability-report.html',
    'showcase.html': 'showcase.html',
    'cpu-lab.html': 'results/cpu-lab.html',
    'cpu-lab-repeat.html': 'results/repeat/cpu-lab.html',
    'smoke-report.html': 'results/smoke-report.html',
}
SUMMARIES = {
    'quotelab.html': (
        'QuoteLab returned successful responses at four requests per second, but response times rose during background CPU work.',
        'I compared HTTP latency, handler wall time and thread CPU time across three runs, alongside Linux CPU and process counters.',
        'In the first run, p95 rose from 92 to 411 ms. Host CPU reached 100% and handler wall time increased much more than thread CPU time.',
        'After the workers stopped, p95 recovered to 102 ms. In a separate trial, limiting the workers to one CPU brought contention p95 to 177 ms.',
        'APP_CASE_STUDY.md',
        (('Linux scenarios', 'showcase.html'), ('Host CPU run 1', 'cpu-lab.html'), ('Host CPU repeat', 'cpu-lab-repeat.html')),
    ),
    'memory.html': (
        'Java can stop because its heap runs out or because Linux enforces the service’s memory limit.',
        'I reproduced both failures and compared JVM error messages, exit status and cgroup memory events. I also compared allocation and buffer reuse under HTTP load.',
        'Heap exhaustion produced a Java error without a cgroup kill. The Linux kills coincided with a one-count increase in the cgroup OOM-kill counter.',
        'I tested higher limits against the same retained workload and ran a buffer-reuse trial that reduced measured GC time.',
        'MEMORY_CASE_STUDY.md',
        (),
    ),
    'storage.html': (
        'Quote requests that write to NFS can stall at the client, on the network or on the storage server.',
        'I compared local writes and NFS, then introduced reply delay and disk load in separate cases while collecting request, RPC and device timings.',
        'In two delay trials, NFS write round-trip time rose from about 8 to 31 ms while server device wait stayed around 1.3–1.5 ms.',
        'I removed the network delay and verified that HTTP p95 recovered from 46–60 ms to 22 ms.',
        'STORAGE_CASE_STUDY.md',
        (),
    ),
    'network.html': (
        'A slow HTTP response can come from the network or from a wait inside the application.',
        'I compared client latency, server handler timing and TCP measurements across delay, loss, bandwidth and application-wait cases.',
        'With injected network delay, HTTP p95 reached 272 ms in one run while handler p95 stayed below 0.5 ms. A deliberate handler pause raised both timings.',
        'I corrected the test cleanup after finding a residual rate limit. After removing the faults, the final run returned to about 9 ms HTTP p95.',
        'NETWORK_CASE_STUDY.md',
        (),
    ),
    'reliability.html': (
        'The frontend stayed live when a slow or unavailable dependency prevented users from getting a timely quote.',
        'I probed liveness and the full quote path, then matched failed request IDs to systemd journal entries.',
        'All 36 liveness probes passed. During the dependency outage, all 24 quote requests returned HTTP 503.',
        'Restarting the dependency restored successful quotes. In the delay trial, shortening the socket timeout returned errors sooner and removing the delay restored successful quotes.',
        'RELIABILITY_CASE_STUDY.md',
        (),
    ),
}
SUPPORTING = {
    'patching.html': (('From Alert to Recovery', 'incident.html'),),
    'incident.html': (('Original QuoteLab CPU investigation', 'quotelab.html'),),
    'showcase.html': (('QuoteLab case study', 'quotelab.html'), ('CPU run 1', 'cpu-lab.html'),
                      ('CPU repeat', 'cpu-lab-repeat.html'), ('Collector check', 'smoke-report.html')),
    'cpu-lab.html': (('QuoteLab case study', 'quotelab.html'), ('Linux scenarios', 'showcase.html'), ('CPU repeat', 'cpu-lab-repeat.html')),
    'cpu-lab-repeat.html': (('QuoteLab case study', 'quotelab.html'), ('Linux scenarios', 'showcase.html'), ('CPU run 1', 'cpu-lab.html')),
    'smoke-report.html': (('Linux scenarios', 'showcase.html'), ('CPU run 1', 'cpu-lab.html')),
}

NAVIGATION = (
    '<a class="site-skip" href="#report-content">Skip to report</a>'
    '<nav class="site-nav" aria-label="Portfolio">'
    '<a class="site-name" href="about.html">Rahul Luthra</a>'
    '<div class="site-links"><a href="index.html">Home</a>'
    '<a href="index.html#case-studies">Case Studies</a>'
    f'<a href="{GITHUB}">GitHub</a></div></nav>'
)


def evidence_links(links):
    return '<p class="case-links">' + ' '.join(
        f'<a href="{escape(url)}">{escape(label)}</a>' for label, url in links
    ) + '</p>'


def report_intro(destination):
    if destination not in SUMMARIES:
        return '<div class="case-related">' + evidence_links(SUPPORTING[destination]) + '</div>'

    problem, investigation, finding, recovery, writeup, related = SUMMARIES[destination]
    steps = (
        ('What happened', problem),
        ('How I investigated', investigation),
        ('What I found', finding),
        ('What I changed', recovery),
    )
    overview = ''.join(f'<div><dt>{label}</dt><dd>{escape(detail)}</dd></div>' for label, detail in steps)
    links = (('Read the methodology', f'{GITHUB}/blob/main/{writeup}'), *related)
    return (
        '<section class="case-summary" aria-labelledby="case-summary-title">'
        '<h2 id="case-summary-title">Case summary</h2>'
        f'<dl>{overview}</dl>{evidence_links(links)}</section>'
    )


def build():
    docs = ROOT / 'docs'
    for destination, source in REPORTS.items():
        html = (ROOT / source).read_text(encoding='utf-8')
        if not all(marker in html for marker in ('</head>', '<main>', '</header>')):
            raise ValueError(f'Unexpected report structure: {source}')
        html = html.replace('</head>', '<link rel="stylesheet" href="site.css"></head>', 1)
        html = html.replace('<main>', f'{NAVIGATION}<main id="report-content">', 1)
        html = html.replace('</header>', '</header>' + report_intro(destination), 1)
        with (docs / destination).open('w', encoding='utf-8', newline='\r\n') as report:
            report.write(html)
    (docs / '.nojekyll').write_text('')


if __name__ == '__main__':
    build()
    print(f'Exported {len(REPORTS)} case study and supporting reports.')
