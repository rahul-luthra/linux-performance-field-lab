"""Derive network-lab statistics without treating unavailable evidence as zero."""
import json
import math
import re
from datetime import datetime,timedelta
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent


def socket_rtts(text,port=5201):
    result=[];selected=False
    for line in text.splitlines():
        if line and not line[0].isspace():selected=bool(re.search(r':'+str(port)+r'\b',line))
        elif selected:
            match=re.search(r'\brtt:([\d.]+)/',line)
            if match:result.append(float(match.group(1)))
    return result


def ping_mean(text):
    match=re.search(r'(?:rtt|round-trip).*?=\s*[\d.]+/([\d.]+)/',text)
    return float(match.group(1))if match else None


def netem_drops(text):
    match=re.search(r'qdisc netem 30:.*?\(dropped (\d+),',text,re.S)
    return int(match.group(1))if match else None


def percentile(values,p):
    values=sorted(v for v in values if v is not None and math.isfinite(v))
    return values[max(0,math.ceil(len(values)*p)-1)]if values else None


def summarize(capture,iperf=None):
    rows=[r for r in capture['requests']if 2<=r['scheduled_s']<18]
    good=[r for r in rows if r.get('correct')and r.get('status')==200]
    bulk=[r for r in capture['bulk']if r.get('correct')and r.get('status')==200]
    result={'all_arrivals':len(capture['requests']),
            'all_correct':sum(bool(r.get('correct'))and r.get('status')==200 for r in capture['requests']),
            'stable_arrivals':len(rows),'stable_errors':len(rows)-len(good),
            'http_p50_ms':percentile([r['latency_ms']for r in good],.5),
            'http_p95_ms':percentile([r['latency_ms']for r in good],.95),
            'connect_p95_ms':percentile([r.get('connect_ms')for r in good],.95),
            'handler_p95_ms':percentile([r.get('handler_ms')for r in good],.95),
            'handler_cpu_p95_ms':percentile([r.get('handler_cpu_ms')for r in good],.95),
            'scheduling_lag_p95_ms':percentile([r.get('scheduler_lag_ms')for r in rows],.95),
            'bulk_correct':len(bulk),'bulk_arrivals':len(capture['bulk']),
            'bulk_median_ms':percentile([r['latency_ms']for r in bulk],.5),
            'iperf_received_mbps':None,'iperf_sender_retransmits':None,'iperf_error':None}
    if iperf:
        result['iperf_error']=iperf.get('error')
        end=iperf.get('end',{})
        bits=end.get('sum_received',{}).get('bits_per_second')
        result['iperf_received_mbps']=bits/1e6 if bits is not None else None
        result['iperf_sender_retransmits']=end.get('sum_sent',{}).get('retransmits')
    return result


if __name__=='__main__':
    source=ROOT/'results/network';results=[];cases=[];previous_drops=0
    for path in sorted(source.glob('*/requests.json')):
        capture=json.loads(path.read_text());iperf=path.parent/'iperf.json'
        summary=summarize(capture,json.loads(iperf.read_text())if iperf.exists()else None)
        directory=path.parent
        def read_json(path):return json.loads(path.read_text())if path.exists()else []
        hosts={role:read_json(directory/role/'host.json')for role in ['client','server']}
        start=datetime.fromisoformat(capture['started_utc'])
        for role,host in hosts.items():
            samples=[s['cpu_busy_pct']for s in host if start+timedelta(seconds=2)<=datetime.fromisoformat(s['time'])<start+timedelta(seconds=18)and s.get('cpu_busy_pct')is not None]
            summary[role+'_cpu_mean_pct']=sum(samples)/len(samples)if samples else None
        socket_file=directory/'server/sockets.txt';rtts=socket_rtts(socket_file.read_text())if socket_file.exists()else []
        summary['iperf_socket_rtt_median_ms']=percentile(rtts,.5)
        summary['iperf_socket_rtt_samples']=len(rtts)
        ping=directory/'ping.txt';summary['ping_mean_ms']=ping_mean(ping.read_text())if ping.exists()else None
        qdisc=directory/'qdisc.txt';summary['qdisc']=qdisc.read_text()if qdisc.exists()else None
        dropped=netem_drops(summary['qdisc']or'')
        before=directory/'qdisc-before.txt';start_drops=netem_drops(before.read_text())if before.exists()else previous_drops
        summary['netem_drop_delta']=dropped-start_drops if dropped is not None and start_drops is not None and dropped>=start_drops else None
        previous_drops=dropped
        summary['protocol_note']='Residual 5-Mbit/s rate discovered: excluded from single-factor attribution; corrected reruns follow.'if path.parent.name.startswith(('09-','10-'))and 'rate 'in(summary['qdisc']or'')else 'Fresh leaf queue; before/after evidence retained.'if before.exists()else 'Original sequential cohort; cumulative queue counters differenced.'
        results.append({'case':path.parent.name,**summary})
        cases.append({'name':path.parent.name,'summary':summary,'capture':capture,'hosts':hosts})
    if not results:raise SystemExit('No measured network evidence found; no report generated.')
    (source/'summary.json').write_text(json.dumps(results,indent=2))
    template=ROOT/'network/report-template.html'
    if template.exists():
        payload=json.dumps({'cases':cases},allow_nan=False).replace('&','\\u0026').replace('<','\\u003c').replace('>','\\u003e')
        (ROOT/'network-report.html').write_text(template.read_text(encoding='utf-8').replace('__NETWORK_DATA__',payload),encoding='utf-8')
    print(json.dumps(results,indent=2))
