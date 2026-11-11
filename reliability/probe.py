"""Send timed requests from the frontend VM, with liveness probes in parallel."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import http.client
import json
import time
from service import utc


def request(host, port, path, request_id):
    started = time.perf_counter()
    connection = http.client.HTTPConnection(host, port, timeout=3)
    try:
        connection.request("GET", path, headers={"X-Lab-Request": request_id})
        response = connection.getresponse()
        payload = json.loads(response.read(256))
        return response.status, payload, round((time.perf_counter() - started) * 1000, 3)
    except (OSError, ValueError, http.client.HTTPException):
        return None, {}, round((time.perf_counter() - started) * 1000, 3)
    finally:
        connection.close()


def measure(port, request_id, scheduled, epoch):
    lag_ms = round((time.perf_counter() - epoch - scheduled) * 1000, 3)
    timestamp = utc()
    status, payload, elapsed = request("127.0.0.1", port, "/quote", request_id)
    return dict(request_id=request_id, scheduled_s=scheduled, started_utc=timestamp,
                lag_ms=lag_ms, status=status, correct=status == 200 and payload == {"price": 42},
                elapsed_ms=elapsed, error=payload.get("error"))


def capture(port, phase):
    start = utc()
    requests, liveness = [], []
    with ThreadPoolExecutor(max_workers=12) as pool:
        epoch = time.perf_counter()
        for index in range(24):
            scheduled = index / 4
            time.sleep(max(0, epoch + scheduled - time.perf_counter()))
            requests.append(pool.submit(measure, port, f"{phase}-{index:02}", scheduled, epoch))
            if index % 4 == 0:
                liveness.append(pool.submit(request, "127.0.0.1", port, "/live", "liveness"))
    return dict(started_utc=start, finished_utc=utc(),
                requests=[future.result() for future in requests],
                liveness=[dict(status=status, correct=status == 200 and body == {"live": True},
                               elapsed_ms=ms) for status, body, ms in (f.result() for f in liveness)])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--phase")
    parser.add_argument("--wait-host")
    args = parser.parse_args()
    if args.wait_host:
        for _ in range(30):
            status, payload, _ = request(args.wait_host, args.port, "/live", "startup")
            if status == 200 and payload == {"live": True}:
                break
            time.sleep(0.2)
        else:
            raise SystemExit("Liveness check failed")
    else:
        print(json.dumps(capture(args.port, args.phase)))
