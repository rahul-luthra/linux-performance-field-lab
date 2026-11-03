"""Record final lab setup checks and optionally remove only known bounded test data files."""
import argparse
import json
import os
from pathlib import Path
import subprocess

CASES=['local-baseline','nfs-baseline','nfs-delay-a','nfs-delay-b','nfs-recovery','nfs-server-io','nfs-io-limited','nfs-server-io-repeat','nfs-io-limited-repeat','nfs-final-recovery']
def run(*args):
    process=subprocess.run(list(args),capture_output=True,text=True)
    return {'status':process.returncode,'stdout':process.stdout.strip(),'stderr':process.stderr.strip()}
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--role',choices=['client','server'],required=True);p.add_argument('--cleanup-data',action='store_true');args=p.parse_args()
root=Path(__file__).resolve().parent.parent;out=root/'results/storage'/args.role;out.mkdir(parents=True,exist_ok=True)
result={'role':args.role,'uid':os.getuid(),'gid':os.getgid(),'selinux':run('getenforce')['stdout'],'test_data_removed_bytes':0}
if args.role=='client':
    share=Path('/mnt/perf-lab-nfs')
    result['mount']=run('findmnt','-T',str(share),'-o','SOURCE,FSTYPE,OPTIONS')
    check=share/'post-test-check.txt';check.write_text('nfs-user-access-ok\n');result['user_read_write_ok']=check.read_text()=='nfs-user-access-ok\n';check.unlink()
    denied=run('sudo','-n','touch',str(share/'root-squash-check'))
    result['direct_root_write_denied']=denied['status']!=0 and 'Permission denied' in denied['stderr']
    assert result['direct_root_write_denied']
    files=[root/'local-data/local-baseline.bin']
else:
    share=Path('/srv/nfs/perf-lab')
    result['export']=run('sudo','-n','exportfs','-v')
    result['firewall_rules']=run('sudo','-n','firewall-cmd','--zone=public','--list-rich-rules')
    result['nfs_versions']=run('sudo','-n','cat','/proc/fs/nfsd/versions')['stdout']
    result['service_active']=run('systemctl','is-active','nfs-server')['stdout'];result['service_enabled']=run('systemctl','is-enabled','nfs-server')['stdout']
    result['qdisc']=json.loads(run('tc','-j','qdisc','show','dev','enp0s3')['stdout'])
    result['network_state_removed']=not Path('/run/perf-lab-network.json').exists()
    result['rollback_timer_active']=run('systemctl','is-active','perflab-network-rollback.timer')['stdout']
    result['disk_scheduler']=Path('/sys/block/sda/queue/scheduler').read_text().strip()
    files=[share/(name+'.bin')for name in CASES if name!='local-baseline']+[share/'background.bin']
    assert result['network_state_removed']and len(result['qdisc'])==1 and result['qdisc'][0]['kind']=='fq_codel'
if args.cleanup_data:
    for file in files:
        if file.exists():
            expected=67108864 if file.name=='background.bin'else 16777216
            assert file.stat().st_size==expected,'Unexpected file size: leave it unchanged'
            result['test_data_removed_bytes']+=file.stat().st_size;file.unlink()
result['filesystem']=run('df','-h',str(share))
(out/'setup.json').write_text(json.dumps(result,indent=2))
print(json.dumps({'role':args.role,'checks_saved':True,'removed_bytes':result['test_data_removed_bytes']}))
