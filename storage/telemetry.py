"""Read-only host and NFS-client snapshots; per-operation RPC fields retain their units."""
import json
from pathlib import Path
import sys
import time
import shutil
import subprocess
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from monitor import snapshot,derive


def mountstats(text, mount='/mnt/perf-lab-nfs'):
    section=False
    operations={}
    for line in text.splitlines():
        if line.startswith('device '): section=(' mounted on '+mount+' ') in line
        elif section and ':' in line:
            name,fields=line.strip().split(':',1)
            values=fields.split()
            if name.isupper() and len(values)>=8 and all(v.isdigit() for v in values): operations[name]=list(map(int,values))
    return operations


def rpc_delta(before,after):
    result={}
    for operation,new in after.items():
        old=before.get(operation)
        if old is None or len(old)<8 or any(new[i]<old[i] for i in range(8)):continue
        d=[new[i]-old[i] for i in range(8)]
        result[operation]={'operations':d[0],'transmissions':d[1],'major_timeouts':d[2],
                           'bytes_sent':d[3],'bytes_received':d[4],
                           'queue_ms_mean':round(d[5]/d[0],3) if d[0] else None,
                           'rtt_ms_mean':round(d[6]/d[0],3) if d[0] else None,
                           'execute_ms_mean':round(d[7]/d[0],3) if d[0] else None,
                           'retransmissions':d[1]-d[0]if d[1]>=d[0]else None}
    return result


def collect(out,seconds=100):
    directory=Path(out);directory.mkdir(parents=True,exist_ok=True)
    old=snapshot();samples=[];observers=[];handles=[]
    commands=[('iostat',['-x','-y','-k','1',str(seconds)],'iostat.txt')]
    if Path('/mnt/perf-lab-nfs').is_mount():commands.append(('nfsiostat',['1',str(seconds),'/mnt/perf-lab-nfs'],'nfsiostat.txt'))
    import os
    for tool,arguments,name in commands:
        if shutil.which(tool):
            handle=(directory/name).open('w');handles.append(handle)
            observers.append(subprocess.Popen([tool]+arguments,stdout=handle,stderr=subprocess.STDOUT,env=dict(os.environ,LC_ALL='C',TZ='UTC')))
    start=time.monotonic()
    try:
        while time.monotonic()-start<seconds and not(directory/'stop-telemetry').exists():
            time.sleep(1);new=snapshot();item=derive(old,new)
            for name,values in new['disk'].items():
                previous=old['disk'].get(name)
                if previous and len(values)>=17 and len(previous)>=17 and name in item['disk']:
                    count,ms=values[15]-previous[15],values[16]-previous[16]
                    item['disk'][name]['flush_iops']=round(count/(new['mono']-old['mono']),3) if count>=0 else None
                    item['disk'][name]['flush_await_ms']=round(ms/count,3) if count>0 and ms>=0 else None
            item['monotonic']=new['mono'];samples.append(item);old=new
    finally:
        for process in observers:
            if process.poll()is None:process.terminate()
            process.wait(timeout=5)
        for handle in handles:handle.close()
        (directory/'host.json').write_text(json.dumps(samples,indent=2))


if __name__=='__main__':collect(sys.argv[1],int(sys.argv[2]) if len(sys.argv)>2 else 100)
