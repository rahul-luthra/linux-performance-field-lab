"""Export only text telemetry, replacing lab addresses with role labels; never copy data files or keys."""
import argparse
from pathlib import Path
import re
from zipfile import ZipFile,ZIP_DEFLATED
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--role',choices=['client','server'],required=True);p.add_argument('--client-address',required=True);p.add_argument('--server-address',required=True);args=p.parse_args()
root=Path(__file__).resolve().parent.parent;source=root/'results/storage'/args.role
names={'capture.json','host.json','unit-result.txt','iostat.txt','nfsiostat.txt','mountstats-before.txt','mountstats-after.txt',
       'controller.json','noise.json','network.json','network-filter.txt','nfsd-before.txt','nfsd-after.txt','server-verification.json','setup.json'}
with ZipFile(root/'results'/('storage-'+args.role+'.zip'),'w',ZIP_DEFLATED)as archive:
    for file in source.rglob('*'):
        if file.is_file()and file.name in names:
            text=file.read_text().replace(args.client_address,'lab-client').replace(args.server_address,'lab-nfs-server')
            lines=text.splitlines(keepends=True)
            if lines and lines[0].startswith('Linux '):lines[0]=re.sub(r'\([^)]*\)','(lab-'+args.role+')',lines[0],count=1)
            archive.writestr('storage/'+args.role+'/'+file.relative_to(source).as_posix(),''.join(lines))
print('Exported '+args.role+' text telemetry.')
