"""Finite unprivileged host/TCP observer; capture command output, never packet payload."""
from datetime import datetime,timezone
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from monitor import snapshot,derive


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',required=True);p.add_argument('--peer',required=True)
    a=p.parse_args();out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
    previous=snapshot();rows=[];deadline=time.monotonic()+50
    with (out/'sockets.txt').open('w')as sockets:
        while time.monotonic()<deadline and not(out/'observer-stop').exists():
            time.sleep(1);current=snapshot();sample=derive(previous,current);previous=current
            rows.append(sample)
            sockets.write(datetime.now(timezone.utc).isoformat()+'\n')
            sockets.write(subprocess.run(['ss','-tin','dst '+a.peer+' and ( sport = :8090 or dport = :8090 or sport = :5201 or dport = :5201 )'],capture_output=True,text=True,timeout=3).stdout)
            sockets.flush()
    (out/'host.json').write_text(json.dumps(rows,indent=2))


if __name__=='__main__':main()
