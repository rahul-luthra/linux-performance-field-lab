"""Small application used to verify the patch targets."""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import socket


class Quote(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/quote":
            self.send_error(404)
            return
        bad = Path("/etc/patch-demo/fault").exists()
        payload = json.dumps({"node": socket.gethostname(), "quote": 0 if bad else 42}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *_):
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8080), Quote).serve_forever()
