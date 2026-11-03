"""Root-only NFS-reply delay, constrained to one destination and TCP source port 2049."""
import argparse
import ipaddress
import json
import subprocess
from pathlib import Path

def run(*args):return subprocess.check_output(list(args),text=True).strip()
parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=['setup','delay','restore']);parser.add_argument('--client',required=True);parser.add_argument('--ms',type=int,choices=[0,20],default=0);args=parser.parse_args();ipaddress.ip_address(args.client)
dev='enp0s3';state=Path('/run/perf-lab-network.json')
if args.action=='setup':
    run('modprobe','sch_netem');run('modprobe','sch_prio')
    original=json.loads(run('tc','-j','qdisc','show','dev',dev));assert len(original)==1 and original[0]['kind']=='fq_codel','Unexpected qdisc; leave it unchanged'
    opts=original[0]['options']
    assert opts['limit']==10240 and opts['flows']==1024 and opts['memory_limit']==33554432 and opts['ecn'] and opts['drop_batch']==64 and 4998<=opts['target']<=5000 and 99998<=opts['interval']<=100000,'Non-default qdisc parameters; inspect rather than overwrite'
    assert not state.exists(),'Existing lab network state needs recovery'
    state.write_text(json.dumps(original))
    run('systemd-run','--unit=perflab-network-rollback','--on-active=12m','/usr/sbin/tc','qdisc','replace','dev',dev,'root','fq_codel','quantum',str(opts['quantum']))
    run('tc','qdisc','replace','dev',dev,'root','handle','1:','prio','bands','3','priomap',*(['0']*16))
    run('tc','qdisc','add','dev',dev,'parent','1:1','handle','10:','fq_codel')
    run('tc','qdisc','add','dev',dev,'parent','1:3','handle','30:','netem','delay','0ms','limit','1000')
    run('tc','filter','add','dev',dev,'protocol','ip','parent','1:','prio','1','u32','match','ip','protocol','6','0xff','match','ip','dst',args.client+'/32','match','ip','sport','2049','0xffff','flowid','1:3')
elif args.action=='delay':
    assert state.exists(),'Set up scoped classifier first'
    run('tc','qdisc','change','dev',dev,'parent','1:3','handle','30:','netem','delay',str(args.ms)+'ms','limit','1000')
else:
    assert state.exists(),'No saved lab qdisc state'
    original=json.loads(state.read_text())[0]['options']
    run('tc','qdisc','replace','dev',dev,'root','fq_codel','quantum',str(original['quantum']))
    subprocess.run(['systemctl','stop','perflab-network-rollback.timer'],capture_output=True)
    state.unlink()
print(run('tc','-s','qdisc','show','dev',dev))
