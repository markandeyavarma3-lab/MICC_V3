"""The local network, asked before the remote host is blamed.

148 of 277 fetch failures since 2026-09-15 were DNS failures — this machine's
network, not NSE. On 2026-09-21 an SHP session frozen by sleep woke at
11:23:47, fired five requests while the Wi-Fi radio was still re-associating,
and the throttle breaker stopped the session "THROTTLED" — blaming NSE for a
university Wi-Fi coming back up.
"""

from __future__ import annotations

import json
from datetime import date

import pytest

from src.common import network

pytestmark = pytest.mark.unit

DNS = "<urlopen error [Errno 8] nodename nor servname provided, or not known>"


def _seq(*states):
    it = iter(states)
    last = [states[-1]]
    def probe():
        try:
            last[0] = next(it)
        except StopIteration:
            pass
        return last[0]
    return probe


# --- classifying the error ------------------------------------------------------


def test_a_name_resolution_failure_is_local_and_throttling_is_not():
    assert network.is_local_network_error(DNS)
    assert not network.is_local_network_error("HTTP Error 403: Forbidden")
    assert not network.is_local_network_error("<urlopen error timed out>")
    assert not network.is_local_network_error("Connection reset by peer")


# --- waiting for it ---------------------------------------------------------------


def test_wait_returns_as_soon_as_the_network_is_up():
    clock = [0.0]
    state, waited = network.wait_for_network(
        180, poll=10, _probe=_seq("DOWN", "DOWN", "UP"),
        _sleep=lambda s: clock.__setitem__(0, clock[0] + s), _now=lambda: clock[0])
    assert state == "UP" and waited == 20


def test_wait_gives_up_at_the_limit_and_says_what_it_saw():
    clock = [0.0]
    state, waited = network.wait_for_network(
        30, poll=10, _probe=_seq("PORTAL"),
        _sleep=lambda s: clock.__setitem__(0, clock[0] + s), _now=lambda: clock[0])
    assert state == "PORTAL" and waited >= 30


# --- the decision the breakers ask for -----------------------------------------------


def test_a_non_dns_failure_counts_without_asking_the_network():
    called = []
    assert network.counts_against_host("HTTP Error 403", _probe=lambda: called.append(1) or "UP")
    assert not called, "a 403 is the host's; probing the network would only slow the run"


def test_a_dns_failure_with_the_network_up_is_the_hosts_and_counts():
    """The network answers Apple fine, so it is the HOST's name that fails."""
    assert network.counts_against_host(DNS, _probe=lambda: "UP")


def test_a_dns_failure_while_the_wifi_comes_back_does_not_count():
    """The 09-21 case: radio re-associating after sleep. Wait, then carry on."""
    assert not network.counts_against_host(
        DNS, _probe=lambda: "DOWN", _wait=lambda m: ("UP", 12.0))


def test_a_network_that_stays_down_stops_the_run_named_for_what_it_is():
    with pytest.raises(network.NetworkDown, match="not the remote host"):
        network.counts_against_host(DNS, _probe=lambda: "DOWN", _wait=lambda m: ("DOWN", 180.0))
    with pytest.raises(network.NetworkDown, match="log in"):
        network.counts_against_host(DNS, _probe=lambda: "PORTAL", _wait=lambda m: ("PORTAL", 180.0))


# --- end to end, through a collector ---------------------------------------------------


def _insider(tmp_path, monkeypatch):
    from src.archive import insider as ins
    monkeypatch.setattr(ins, "ARCHIVE", tmp_path)
    monkeypatch.setattr(ins, "MANIFEST", tmp_path / "m.jsonl")
    monkeypatch.setattr(ins, "RATE_LIMIT", 0)
    ins._prior_xbrl.clear()
    return ins


def _index(n):
    return json.dumps({"data": [
        {"appId": str(i), "symbol": "ACME", "xmlFileName": f"https://x/PIT_{i}.xml"}
        for i in range(n)]}).encode()


def test_a_wifi_blip_mid_session_does_not_trip_the_throttle_breaker(tmp_path, monkeypatch):
    """Twelve DNS failures in a row while the local network was down and came
    back — none counted, so the session is not stopped THROTTLED."""
    ins = _insider(tmp_path, monkeypatch)
    monkeypatch.setattr(ins, "_get", lambda op, url, ref: _index(12) if "corporates-pit" in url
                        else (_ for _ in ()).throw(RuntimeError(DNS)))
    monkeypatch.setattr(ins, "counts_against_host", lambda err: False)
    out = ins.collect(date(2026, 6, 1), date(2026, 6, 30))
    assert not any("THROTTLED" in o.detail for o in out)


def test_a_network_that_stays_down_stops_the_collector_as_network_down_not_throttled(tmp_path, monkeypatch):
    ins = _insider(tmp_path, monkeypatch)
    monkeypatch.setattr(ins, "_get", lambda op, url, ref: (_ for _ in ()).throw(RuntimeError(DNS)))
    def down(err):
        raise network.NetworkDown("DOWN", 180.0)
    monkeypatch.setattr(ins, "counts_against_host", down)
    out = ins.collect(date(2026, 6, 1), date(2026, 6, 30))
    assert out[-1].status == "FAILED"
    assert "NETWORK DOWN" in out[-1].detail and "THROTTLED" not in out[-1].detail
    rows = [json.loads(l) for l in (tmp_path / "m.jsonl").read_text().splitlines()]
    assert "NETWORK DOWN" in rows[-1]["error"]
