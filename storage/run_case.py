"""Client-side bounded synchronized-write HTTP test, controlled by an external ready/go gate."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
import argparse
import json
import os
from pathlib import Path
import pwd
import struct
import subprocess
import sys
import threading
import time
from urllib.request import urlopen
import zlib
from telemetry import mountstats

def get(path):
    with urlopen('http://127.0.0.1:8089'+path,timeout=3) as response:return response.status,response.headers,json.loads(response.read())
def utc():return datetime.now(timezone.utc).isoformat()

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--case',required=True);p.add_argument('--storage',choices=['local','nfs'],required=True);args=p.parse_args()
    root=Path(__file__).resolve().parent.parent;out=root/'results/storage/client'/args.case
    if out.exists():p.error('Preserve existing case; use a new name')
    out.mkdir(parents=True)
    data_dir=Path('/mnt/perf-lab-nfs') if args.storage=='nfs' else root/'local-data'
    data_dir.mkdir(exist_ok=True)
    data_file=data_dir/(args.case+'.bin');unit='storageapp-'+str(os.getpid())
    user=pwd.getpwuid(os.getuid()).pw_name
    command=['sudo','-n','systemd-run','--unit='+unit,'--wait','--quiet','--service-type=exec',
             '--property=User='+user,'--property=MemoryMax=192M','--property=TasksMax=48','--property=RuntimeMaxSec=100',
             '--property=TimeoutStopSec=5','--property=SuccessExitStatus=143','--property=NoNewPrivileges=yes',
             '--property=PrivateTmp=yes','--property=ProtectSystem=strict','--property=ProtectHome=read-only',
             '--property=ReadWritePaths='+str(data_dir),'/usr/lib/jvm/jre-17-openjdk/bin/java','--add-modules','jdk.httpserver',
             '-Xms32m','-Xmx32m','-XX:+UseSerialGC','-XX:MaxMetaspaceSize=48m','-XX:ReservedCodeCacheSize=24m',
             '-cp','/opt/linux-performance-field-lab/storage','StorageLab',str(data_file)]
    process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    requests=[];permits=threading.BoundedSemaphore(8);observer=None
    try:
        for _ in range(80):
            if process.poll() is not None:raise RuntimeError(process.stdout.read())
            try:
                if get('/health')[0]==200:break
            except Exception:pass
            time.sleep(.25)
        else:raise RuntimeError('Service not ready')
        for _ in range(32):
            began=time.monotonic();assert get('/save')[0]==200;time.sleep(max(0,.25-(time.monotonic()-began)))
        (out/'ready').touch();print('READY '+args.case,flush=True)
        for _ in range(200):
            if(out/'go').exists():break
            time.sleep(.1)
        else:raise RuntimeError('Controller did not release measurement gate')
        before_text=Path('/proc/self/mountstats').read_text();before=mountstats(before_text)
        started=utc();start=time.monotonic()
        observer=subprocess.Popen([sys.executable,str(root/'storage/telemetry.py'),str(out),'35'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        def request_one(index):
            scheduled=index/4;actual=time.monotonic();row={'index':index,'scheduled_s':scheduled,'scheduler_lag_ms':round(max(0,actual-start-scheduled)*1000,3)}
            try:
                status,headers,body=get('/save');row.update(status=status,**body)
                for key,header in [('write_ms','X-Write-Ms'),('force_ms','X-Force-Ms'),('handler_wall_ms','X-Handler-Wall-Ms'),('handler_cpu_ms','X-Handler-Cpu-Ms')]:row[key]=float(headers[header])
                expected=bytearray([0x5a])*65536;struct.pack_into('>q',expected,0,body['sequence'])
                row['correct_response']=body['saved_bytes']==65536 and body['crc32']==zlib.crc32(expected)
            except Exception as exc:row.update(status=0,error=type(exc).__name__+': '+str(exc),correct_response=False)
            finally:row['latency_ms']=round((time.monotonic()-actual)*1000,3);requests.append(row);permits.release()
        with ThreadPoolExecutor(max_workers=8) as executor:
            futures=[]
            for index in range(120):
                time.sleep(max(0,start+index/4-time.monotonic()))
                if permits.acquire(blocking=False):futures.append(executor.submit(request_one,index))
                else:requests.append({'index':index,'scheduled_s':index/4,'status':0,'correct_response':False,'error':'client cap'})
            for future in futures:future.result()
        time.sleep(max(0,start+30-time.monotonic()))
        finished=utc();after_text=Path('/proc/self/mountstats').read_text();after=mountstats(after_text)
        good=[r for r in requests if r.get('correct_response')]
        verification={}
        if good:
            last=max(good,key=lambda r:r['sequence'])
            with data_file.open('rb')as handle:handle.seek(last['slot']*65536);block=handle.read(65536)
            verification={'sequence':last['sequence'],'slot':last['slot'],'expected_crc32':last['crc32'],'read_crc32':zlib.crc32(block),'matches':zlib.crc32(block)==last['crc32']}
        (out/'mountstats-before.txt').write_text(before_text)
        (out/'mountstats-after.txt').write_text(after_text)
        (out/'capture.json').write_text(json.dumps({'name':args.case,'storage':args.storage,'synthetic':False,'started_utc':started,'finished_utc':finished,
            'load_start_monotonic':start,'metadata':{'rate_rps':4,'duration_s':30,'warmup_requests':32,'file_cap_bytes':16777216,'write_bytes':65536,
            'force_metadata':False,'http_timeout_s':3,'client_cap':8,'file':str(data_file),'unit':unit,
            'note':'Application on NFS client; generator shares that VM. force(false) acknowledges OS sync completion, not a power-loss guarantee.'},
            'requests':sorted(requests,key=lambda r:r['index']),'nfs_before':before,'nfs_after':after,'verification':verification},indent=2))
        print('COMPLETE '+args.case,flush=True)
    finally:
        (out/'stop-telemetry').touch()
        if observer is not None:observer.wait(timeout=5)
        subprocess.run(['sudo','-n','systemctl','stop',unit],capture_output=True)
        stdout=process.communicate(timeout=10)[0];(out/'unit-result.txt').write_text(stdout)
        subprocess.run(['sudo','-n','systemctl','reset-failed',unit],capture_output=True)
    assert len(requests)==120

if __name__=='__main__':main()
