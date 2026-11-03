"""Local controller: uses the operator's SSH key; no inter-VM private key is installed."""
import argparse
import json
from pathlib import Path
import shlex
import subprocess
import sys

p=argparse.ArgumentParser(description=__doc__);p.add_argument('--client',required=True);p.add_argument('--server',required=True);p.add_argument('--key',required=True);p.add_argument('--known-hosts',required=True);p.add_argument('--repeat-io',action='store_true');p.add_argument('--remote-root',default='/home/rahul/nfs-storage-lab');args=p.parse_args()
options=['-i',Path(args.key).resolve().as_posix(),'-o','IdentitiesOnly=yes','-o','BatchMode=yes','-o','ConnectTimeout=8','-o','StrictHostKeyChecking=yes','-o','UserKnownHostsFile="'+Path(args.known_hosts).resolve().as_posix()+'"']
def ssh(host,command,**kwargs):
    result=subprocess.run(['ssh']+options+['rahul@'+host,command],text=True,capture_output=True,**kwargs)
    if result.returncode:raise RuntimeError(result.stderr+result.stdout)
    return result.stdout
import re
if not re.fullmatch(r'/home/rahul/[A-Za-z0-9_-]+',args.remote_root):p.error('remote-root must be a simple directory directly under /home/rahul')
base=args.remote_root
cases=[('local-baseline','local',0,'none'),('nfs-baseline','nfs',0,'none'),('nfs-delay-a','nfs',20,'none'),('nfs-delay-b','nfs',20,'none'),
       ('nfs-recovery','nfs',0,'none'),('nfs-server-io','nfs',0,'unlimited'),('nfs-io-limited','nfs',0,'limited')]
if args.repeat_io:cases=[('nfs-server-io-repeat','nfs',0,'unlimited'),('nfs-io-limited-repeat','nfs',0,'limited'),('nfs-final-recovery','nfs',0,'none')]
network_ready=False
try:
    print(ssh(args.server,f'sudo -n python3 {base}/storage/network.py setup --client {shlex.quote(args.client)}'),flush=True)
    network_ready=True
    for name,storage,delay,noise in cases:
        print('CASE '+name,flush=True)
        print(ssh(args.server,f'sudo -n python3 {base}/storage/network.py delay --client {shlex.quote(args.client)} --ms {delay}'),flush=True)
        process=subprocess.Popen(['ssh']+options+['rahul@'+args.client,f'cd {base} && python3 storage/run_case.py --case {name} --storage {storage}'],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
        prepared=False
        for line in process.stdout:
            print(line.rstrip(),flush=True)
            if line.startswith('READY '):
                print(ssh(args.server,f'cd {base} && python3 storage/server_case.py start --case {name} --noise {noise}'),flush=True)
                ssh(args.client,f'touch {base}/results/storage/client/{name}/go');prepared=True
        code=process.wait()
        if prepared:print(ssh(args.server,f'cd {base} && python3 storage/server_case.py finish --case {name}'),flush=True)
        if code:raise RuntimeError('Client case failed: '+name)
finally:
    try:print(ssh(args.server,f'sudo -n python3 {base}/storage/network.py restore --client {shlex.quote(args.client)}'),flush=True)
    except RuntimeError:
        if network_ready:raise
