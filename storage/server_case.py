"""Start/finish bounded server observers and optional direct-write interference."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import struct
import zlib

p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['start','finish']);p.add_argument('--case',required=True);p.add_argument('--noise',choices=['none','unlimited','limited'],default='none');args=p.parse_args()
root=Path(__file__).resolve().parent.parent;out=root/'results/storage/server'/args.case;unit='nfsnoise-'+args.case
if args.action=='start':
    if out.exists():raise RuntimeError('Existing server case must be preserved')
    out.mkdir(parents=True)
    before=Path('/proc/net/rpc/nfsd').read_text();(out/'nfsd-before.txt').write_text(before)
    observer=subprocess.Popen([sys.executable,str(root/'storage/telemetry.py'),str(out),'45'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
    if args.noise!='none':
        file=Path('/srv/nfs/perf-lab/background.bin')
        if not file.exists():
            with file.open('xb')as handle:
                for _ in range(64):handle.write(bytes(1048576))
                handle.flush();os.fsync(handle.fileno())
        assert file.stat().st_size==64*1048576
        command=['sudo','-n','systemd-run','--unit='+unit,'--quiet','--service-type=exec','--property=User=rahul',
                 '--property=IOAccounting=yes','--property=MemoryMax=128M','--property=RuntimeMaxSec=45','--property=TimeoutStopSec=5','--property=TasksMax=16']
        if args.noise=='limited':command+=['--property=IOWriteIOPSMax=/dev/sda 50']
        command += [sys.executable,str(root/'storage/noise.py'),str(file),str(out),'40']
        subprocess.run(command,check=True,capture_output=True,text=True)
        for _ in range(100):
            if(out/'ready').exists():break
            time.sleep(.1)
        else:raise RuntimeError('Noise did not become ready')
    (out/'controller.json').write_text(json.dumps({'noise':args.noise,'observer_pid':observer.pid,'unit':unit},indent=2))
    print('SERVER_READY',flush=True)
else:
    config=json.loads((out/'controller.json').read_text())
    if config['noise']!='none':subprocess.run(['sudo','-n','systemctl','stop',unit],check=True,capture_output=True)
    (out/'stop-telemetry').touch()
    for _ in range(60):
        if(out/'host.json').exists():break
        time.sleep(.1)
    (out/'nfsd-after.txt').write_text(Path('/proc/net/rpc/nfsd').read_text())
    (out/'network.json').write_text(subprocess.check_output(['tc','-j','-s','qdisc','show','dev','enp0s3'],text=True))
    (out/'network-filter.txt').write_text(subprocess.check_output(['tc','filter','show','dev','enp0s3','parent','1:'],text=True))
    file=Path('/srv/nfs/perf-lab')/(args.case+'.bin')
    if file.exists():
        last=None;count=0
        with file.open('rb')as handle:
            for slot in range(256):
                block=handle.read(65536)
                if len(block)==65536 and block[8:]==bytes([0x5a])*(65536-8):
                    sequence=struct.unpack('>q',block[:8])[0]
                    if sequence%256==slot:
                        count+=1
                        if last is None or sequence>last['sequence']:last={'sequence':sequence,'slot':slot,'crc32':zlib.crc32(block)}
        (out/'server-verification.json').write_text(json.dumps({'valid_written_slots':count,'latest':last},indent=2))
    if config['noise']!='none':
        state=subprocess.run(['systemctl','show',unit,'-p','Result','-p','IOWriteBytes'],capture_output=True,text=True)
        (out/'unit-result.txt').write_text(state.stdout)
        subprocess.run(['sudo','-n','systemctl','reset-failed',unit],capture_output=True)
    print('SERVER_FINISHED',flush=True)
