"""Synthetic HTTP dependency and frontend for the two-VM reliability lab."""
import argparse
import http.client
import json
import socket
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def utc():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def dependency_result(host, port, timeout):
    connection = http.client.HTTPConnection(host, port, timeout=timeout)
    try:
        connection.request("GET", "/price")
        response = connection.getresponse()
        if response.status == 200 and response.read(100) == b'{"price":42}':
            return 200, "ok"
        return 502, "invalid_dependency_response"
    except (socket.timeout, TimeoutError):
        return 504, "dependency_timeout"
    except ConnectionRefusedError:
        return 503, "dependency_connection_refused"
    except (OSError, http.client.HTTPException):
        return 503, "dependency_transport_error"
    finally:
        connection.close()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        config = self.server.config
        if self.path == "/live":
            self.reply(200, b'{"live":true}')
            return
        if config.role == "dependency" and self.path == "/price":
            delay = int(config.setting.read_text()) / 1000
            time.sleep(delay)
            self.reply(200, b'{"price":42}')
            return
        if config.role != "frontend" or self.path != "/quote":
            self.reply(404, b"{}")
            return
        timeout_ms = int(config.setting.read_text())
        started = time.perf_counter()
        status, cause = dependency_result(config.peer, config.peer_port, timeout_ms / 1000)
        request_id = self.headers.get("X-Lab-Request", "probe")
        payload = {"price": 42} if status == 200 else {"error": cause}
        event = dict(time=utc(), request_id=request_id, status=status, cause=cause,
                     dependency_ms=round((time.perf_counter() - started) * 1000, 3),
                     timeout_ms=timeout_ms)
        print(json.dumps(event), flush=True)
        self.reply(status, json.dumps(payload).encode())

    def reply(self, status, payload):
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, *_args):
        pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("role", choices=["frontend", "dependency"])
    parser.add_argument("--bind", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--peer")
    parser.add_argument("--peer-port", type=int)
    parser.add_argument("--setting", type=Path, required=True)
    config = parser.parse_args()
    with ThreadingHTTPServer((config.bind, config.port), Handler) as server:
        server.config = config
        server.serve_forever()
