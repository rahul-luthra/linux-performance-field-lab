#!/usr/bin/env python3
"""Opt-in bounded CPU workload for an isolated Linux lab VM only."""
import argparse
import multiprocessing as mp
import os
import time


def burn(seconds):
    end = time.monotonic() + seconds
    n = 1
    while time.monotonic() < end:
        for _ in range(10000):
            n = (n * 1664525 + 1013904223) % (2 ** 32)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--isolated-lab', action='store_true', required=True)
    parser.add_argument('--workers', type=int, default=1)
    parser.add_argument('--seconds', type=int, default=30)
    args = parser.parse_args()
    if not 1 <= args.workers <= min(8, (os.cpu_count() or 1) * 2):
        parser.error('workers must be 1 through min(8, logical CPUs * 2)')
    if not 1 <= args.seconds <= 120:
        parser.error('seconds must be 1 through 120')
    workers = [mp.Process(target=burn, args=(args.seconds,)) for _ in range(args.workers)]
    try:
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join()
    finally:
        for worker in workers:
            if worker.is_alive():
                worker.terminate()
            worker.join()
