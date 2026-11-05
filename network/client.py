"""Open-loop small requests and separately timed bounded bulk downloads."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import http.client
import json
from pathlib import Path
import time
import zlib


def request(host, port, path, scheduled=None, epoch=None):
    started = time.perf_counter()
    result = {'scheduled_s': scheduled, 'scheduler_lag_ms': max(0, (started - epoch - scheduled) * 1000) if epoch is not None else None}
    connection = http.client.HTTPConnection(host, port, timeout=5)
    try:
        connection.connect()
        connected = time.perf_counter()
        connection.request('GET', path)
        response = connection.getresponse()
        headers = time.perf_counter()
        body = response.read(512 * 1024 + 1)
        finished = time.perf_counter()
        expected_size = 512 * 1024 if path.startswith('/large') else 1024
        result.update(status=response.status, bytes=len(body), connect_ms=(connected-started)*1000,
                      headers_ms=(headers-started)*1000, latency_ms=(finished-started)*1000,
                      body_ms=(finished-headers)*1000,
                      handler_ms=float(response.getheader('X-Handler-Ms')),
                      handler_cpu_ms=float(response.getheader('X-Handler-CPU-Ms')),
                      correct=response.status == 200 and len(body) == expected_size and body == b'N'*expected_size
                      and zlib.crc32(body) == int(response.getheader('X-CRC32')))
    except Exception as error:
        result.update(status=None, correct=False, error=type(error).__name__, latency_ms=(time.perf_counter()-started)*1000)
    finally:
        connection.close()
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--server',required=True);p.add_argument('--out',required=True)
    p.add_argument('--pause-ms',type=int,choices=[0,100],default=0);p.add_argument('--port',type=int,default=8090)
    args=p.parse_args();path=Path(args.out)
    if path.exists():p.error('Refuse to overwrite evidence')
    for _ in range(8):request(args.server,args.port,'/small?pause_ms='+str(args.pause_ms))
    started=datetime.now(timezone.utc).isoformat();epoch=time.perf_counter();futures=[]
    with ThreadPoolExecutor(max_workers=8) as executor:
        for index in range(100):
            scheduled=index/5
            time.sleep(max(0,epoch+scheduled-time.perf_counter()))
            futures.append(executor.submit(request,args.server,args.port,'/small?pause_ms='+str(args.pause_ms),scheduled,epoch))
        rows=[future.result()for future in futures]
    large=[request(args.server,args.port,'/large')for _ in range(5)]
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps({'started_utc':started,'finished_utc':datetime.now(timezone.utc).isoformat(),
                               'offered_rps':5,'request_policy':'new TCP connection per request; no TLS or DNS; HTTP/1.1',
                               'pause_ms':args.pause_ms,'requests':rows,'bulk':large},indent=2))
    print(json.dumps({'requests':len(rows),'correct':sum(r['correct']for r in rows),'bulk_correct':sum(r['correct']for r in large)}))


if __name__=='__main__':main()
