"""Offer four QuoteLab requests per second and export a 20-second rolling p95."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
from pathlib import Path
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


QUOTE = "http://127.0.0.1:8087/quote"
RATE = 4
WINDOW = 20


def p95(values):
    ordered = sorted(values)
    return ordered[math.ceil(0.95 * len(ordered)) - 1] if ordered else None


def request(scheduled):
    start = time.monotonic()
    row = {"started": time.time(), "dispatch_ms": (start - scheduled) * 1000}
    try:
        with urlopen(QUOTE, timeout=3) as response:
            payload = json.load(response)
            row.update(
                status=response.status,
                correct=payload.get("iterations") == 1_200_000 and isinstance(payload.get("quote"), (float, int)),
                handler_wall_ms=float(response.headers["X-Handler-Wall-Ms"]),
                handler_cpu_ms=float(response.headers["X-Handler-Cpu-Ms"]),
            )
    except (HTTPError, URLError, OSError, ValueError, TypeError, KeyError) as error:
        row.update(status=getattr(error, "code", 0), correct=False, error=type(error).__name__)
    row.update(finished=time.time(), elapsed_ms=(time.monotonic() - start) * 1000)
    return row


def cpu_snapshot():
    with open("/proc/stat") as stat:
        counters = [int(value) for value in stat.readline().split()[1:9]]
    total = sum(counters)
    busy = total - counters[3] - counters[4] - counters[7]
    with open("/proc/loadavg") as loadavg:
        runnable = int(loadavg.readline().split()[3].split("/")[0])
    return total, busy, runnable


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    lock = threading.Lock()
    recent = []
    cpu = {}
    totals = {"success": 0, "failure": 0, "skipped": 0}

    class Metrics(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path != "/metrics":
                self.send_error(404)
                return
            with lock:
                window = [row for row in recent if row["finished"] > time.time() - WINDOW]
                success = [row["elapsed_ms"] for row in window if row["correct"]]
                metrics = {
                    "quotelab_probe_window_count": len(success),
                    "quotelab_probe_window_failures": len(window) - len(success),
                    "quotelab_probe_success_total": totals["success"],
                    "quotelab_probe_failure_total": totals["failure"],
                    "quotelab_probe_skipped_total": totals["skipped"],
                    **cpu,
                }
                if success:
                    metrics["quotelab_probe_window_p95_seconds"] = p95(success) / 1000
            body = "".join(f"{name} {value}\n" for name, value in metrics.items()).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 9817), Metrics)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    previous = cpu_snapshot()
    last_cpu = time.monotonic()
    scheduled = last_cpu
    pending = set()
    with args.output.open("a", encoding="utf-8", buffering=1) as output, ThreadPoolExecutor(max_workers=16) as pool:
        while True:
            now = time.monotonic()
            for future in tuple(pending):
                if future.done():
                    pending.remove(future)
                    row = future.result()
                    with lock:
                        recent.append(row)
                        totals["success" if row["correct"] else "failure"] += 1
                    output.write(json.dumps(row) + "\n")
            if now >= last_cpu + 5:
                total, busy, runnable = cpu_snapshot()
                with lock:
                    cpu["quotelab_host_cpu_execution_ratio"] = (busy - previous[1]) / (total - previous[0])
                    cpu["quotelab_host_runnable_tasks"] = runnable
                    recent[:] = [row for row in recent if row["finished"] > time.time() - WINDOW]
                previous = total, busy, runnable
                last_cpu = now
            if now >= scheduled:
                if len(pending) < 16 and now - scheduled < 1 / RATE:
                    pending.add(pool.submit(request, scheduled))
                else:
                    with lock:
                        totals["skipped"] += 1
                scheduled += 1 / RATE
            time.sleep(min(0.02, max(0, scheduled - time.monotonic())))


if __name__ == "__main__":
    main()
