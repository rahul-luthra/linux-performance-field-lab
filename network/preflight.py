"""Record lab prerequisites and refresh the existing NFS share after address changes."""
import argparse
import ipaddress
import json
import os
from pathlib import Path
import shutil
import subprocess


def run(*args):return subprocess.check_output(list(args),text=True,timeout=90).strip()


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--role',choices=['client','server'],required=True)
    p.add_argument('--client',required=True);p.add_argument('--server',required=True)
    p.add_argument('--previous-client',required=True);p.add_argument('--previous-server',required=True);a=p.parse_args()
    for address in (a.client,a.server,a.previous_client,a.previous_server):ipaddress.IPv4Address(address)
    root=Path(__file__).resolve().parent.parent
    assert shutil.disk_usage(root).free>512*1024*1024,'Need at least 512 MiB free'
    if a.role=='server':
        export=Path('/etc/exports.d/perf-lab.exports');old=export.read_text()
        expected=f'/srv/nfs/perf-lab {a.previous_client}(rw,sync,root_squash,no_subtree_check,sec=sys)\n'
        updated=f'/srv/nfs/perf-lab {a.client}(rw,sync,root_squash,no_subtree_check,sec=sys)\n'
        assert old in (expected,updated),'Unexpected export configuration'
        if old!=updated:
            Path('/etc/exports.d/perf-lab.exports.before-network').write_text(old)
            export.write_text(updated)
        oldrule=f'rule family="ipv4" source address="{a.previous_client}/32" port port="2049" protocol="tcp" accept'
        newrule=f'rule family="ipv4" source address="{a.client}/32" port port="2049" protocol="tcp" accept'
        for scope in ([],['--permanent']):
            subprocess.run(['firewall-cmd','--zone=public',*scope,'--remove-rich-rule='+oldrule],capture_output=True)
            run('firewall-cmd','--zone=public',*scope,'--add-rich-rule='+newrule)
        run('exportfs','-ra')
    else:
        fstab=Path('/etc/fstab');old=fstab.read_text()
        new=old.replace(a.previous_server+':/srv/nfs/perf-lab',a.server+':/srv/nfs/perf-lab')
        if old!=new:
            Path('/etc/fstab.before-network-lab').write_text(old);fstab.write_text(new)
        run('systemctl','daemon-reload')
        mounted=subprocess.run(['findmnt','-rn','--mountpoint','/mnt/perf-lab-nfs','-o','SOURCE'],capture_output=True,text=True)
        if mounted.returncode==0 and a.previous_server!=a.server and mounted.stdout.strip().startswith(a.previous_server+':'):
            run('umount','/mnt/perf-lab-nfs')
            mounted=subprocess.run(['findmnt','-rn','--mountpoint','/mnt/perf-lab-nfs'],capture_output=True)
        if mounted.returncode!=0:run('mount','/mnt/perf-lab-nfs')
    commands={'disk':['df','-h','/'],'memory':['free','-m'],'addresses':['ip','-4','-br','address'],
              'route':['ip','route','get',a.server if a.role=='client'else a.client],
              'qdisc':['tc','-s','qdisc','show','dev','enp0s3'],'offloads':['ethtool','-k','enp0s3'],
              'os':['cat','/etc/oracle-release'],'kernel':['uname','-r'],'selinux':['getenforce'],
              'iperf_version':['iperf3','--version'],'tcpdump_version':['tcpdump','--version']}
    result={'role':a.role,'free_bytes':shutil.disk_usage(root).free}
    for name,cmd in commands.items():
        result[name]=run(*cmd)if shutil.which(cmd[0])else None
    result['nfs']=run('findmnt','-rn','--mountpoint','/mnt/perf-lab-nfs')if a.role=='client'else run('exportfs','-v')
    directory=root/'results/network';directory.mkdir(parents=True,exist_ok=True)
    os.chown(directory.parent,1000,1000);os.chown(directory,1000,1000)
    (directory/('preflight-'+a.role+'.json')).write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
