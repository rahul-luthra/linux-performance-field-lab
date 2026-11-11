# Linux service reliability through a dependency outage

A Python quote frontend on one Linux VM calls a price service on another. The frontend's `/live` endpoint can answer on its own. The `/quote` endpoint needs a valid price from the dependency. The lab target is HTTP 200 with the expected quote within 250 ms. [Interactive measurements](https://rahul-luthra.github.io/linux-performance-field-lab/reliability.html)

Each phase scheduled 24 quote requests at four per second and sampled liveness six times. The probe ran on the frontend VM. The p95 includes every quote outcome, including errors. Each phase used the same frontend PID, verified with `systemctl show` at its boundaries.

| Phase | HTTP result | Correct within 250 ms | Quote p95 | Liveness |
|---|---|---:|---:|---:|
| Healthy | 24 × 200 | 24/24 | 19.1 ms | 6/6 |
| Dependency delayed by 650 ms | 24 × 200 | 0/24 | 662.9 ms | 6/6 |
| Dependency stopped | 24 × 503 | 0/24 | 14.5 ms | 6/6 |
| Dependency restarted | 24 × 200 | 24/24 | 76.4 ms | 6/6 |
| Same delay with a 200 ms socket timeout | 24 × 504 | 0/24 | 482.6 ms | 6/6 |
| Delay removed | 24 × 200 | 24/24 | 17.0 ms | 6/6 |

## Investigate the user-visible failure

Liveness passed all 36 probes. A check of the process and its liveness endpoint would have missed the outage and slow quotes. The quote probe exposed both. During the slow phase every quote was correct, but all 24 missed the latency target. During the outage, responses were quick and every one was an error.

The dependency unit was inactive during the outage. Matching request IDs in the client capture and the frontend's systemd journal tied each 503 to a refused dependency connection. Starting a fresh instance of the dependency restored 24 correct quotes within target without restarting the frontend. [Raw capture and journal](results/reliability/capture.json)

The dependency VM's clock was about five days and nine hours behind the frontend. Use each VM's journal for its own event order. Request IDs link frontend journal entries to probes, and the latency measurements use monotonic clocks.

## Compare timeout behavior and recovery

With the same 650 ms injected delay, shortening the socket timeout from 1,500 ms to 200 ms moved the quote p95 from 662.9 ms to 482.6 ms. All 24 responses were 504 errors. The shorter setting reduced waiting in this run. Removing the delay was what restored successful quotes.

The 200 ms setting applied to blocking socket operations. It did not set a wall-clock limit for the complete quote. The frontend journal recorded a dependency call p95 of 475.0 ms in that phase. The lab did not isolate the cause of that overshoot. Probe starts also lagged their scheduled times by up to 362 ms in the healthy phase, so the nominal rate describes the schedule. This six-phase sample illustrates failure modes on these VMs and provides no production tail-latency estimate.

The initial trial classified Python 3.9 socket timeouts as generic 503 transport errors. I corrected the timeout handler and reran every phase. This page and its downloadable capture use the corrected run.

## Interview walkthrough

“I saw the service was active and its liveness check passed, but users couldn’t get a quote. I sent a request that exercised the dependency and matched its request ID to the journal. The log showed a refused connection, and systemd showed the dependency was stopped. After starting it, every test quote met the target again. I also tested a slow dependency. A shorter timeout got an error back sooner, and removing the delay restored successful quotes.”

The test services ran in temporary systemd units. Post-run checks confirmed that both test ports were closed and the temporary firewall rule was absent. [Reproduction guide](reliability/README.md)
