"""What the rolling endpoints should be serving, and whether a miss costs anything.

Three channels told the operator data was at risk on the morning of
2026-09-17. It was not: the file on the endpoint was the previous session's,
already held. This module is the one answer all of them now consult.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from src.common.sessions import IST, expected_session, exposure

pytestmark = pytest.mark.unit


def _ist(y, m, d, hh, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=IST)


# 2026-09-17 is a Thursday.

def test_the_morning_after_a_clean_evening_expects_the_previous_session():
    """08:37 IST on 2026-09-17: the file on the endpoint is 09-16's."""
    assert expected_session(_ist(2026, 9, 17, 8, 37)) == date(2026, 9, 16)


def test_after_the_publish_hour_today_is_expected():
    assert expected_session(_ist(2026, 9, 17, 20, 30)) == date(2026, 9, 17)
    assert expected_session(_ist(2026, 9, 17, 22, 30)) == date(2026, 9, 17)


def test_a_weekend_expects_friday_whatever_the_hour():
    assert expected_session(_ist(2026, 9, 19, 9)) == date(2026, 9, 18)   # Saturday
    assert expected_session(_ist(2026, 9, 20, 23)) == date(2026, 9, 18)  # Sunday


def test_monday_morning_expects_friday_not_sunday():
    assert expected_session(_ist(2026, 9, 21, 8, 30)) == date(2026, 9, 18)


def test_the_boundary_is_evaluated_in_ist_not_utc():
    """A UTC caller at 15:00 on 09-17 is at 20:30 IST: today's file is expected.
    Read as UTC it would be 'afternoon' and expect yesterday's."""
    from datetime import UTC
    assert expected_session(datetime(2026, 9, 17, 15, 0, tzinfo=UTC)) == date(2026, 9, 17)


# --- exposure: the sentence the alerts print --------------------------------

def test_a_failed_fetch_of_a_session_already_held_is_not_at_risk():
    """THE 2026-09-17 CASE. Held 09-16, endpoint serving 09-16, fetch failed."""
    at_risk, why = exposure(date(2026, 9, 16), _ist(2026, 9, 17, 8, 37))
    assert not at_risk
    assert "nothing at risk" in why


def test_a_failed_fetch_of_a_session_not_held_is_at_risk_and_says_so():
    """The morning after a fully missed evening: held 09-15, endpoint on 09-16."""
    at_risk, why = exposure(date(2026, 9, 15), _ist(2026, 9, 17, 8, 37))
    assert at_risk
    assert "2026-09-16" in why and "NOT held" in why and "Fetch now" in why


def test_nothing_held_is_at_risk():
    at_risk, _ = exposure(None, _ist(2026, 9, 17, 8, 37))
    assert at_risk
