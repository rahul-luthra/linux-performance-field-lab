"""Serve round-robin quotes with a scoped control endpoint for the patch workflow."""
import argparse
from contextlib import contextmanager
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from threading import Condition
from time import monotonic
from urllib.request import urlopen


class Pool:
    def __init__(self, endpoints):
        self.endpoints = endpoints
        self.active = set(endpoints)
        self.inflight = dict.fromkeys(endpoints, 0)
        self.position = 0
        self.lock = Condition()

    @contextmanager
    def lease(self):
        with self.lock:
            names = sorted(self.active)
            name = names[self.position % len(names)]
            self.position += 1
            self.inflight[name] += 1
        try:
            yield name
        finally:
            with self.lock:
                self.inflight[name] -= 1
                self.lock.notify_all()

    def quote(self, name):
        with urlopen(self.endpoints[name] + "/quote", timeout=2) as response:
            payload = json.load(response)
        if payload != {"node": name, "quote": 42}:
            raise ValueError(f"{name} returned an invalid quote")
        return payload

    def members(self):
        with self.lock:
            return sorted(self.active)

    def change(self, name, action):
        if name not in self.endpoints:
            raise ValueError("Unknown target")
        if action == "ready":
            self.quote(name)
            with self.lock:
                self.active.add(name)
        elif action == "drained":
            with self.lock:
                if self.active == {name}:
                    raise ValueError("Cannot drain the last active target")
                self.active.discard(name)
                deadline = monotonic() + 5
                while self.inflight[name]:
                    if monotonic() >= deadline:
                        raise TimeoutError("Target was removed but still has in-flight requests")
                    self.lock.wait(deadline - monotonic())
        else:
            raise ValueError("Unknown pool action")
        return {"active": self.members()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    token = config["token"]
    pool = Pool(config["backends"])

    class Router(BaseHTTPRequestHandler):
        def send_json(self, status, payload):
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def authorize(self):
            if hmac.compare_digest(self.headers.get("Authorization", ""), "Bearer " + token):
                return True
            self.send_json(403, {"error": "Access denied"})
            return False

        def do_GET(self):
            if self.path == "/quote":
                try:
                    with pool.lease() as target:
                        payload = pool.quote(target)
                    self.send_json(200, payload)
                except (OSError, ValueError):
                    self.send_json(502, {"error": "Quote request failed"})
            elif self.path == "/pool":
                if self.authorize():
                    self.send_json(200, {"active": pool.members()})
            else:
                self.send_error(404)

        def do_PUT(self):
            if not self.path.startswith("/pool/"):
                self.send_error(404)
                return
            if not self.authorize():
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
                if not 0 < length <= 64:
                    raise ValueError("Invalid request length")
                action = json.loads(self.rfile.read(length))["state"]
                self.send_json(200, pool.change(self.path.removeprefix("/pool/"), action))
            except (OSError, ValueError, KeyError, TypeError) as error:
                self.send_json(409, {"error": str(error)})

        def log_message(self, *_):
            pass

    ThreadingHTTPServer((config["bind"], config["port"]), Router).serve_forever()


if __name__ == "__main__":
    main()
