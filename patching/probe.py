"""Record valid client quotes continuously at four scheduled arrivals a second."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from time import monotonic, sleep, time
from urllib.error import HTTPError
from urllib.request import urlopen


def request(url, scheduled):
    start = monotonic()
    row = {"time": time(), "dispatch_ms": (start - scheduled) * 1000}
    try:
        with urlopen(url + "/quote", timeout=3) as response:
            payload = json.load(response)
            row.update(status=response.status, node=payload.get("node"),
                       valid=payload.get("quote") == 42 and payload.get("node") in {"patch-canary", "patch-peer"})
    except (OSError, ValueError) as error:
        row.update(status=error.code if isinstance(error, HTTPError) else 0, node=None, valid=False)
    row["elapsed_ms"] = (monotonic() - start) * 1000
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pool")
    parser.add_argument("output", type=Path)
    parser.add_argument("stop_file", type=Path)
    args = parser.parse_args()
    deadline = monotonic() + 1200
    scheduled = monotonic()
    pending = set()
    with args.output.open("w", encoding="utf-8", buffering=1) as output, ThreadPoolExecutor(max_workers=12) as executor:
        while (not args.stop_file.exists() and monotonic() < deadline) or pending:
            for future in tuple(pending):
                if future.done():
                    output.write(json.dumps(future.result()) + "\n")
                    pending.remove(future)
            now = monotonic()
            if now >= scheduled and not args.stop_file.exists() and now < deadline:
                if len(pending) < 12 and now - scheduled < 0.25:
                    pending.add(executor.submit(request, args.pool, scheduled))
                else:
                    output.write(json.dumps({"time": time(), "status": "skipped", "node": None, "valid": False}) + "\n")
                scheduled += 0.25
            sleep(0.015)


if __name__ == "__main__":
    main()
