"""Scoped HTTP/iperf response impairment; automatic rollback excludes SSH and NFS."""
import argparse
import ipaddress
import json
from pathlib import Path
import subprocess

STATE=Path('/run/network-field-lab.json')


def run(*args):return subprocess.check_output(list(args),text=True).strip()


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['setup','set','restore'])
    p.add_argument('--client',required=True);p.add_argument('--dev',default='enp0s3')
    p.add_argument('--mode',choices=['normal','delay','loss','bandwidth'],default='normal')
    args=p.parse_args();ipaddress.IPv4Address(args.client);dev=args.dev
    if args.action=='setup':
        original=json.loads(run('tc','-j','qdisc','show','dev',dev))
        assert len(original)==1 and original[0]['kind']=='fq_codel','Unexpected qdisc: inspect manually'
        o=original[0]['options']
        assert o['limit']==10240 and o['flows']==1024 and o['ecn'] and o['memory_limit']==33554432 and o['drop_batch']==64 and 4998<=o['target']<=5000 and 99998<=o['interval']<=100000,'Unrecognized policy'
        assert not STATE.exists(),'Existing experiment state needs recovery'
        run('modprobe','sch_netem');run('modprobe','sch_prio')
        STATE.write_text(json.dumps({'dev':dev,'qdisc':original}))
        run('systemd-run','--unit=networklab-rollback','--on-active=15m','/usr/sbin/tc','qdisc','replace','dev',dev,'root','fq_codel','quantum',str(o['quantum']))
        run('tc','qdisc','replace','dev',dev,'root','handle','1:','prio','bands','3','priomap',*(['0']*16))
        run('tc','qdisc','add','dev',dev,'parent','1:1','handle','10:','fq_codel')
        run('tc','qdisc','add','dev',dev,'parent','1:3','handle','30:','netem','limit','1000','delay','0ms')
        for priority,port in enumerate([8090,5201],1):
            run('tc','filter','add','dev',dev,'protocol','ip','parent','1:','prio',str(priority),'u32',
                'match','ip','protocol','6','0xff','match','ip','dst',args.client+'/32',
                'match','ip','sport',str(port),'0xffff','flowid','1:3')
    elif args.action=='set':
        assert STATE.exists(),'Run setup first'
        settings={'normal':['delay','0ms'],'delay':['delay','50ms'],'loss':['loss','random','1%'],
                  'bandwidth':['rate','5mbit']}[args.mode]
        # Delete/recreate: on this kernel a same-kind replace retains an omitted rate.
        run('tc','qdisc','del','dev',dev,'parent','1:3','handle','30:')
        run('tc','qdisc','add','dev',dev,'parent','1:3','handle','30:','netem','limit','1000',*settings)
    else:
        saved=json.loads(STATE.read_text());assert saved['dev']==dev
        run('tc','qdisc','replace','dev',dev,'root','fq_codel','quantum',str(saved['qdisc'][0]['options']['quantum']))
        subprocess.run(['systemctl','stop','networklab-rollback.timer'],capture_output=True)
        STATE.unlink()
    print(run('tc','-s','qdisc','show','dev',dev))


if __name__=='__main__':main()
