"""Four CPU workers for a lab-only, time-limited systemd transient unit."""
from multiprocessing import Process


def worker():
    value = 1
    while True:
        value = (value * 1664525 + 1013904223) & 0xFFFFFFFF


if __name__ == "__main__":
    workers = [Process(target=worker) for _ in range(4)]
    for process in workers:
        process.start()
    for process in workers:
        process.join()
