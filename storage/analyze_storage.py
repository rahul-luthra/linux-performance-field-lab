"""Analyze application sync-write latency, NFS RPC counters and both hosts without conflating layers."""
from datetime import datetime,timedelta
import argparse
import json
import math
from pathlib import Path
import statistics
from telemetry import rpc_delta

ROOT=Path(__file__).resolve().parent.parent
ORDER=['local-baseline','nfs-baseline','nfs-delay-a','nfs-delay-b','nfs-recovery','nfs-server-io','nfs-io-limited','nfs-server-io-repeat','nfs-io-limited-repeat','nfs-final-recovery']
def avg(values):return round(statistics.mean(values),3)if values else None
def percentile(values,p):
    values=sorted(values);return round(values[math.ceil(len(values)*p)-1],3)if values else None
def device_summary(samples,name='sda'):
    rows=[(s['disk'][name],s['interval_s'])for s in samples if name in s['disk']]
    timed=[(r,dt)for r,dt in rows if r.get('rw_iops')is not None and r.get('rw_await_ms')is not None]
    completed=sum(row['rw_iops']*dt for row,dt in timed)
    return {'device':name,'samples':len(rows),'rw_await_ms_weighted':round(sum(r['rw_await_ms']*r['rw_iops']*dt for r,dt in timed)/completed,3)if completed else None,
            'queue_mean':avg([r['avg_queue']for r,_ in rows]),'busy_mean_pct':avg([r['busy_pct']for r,_ in rows]),
            'write_mib_s_mean':avg([r['write_mib_s']for r,_ in rows]),
            'flush_await_ms_mean':avg([r['flush_await_ms']for r,_ in rows if r.get('flush_await_ms')is not None])}


def summarize(capture,client_host,server_host,noise=None,server_verification=None):
    rows=[r for r in capture['requests']if 2<=r['scheduled_s']<28]
    good=[r for r in rows if r.get('correct_response')and r['status']==200]
    started=datetime.fromisoformat(capture['started_utc']);finished=datetime.fromisoformat(capture['finished_utc'])
    selected=[]
    for host in (client_host,server_host):
        selected.append([s for s in host if started+timedelta(seconds=2)<=datetime.fromisoformat(s['time'])<finished-timedelta(seconds=2)])
    operations=rpc_delta(capture['nfs_before'],capture['nfs_after'])if capture['storage']=='nfs'else{}
    verification=capture.get('verification',{})
    expected=verification.get('expected_crc32')
    server_matches=(server_verification.get('latest')or{}).get('crc32')==expected if server_verification and expected is not None else None
    return {'name':capture['name'],'storage':capture['storage'],'stable_arrivals':len(rows),'successes':len(good),'errors':len(rows)-len(good),
            'all_arrivals':len(capture['requests']),'all_successes':sum(bool(r.get('correct_response'))and r['status']==200 for r in capture['requests']),
            'p50_ms':percentile([r['latency_ms']for r in good],.5),'p95_ms':percentile([r['latency_ms']for r in good],.95),'p99_ms':percentile([r['latency_ms']for r in good],.99),
            'force_p95_ms':percentile([r['force_ms']for r in good],.95),'write_p95_ms':percentile([r['write_ms']for r in good],.95),
            'handler_cpu_mean_ms':avg([r['handler_cpu_ms']for r in good]),'client_lag_p95_ms':percentile([r.get('scheduler_lag_ms',0)for r in rows],.95),
            'client_cpu_mean_pct':avg([s['cpu_busy_pct']for s in selected[0]if s['cpu_busy_pct']is not None]),
            'server_cpu_mean_pct':avg([s['cpu_busy_pct']for s in selected[1]if s['cpu_busy_pct']is not None]),
            'server_disk':device_summary(selected[1]),'client_disk':device_summary(selected[0]),'rpc':operations,
            'client_readback_matches':verification.get('matches'),'server_readback_matches':server_matches,
            'noise_write_ops_s':round(sum(noise['worker_writes'])/noise['seconds'],3)if noise and noise.get('worker_writes')else None,
            'noise_io_max':noise.get('io_max')if noise else None,
            'host_alignment_note':'Host samples selected by UTC window; clocks/snapshots are not atomically aligned. RPC deltas cover the full 120-arrival measurement, unlike the trimmed HTTP percentiles.'}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--evidence',default='results/storage');args=p.parse_args();root=(ROOT/args.evidence).resolve();cases=[]
    for name in ORDER:
        directory=root/'client'/name
        if not(directory/'capture.json').exists():continue
        capture=json.loads((directory/'capture.json').read_text());server=root/'server'/name
        def read(path,default):return json.loads(path.read_text())if path.exists()else default
        client_host=read(directory/'host.json',[]);server_host=read(server/'host.json',[]);noise=read(server/'noise.json',None);verified=read(server/'server-verification.json',None)
        summary=summarize(capture,client_host,server_host,noise,verified)
        (directory/'summary.json').write_text(json.dumps(summary,indent=2))
        cases.append({'name':name,'capture':capture,'client_host':client_host,'server_host':server_host,'summary':summary})
    (root/'summary.json').write_text(json.dumps([c['summary']for c in cases],indent=2))
    print(json.dumps([c['summary']for c in cases],indent=2))
    template=ROOT/'storage/report-template.html'
    if template.exists():
        data=json.dumps({'cases':cases},allow_nan=False).replace('&','\\u0026').replace('<','\\u003c').replace('>','\\u003e')
        (ROOT/'storage-report.html').write_text(template.read_text(encoding='utf-8').replace('__STORAGE_DATA__',data),encoding='utf-8')

if __name__=='__main__':main()
