"""network.py — is the LOCAL network up, before we blame the remote host?

WHY THIS EXISTS, MEASURED 2026-09-25. DNS failures ("nodename nor servname
provided") were the largest single class of fetch failure in the manifest —
148 of 277 since 09-15 — and they are not NSE's doing: a remote host that is
throttling answers 403, times out or resets. A name that will not RESOLVE is
this machine's network, and on a university Wi-Fi it has two ordinary causes:

  1. The Mac just woke. Wi-Fi takes seconds to re-associate. On 09-21 the
     10:30 SHP session was frozen by sleep, the Mac woke at 11:23:47, and the
     session fired its next request at 11:23:55 — five DNS failures in a
     minute tripped the throttle breaker and the session stopped, blaming NSE
     for a Wi-Fi radio that was still coming up.
  2. The campus portal logged the machine out after ~10 idle minutes. The
     radio is associated, DNS may resolve, but every request is intercepted
     until somebody logs in again.

So before counting a DNS failure against the remote host, ask the network.

THE PROBE is Apple's own captive-portal check, the same URL macOS uses to
decide whether to pop the Wi-Fi login sheet: it answers a fixed page whose
body contains "Success". Three outcomes:

  UP      the page came back and says Success — the internet is reachable.
  PORTAL  something answered, but not Apple — a captive portal intercepted it.
  DOWN    nothing answered at all: no association, no DNS, no route.

Only UP means a failure afterwards is the remote host's.
"""

from __future__ import annotations

import sys
import time
from urllib.request import Request, urlopen

from src.common.bounded import bounded

PROBE_URL = "http://captive.apple.com/hotspot-detect.html"
PROBE_TIMEOUT = 8
UP, PORTAL, DOWN = "UP", "PORTAL", "DOWN"


def probe() -> str:
    """One check. Never raises."""
    def _read() -> bytes:
        req = Request(PROBE_URL, headers={"User-Agent": "CaptiveNetworkSupport"})
        with urlopen(req, timeout=PROBE_TIMEOUT) as resp:  # noqa: S310 - fixed URL
            return resp.read(4096)
    try:
        body = bounded(_read, PROBE_TIMEOUT + 4, what="network probe")
    except Exception:  # noqa: BLE001 - any failure to reach it means DOWN
        return DOWN
    return UP if b"Success" in body else PORTAL


def wait_for_network(max_seconds: float = 180, poll: float = 10,
                     _probe=probe, _sleep=time.sleep, _now=time.monotonic) -> tuple[str, float]:
    """Probe until UP or `max_seconds` pass. Returns (final state, seconds waited).

    Three minutes by default: a woken Mac re-associates in seconds, so a
    network still down after three minutes is a portal or an outage, and
    waiting longer only burns the run's wall clock.
    """
    t0 = _now()
    state = _probe()
    while state != UP and _now() - t0 < max_seconds:
        _sleep(poll)
        state = _probe()
    return state, _now() - t0


class NetworkDown(RuntimeError):
    """The local network stayed down past the wait. Not the remote host's
    fault, so a run stopped by it must not be reported as THROTTLED."""

    def __init__(self, state: str, waited: float):
        self.state, self.waited = state, waited
        why = ("the Wi-Fi portal is intercepting — log in to the network"
               if state == PORTAL else "no network — Wi-Fi down or DNS not answering")
        super().__init__(f"LOCAL NETWORK {state} for {waited:.0f}s, not the remote host: {why}")


#: How long a collector waits for its own network before giving up the run.
LOCAL_NET_WAIT = 180


def counts_against_host(err: str, max_wait: float = LOCAL_NET_WAIT,
                        _probe=None, _wait=None) -> bool:
    """Should this failure count toward the remote host's throttle breaker?

    Anything that is not a name-resolution failure: yes, as before. A DNS
    failure: ask the network. If the network is fine right now, the name
    failure is the host's (its DNS is broken) and it counts. If the network
    is NOT fine, wait for it: back up means the failure was local and it does
    not count; still down means the run stops, named for what actually
    happened, via NetworkDown.
    """
    if not is_local_network_error(err):
        return True
    _probe = _probe or probe
    _wait = _wait or wait_for_network
    if _probe() == UP:
        return True
    state, waited = _wait(max_wait)
    if state == UP:
        print(f"  local network was down; back after {waited:.0f}s — not counted against the host",
              flush=True)
        return False
    raise NetworkDown(state, waited)


def is_local_network_error(err: str) -> bool:
    """The error says the NAME did not resolve — this machine's network, not
    the remote host. Throttling looks different: 403, timeouts, resets."""
    e = err.lower()
    return "nodename nor servname" in e or "name or service not known" in e \
        or "temporary failure in name resolution" in e


def main(argv: list[str] | None = None) -> int:
    """`python -m src.common.network --wait 180` — exit 0 UP, 2 PORTAL, 1 DOWN."""
    argv = sys.argv[1:] if argv is None else argv
    wait = float(argv[argv.index("--wait") + 1]) if "--wait" in argv else 0
    state, waited = wait_for_network(wait) if wait else (probe(), 0.0)
    hint = {UP: "internet reachable",
            PORTAL: "a captive portal is intercepting — log in to the Wi-Fi",
            DOWN: "no network — Wi-Fi not associated or DNS not answering"}[state]
    print(f"NETWORK: {state} after {waited:.0f}s — {hint}")
    return {UP: 0, PORTAL: 2, DOWN: 1}[state]


if __name__ == "__main__":
    raise SystemExit(main())
