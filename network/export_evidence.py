"""Allowlisted text evidence only; redact addresses and exclude unrelated socket records."""
import argparse
from pathlib import Path
import re
from zipfile import ZipFile,ZIP_DEFLATED


def scoped_sockets(text):
    result=[];keep=False
    for line in text.splitlines(keepends=True):
        if re.match(r'^\d{4}-\d\d-',line):result.append(line);keep=False
        elif line.startswith('State '):result.append(line);keep=False
        elif line and not line[0].isspace():
            keep=bool(re.search(r':(?:8090|5201)\b',line))
            if keep:result.append(line)
        elif keep:result.append(line)
    return ''.join(result)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--role',choices=['client','server'],required=True)
    p.add_argument('--client',required=True);p.add_argument('--server',required=True);a=p.parse_args()
    root=Path(__file__).resolve().parent.parent;source=root/'results/network'
    names={'requests.json','iperf.json','ping.txt','packet-headers.txt','qdisc.txt','qdisc-before.txt','filter.txt','host.json','sockets.txt','observer.log',
           'preflight-client.json','preflight-server.json','cleanup-client.json','cleanup-server.json'}
    with ZipFile(root/'results'/('network-'+a.role+'.zip'),'w',ZIP_DEFLATED)as archive:
        for file in source.rglob('*'):
            if not file.is_file()or file.name not in names:continue
            text=file.read_text()
            if file.name=='sockets.txt':text=scoped_sockets(text)
            text=text.replace(a.client,'lab-client').replace(a.server,'lab-server')
            text=text.replace('Linux db ','Linux lab-client ').replace('Linux nfs-lab-server ','Linux lab-server ')
            archive.writestr('network/'+file.relative_to(source).as_posix(),text)
    print('Exported '+a.role+' allowlisted de-identified text evidence.')


if __name__=='__main__':main()
