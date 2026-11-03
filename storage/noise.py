"""Bounded random direct synchronous writes to a preinitialized 64-MiB noise file."""
from concurrent.futures import ThreadPoolExecutor
import json
import mmap
import os
from pathlib import Path
import random
import signal
import sys
import threading
import time

file,out,seconds=Path(sys.argv[1]),Path(sys.argv[2]),int(sys.argv[3]);out.mkdir(parents=True,exist_ok=True)
assert file.stat().st_size==64*1048576
stop=threading.Event();signal.signal(signal.SIGTERM,lambda *_:stop.set())
group=next(line.split('::',1)[1] for line in Path('/proc/self/cgroup').read_text().splitlines() if line.startswith('0::'))
cg=Path('/sys/fs/cgroup')/group.lstrip('/')
def read(name):
    try:return (cg/name).read_text().strip()
    except OSError:return None
before=read('io.stat');start=time.monotonic();ready=threading.Event()
def worker(index):
    count=0;generator=random.Random(1234+index);buffer=mmap.mmap(-1,8192);buffer[:]=bytes([index+1])*8192
    fd=os.open(file,os.O_RDWR|os.O_DIRECT|os.O_DSYNC)
    try:
        while not stop.is_set() and time.monotonic()-start<seconds:
            assert os.pwrite(fd,buffer,generator.randrange((64*1048576)//8192)*8192)==8192
            count+=1;ready.set()
        return count
    finally:os.close(fd);buffer.close()
try:
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures=[executor.submit(worker,i) for i in range(2)]
        if not ready.wait(5):raise RuntimeError('No direct write completed')
        (out/'ready').touch()
        counts=[future.result() for future in futures]
finally:
    stop.set()
    result={'seconds':round(time.monotonic()-start,3),'io_max':read('io.max'),'io_before':before,'io_after':read('io.stat'),
            'worker_writes':counts if 'counts'in locals() else None,'block_bytes':8192,'workers':2}
    (out/'noise.json').write_text(json.dumps(result,indent=2))
