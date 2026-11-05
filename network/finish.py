"""Record cleanup after the test controller has restored queues and stopped services."""
import argparse
import json
from pathlib import Path
import subprocess


def run(*args):
    r=subprocess.run(list(args),capture_output=True,text=True,timeout=15)
    return {'status':r.returncode,'stdout':r.stdout.strip(),'stderr':r.stderr.strip()}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--role',choices=['client','server'],required=True);a=p.parse_args()
    root=Path(__file__).resolve().parent.parent
    result={'role':a.role,'disk':run('df','-h','/'),'qdisc':run('tc','-j','qdisc','show','dev','enp0s3'),
            'listeners':run('ss','-ltn','( sport = :8090 or sport = :5201 )'),
            'lab_processes':run('pgrep','-af',r'network/[s]erve.py|network/[o]bserve.py|[i]perf3 -s'),
            'selinux':run('getenforce'),'units':run('systemctl','is-active','networklab-http','networklab-iperf','networklab-rollback.timer'),
            'temporary_state_removed':not Path('/run/network-field-lab.json').exists()}
    if a.role=='server':result['firewall']=run('sudo','-n','firewall-cmd','--zone=public','--list-rich-rules')
    else:
        result['nfs_mount']=run('findmnt','-rn','--mountpoint','/mnt/perf-lab-nfs')
        check=Path('/mnt/perf-lab-nfs/network-lab-check.txt')
        check.write_text('network-lab-nfs-ok\n');result['nfs_user_access_ok']=check.read_text()=='network-lab-nfs-ok\n';check.unlink()
    assert result['temporary_state_removed']
    assert len(json.loads(result['qdisc']['stdout']))==1 and json.loads(result['qdisc']['stdout'])[0]['kind']=='fq_codel'
    assert result['lab_processes']['status']==1,'Unexpected leftover lab process'
    assert len(result['listeners']['stdout'].splitlines())<=1,'Unexpected test-port listener'
    (root/'results/network'/('cleanup-'+a.role+'.json')).write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
