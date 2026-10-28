"""netcheck.py — wait until NSE can be reached before a scheduled job fetches.

WHY (owner, 2026-10-28). Most failures of 22-28 October were runs that began
before the internet was back after the Mac woke: every stage failed with
"nodename nor servname provided", and the 27 October bulk-deal file was lost
for good (NSE replaces it the next day). A job now checks first.

WHAT IT DOES, AND DOES NOT. It opens a plain connection to NSE's archive host
every 30 seconds, for up to 15 minutes, and returns as soon as one succeeds.
It never touches Wi-Fi, sleep, wake or power settings (the owner's standing
order). If NSE never answers, the job runs anyway and its stages fail and
report as before.

    RESEARCH_ENV=prod .venv/bin/python -m src.monitor.netcheck
"""

from __future__ import annotations

import socket
import sys
import time

HOSTS = (("nsearchives.nseindia.com", 443), ("www.nseindia.com", 443))
EVERY_S = 30
MAX_MINUTES = 15


def reachable(hosts=HOSTS, timeout: float = 8.0) -> bool:
    """True if any host accepts a connection: name lookup and route both work."""
    for host, port in hosts:
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except OSError:
            continue
    return False


def wait(max_minutes: float = MAX_MINUTES, every: float = EVERY_S, probe=reachable,
         sleep=time.sleep, clock=time.time) -> tuple[bool, float]:
    """(reached, seconds waited). Checks at once, then every `every` seconds."""
    t0 = clock()
    while True:
        if probe():
            return True, clock() - t0
        if clock() - t0 + every > max_minutes * 60:
            return False, clock() - t0
        sleep(every)


def main() -> int:
    ok, waited = wait()
    if ok:
        print(f"  NETWORK: NSE reachable{f' after {waited:.0f} s' if waited >= 1 else ''}")
        return 0
    print(f"  NETWORK: NSE not reachable after {MAX_MINUTES} min; the run continues and its stages will report")
    return 1


if __name__ == "__main__":
    sys.exit(main())
