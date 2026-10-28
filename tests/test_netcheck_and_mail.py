"""The start-of-run network wait, and one summary email a day (owner, 2026-10-28)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from src.monitor import digest, health, netcheck

pytestmark = pytest.mark.unit


def _clock(step: float = 30.0):
    t = {"now": 0.0}
    return (lambda: t["now"]), (lambda s: t.__setitem__("now", t["now"] + s))


def test_the_wait_returns_as_soon_as_nse_answers():
    clock, sleep = _clock()
    answers = iter([False, False, True])
    ok, waited = netcheck.wait(probe=lambda: next(answers), sleep=sleep, clock=clock)
    assert ok and waited == 60


def test_the_wait_gives_up_after_fifteen_minutes_and_the_run_goes_on():
    clock, sleep = _clock()
    ok, waited = netcheck.wait(probe=lambda: False, sleep=sleep, clock=clock)
    assert not ok and waited <= 15 * 60


def test_the_network_check_never_touches_wifi_sleep_or_power():
    src = Path(netcheck.__file__).read_text().split('"""', 2)[2]          # code, not the docstring
    for word in ("networksetup", "pmset", "caffeinate", "airport", "wake", "sleep_mode"):
        assert word not in src.lower()


def test_an_alert_does_not_email_unless_asked(monkeypatch):
    sent = []
    monkeypatch.setattr(health, "notify_desktop", lambda t, b: True)
    monkeypatch.setattr(health, "notify_telegram", lambda t, b: "telegram sent")
    monkeypatch.setattr(health, "notify_email", lambda t, b: sent.append(t) or "email sent")
    out = health.broadcast("x FAILED", "body")
    assert sent == [] and out["telegram"] == "telegram sent" and "skipped" in out["email"]
    health.broadcast("x", "body", email=True)
    assert sent == ["x"]


def test_yesterdays_missing_summary_is_sent_at_any_hour(tmp_path):
    stamp = tmp_path / ".digest_sent"
    today = date(2026, 10, 28)
    stamp.write_text("2026-10-27")
    assert not digest.missed_yesterday(today, stamp)        # sent last night: wait for 21:00
    stamp.write_text("2026-10-26")
    assert digest.missed_yesterday(today, stamp)            # last night's never went: send now
    assert digest.missed_yesterday(today, tmp_path / "none")
