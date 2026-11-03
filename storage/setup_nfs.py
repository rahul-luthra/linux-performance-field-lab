"""Root-only, scoped lab NFS setup; run separately on server and client."""
import argparse
from pathlib import Path
import subprocess
import os


def run(*args):
    return subprocess.run(list(args), check=True, text=True, capture_output=True).stdout.strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('role', choices=['server', 'client'])
    parser.add_argument('--server', required=True)
    parser.add_argument('--client', required=True)
    args = parser.parse_args()
    assert os.geteuid() == 0
    # IP-only arguments: do not accept arbitrary export-option text.
    import ipaddress
    ipaddress.ip_address(args.server)
    ipaddress.ip_address(args.client)
    if args.role == 'server':
        directory = Path('/srv/nfs/perf-lab')
        directory.mkdir(parents=True, exist_ok=True)
        os.chown(directory, 1000, 1000)
        directory.chmod(0o700)
        Path('/etc/nfs.conf.d').mkdir(exist_ok=True)
        Path('/etc/nfs.conf.d/perf-lab.conf').write_text('[nfsd]\nvers3=n\nvers4=y\nudp=n\ntcp=y\nthreads=8\n')
        Path('/etc/exports.d').mkdir(exist_ok=True)
        Path('/etc/exports.d/perf-lab.exports').write_text(f'{directory} {args.client}(rw,sync,root_squash,no_subtree_check,sec=sys)\n')
        rule = f'rule family="ipv4" source address="{args.client}/32" port port="2049" protocol="tcp" accept'
        run('firewall-cmd', '--zone=public', '--permanent', '--add-rich-rule=' + rule)
        run('firewall-cmd', '--zone=public', '--add-rich-rule=' + rule)
        run('systemctl', 'enable', '--now', 'nfs-server')
        run('exportfs', '-ra')
        print(run('exportfs', '-v'))
        print(run('cat', '/proc/fs/nfsd/versions'))
    else:
        directory = Path('/mnt/perf-lab-nfs')
        directory.mkdir(exist_ok=True)
        if not subprocess.run(['mountpoint', '-q', str(directory)]).returncode == 0:
            run('mount', '-t', 'nfs4', '-o', 'vers=4.2,proto=tcp,hard,nosuid,nodev,noexec', args.server + ':/srv/nfs/perf-lab', str(directory))
        line = f'{args.server}:/srv/nfs/perf-lab {directory} nfs4 rw,vers=4.2,proto=tcp,hard,nosuid,nodev,noexec,_netdev,nofail 0 0\n'
        fstab = Path('/etc/fstab')
        original = fstab.read_text()
        if '/mnt/perf-lab-nfs' not in original:
            backup = Path('/etc/fstab.before-perf-lab')
            if not backup.exists(): backup.write_text(original)
            fstab.write_text(original.rstrip() + '\n# Performance lab: source-restricted NFSv4 share\n' + line)
        run('systemctl', 'daemon-reload')
        print(run('findmnt', '-T', str(directory), '-o', 'SOURCE,FSTYPE,OPTIONS'))


if __name__ == '__main__': main()
