"""Finite in-memory HTTP teaching service; bind only to the lab address."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import time
from urllib.parse import urlparse, parse_qs
import zlib

SMALL = b'N' * 1024
LARGE = b'N' * (512 * 1024)


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path not in ('/small', '/large'):
            self.send_error(404)
            return
        delay = min(100, max(0, int(parse_qs(parsed.query).get('pause_ms', ['0'])[0])))
        started = time.perf_counter()
        cpu = time.thread_time()
        if delay:
            time.sleep(delay / 1000)
        body = LARGE if parsed.path == '/large' else SMALL
        self.send_response(200)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('X-CRC32', str(zlib.crc32(body)))
        self.send_header('X-Handler-Ms', str((time.perf_counter() - started) * 1000))
        self.send_header('X-Handler-CPU-Ms', str((time.thread_time() - cpu) * 1000))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, *args):
        pass


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--bind', required=True)
    p.add_argument('--port', type=int, default=8090)
    args = p.parse_args()
    ThreadingHTTPServer((args.bind, args.port), Handler).serve_forever()
