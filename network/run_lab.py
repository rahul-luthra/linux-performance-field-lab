"""Operator-side controller for bounded two-VM network experiments."""
import argparse
from pathlib import Path
import shlex
import subprocess
import time

CASES=[('01-baseline','normal',0),('02-delay-a','delay',0),('03-delay-b','delay',0),('04-delay-recovery','normal',0),
       ('05-loss-a','loss',0),('06-loss-b','loss',0),('07-loss-recovery','normal',0),('08-bandwidth','bandwidth',0),
       ('09-slow-handler','normal',100),('10-final-recovery','normal',0)]


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--client',required=True);p.add_argument('--server',required=True)
    p.add_argument('--key',required=True);p.add_argument('--known-hosts',required=True);p.add_argument('--corrected-tail',action='store_true');a=p.parse_args()
    options=['-i',Path(a.key).resolve().as_posix(),'-o','BatchMode=yes','-o','IdentitiesOnly=yes','-o','ConnectTimeout=8',
             '-o','StrictHostKeyChecking=yes','-o','UserKnownHostsFile="'+Path(a.known_hosts).resolve().as_posix()+'"']
    base='/home/rahul/network-field-lab'
    def ssh(ip,command,timeout=110):
        r=subprocess.run(['ssh',*options,'rahul@'+ip,command],capture_output=True,text=True,timeout=timeout)
        if r.returncode:raise RuntimeError(command+'\n'+r.stdout+r.stderr)
        return r.stdout
    def sudo(command):return 'sudo -n '+command
    rules=[f'rule family="ipv4" source address="{a.client}/32" port port="{port}" protocol="tcp" accept'for port in [8090,5201]]
    network=False
    try:
        ssh(a.server,sudo('systemctl reset-failed networklab-http networklab-iperf networklab-rollback.service || true'))
        for rule in rules:
            assert 'yes' not in ssh(a.server,sudo('firewall-cmd --zone=public --query-rich-rule='+shlex.quote(rule))+' || true').lower(),'Existing firewall rule: inspect ownership'
            ssh(a.server,sudo('firewall-cmd --zone=public --add-rich-rule='+shlex.quote(rule)+' --timeout=900'))
        common=' --property=User=rahul --property=MemoryMax=192M --property=TasksMax=64 --property=RuntimeMaxSec=900s --property=NoNewPrivileges=yes --property=ProtectSystem=strict --property=PrivateTmp=yes '
        ssh(a.server,sudo('systemd-run --unit=networklab-http'+common+' /usr/bin/python3 '+base+'/network/serve.py --bind '+a.server))
        ssh(a.server,sudo('systemd-run --unit=networklab-iperf'+common+' /usr/bin/iperf3 -s -B '+a.server+' -p 5201'))
        ssh(a.server,sudo('python3 '+base+'/network/impair.py setup --client '+a.client));network=True
        cases=[('11-slow-handler-corrected','normal',100),('12-final-recovery-corrected','normal',0)]if a.corrected_tail else CASES
        for name,mode,pause in cases:
            print('CASE '+name,flush=True)
            out=base+'/results/network/'+name
            ssh(a.server,sudo('python3 '+base+'/network/impair.py set --client '+a.client+' --mode '+mode))
            for ip,role,peer in [(a.client,'client',a.server),(a.server,'server',a.client)]:
                ssh(ip,'test ! -e '+out+' && mkdir -p '+out+'/'+role)
                ssh(ip,'python3 '+base+'/network/observe.py --peer '+peer+' --out '+out+'/'+role+' > '+out+'/'+role+'/observer.log 2>&1 < /dev/null &')
            ssh(a.server,'tc -s qdisc show dev enp0s3 > '+out+'/qdisc-before.txt')
            bpf=f'host {a.client} and tcp and (port 8090 or port 5201)'
            capunit='networkcap-'+name
            ssh(a.server,sudo('systemd-run --unit='+capunit+' --property=RuntimeMaxSec=48s /usr/sbin/tcpdump -nn -tt -l -i enp0s3 -s 64 -c 400 '+shlex.quote(bpf)))
            ssh(a.client,'ping -n -c 4 -W 1 '+a.server+' > '+out+'/ping.txt')
            print(ssh(a.client,'python3 '+base+'/network/client.py --server '+a.server+' --pause-ms '+str(pause)+' --out '+out+'/requests.json'),flush=True)
            # A separate eight-second reverse TCP test, capped at 100 Mbit/s offered traffic.
            ssh(a.client,'timeout 20 iperf3 -c '+a.server+' -p 5201 -R -t 8 -b 100M -J --get-server-output > '+out+'/iperf.json || test -s '+out+'/iperf.json')
            for ip,role in [(a.client,'client'),(a.server,'server')]:ssh(ip,'touch '+out+'/'+role+'/observer-stop')
            ssh(a.server,sudo('systemctl stop '+capunit+' || true'))
            ssh(a.server,sudo('journalctl -u '+capunit+' --no-pager -o cat')+' > '+out+'/packet-headers.txt')
            ssh(a.server,'tc -s qdisc show dev enp0s3 > '+out+'/qdisc.txt; tc -s filter show dev enp0s3 parent 1: > '+out+'/filter.txt')
            time.sleep(2)
    finally:
        if network:print(ssh(a.server,sudo('python3 '+base+'/network/impair.py restore --client '+a.client)),flush=True)
        ssh(a.server,sudo('systemctl stop networklab-http networklab-iperf || true'))
        ssh(a.server,sudo('systemctl reset-failed networklab-http networklab-iperf || true'))
        for rule in rules:ssh(a.server,sudo('firewall-cmd --zone=public --remove-rich-rule='+shlex.quote(rule)))
        print('CLEANUP complete',flush=True)


if __name__=='__main__':main()
