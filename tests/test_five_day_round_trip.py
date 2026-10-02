"""The five-session round-trip flag (Plan 1 §7.1, owner decision Q23).

Pinned: the window is counted in SESSIONS, not calendar days; it looks both
ways; a same-day pair is the other flag's business; the side matters; and the
flag never moves eligibility, because half of it is hindsight.
"""

from __future__ import annotations

import inspect

import duckdb
import pytest

from src.mart import clean

pytestmark = pytest.mark.unit

# Twelve sessions with a weekend gap: 2025-01-03 (Fri) -> 2025-01-06 (Mon).
SESSIONS = ["2025-01-01", "2025-01-02", "2025-01-03", "2025-01-06", "2025-01-07",
            "2025-01-08", "2025-01-09", "2025-01-10", "2025-01-13", "2025-01-14",
            "2025-01-15", "2025-01-16"]


def _rt5(legs: list[tuple[str, str, str, int, int]], n: int = 5) -> set[tuple[str, str, str]]:
    """legs: (participant, symbol, date, bought, sold) -> {(participant, date, side)}."""
    con = duckdb.connect()
    try:
        con.execute("CREATE TABLE cal (d DATE)")
        con.executemany("INSERT INTO cal VALUES (?)", [(d,) for d in SESSIONS])
        con.execute("CREATE TABLE csd (participant VARCHAR, symbol VARCHAR, trade_date DATE,"
                    " bought INT, sold INT)")
        con.executemany("INSERT INTO csd VALUES (?,?,?,?,?)", legs)
        clean.five_day_flags(con, n)
        return {(p, str(d), s) for p, _, d, s in con.execute("SELECT * FROM rt5").fetchall()}
    finally:
        con.close()


def test_a_buy_sold_back_within_five_sessions_flags_both_legs():
    got = _rt5([("F", "ACME", "2025-01-02", 1, 0), ("F", "ACME", "2025-01-08", 0, 1)])
    assert got == {("F", "2025-01-02", "BUY"), ("F", "2025-01-08", "SELL")}


def test_the_window_is_sessions_not_calendar_days():
    """01-03 -> 01-10 is seven calendar days but five sessions (the weekend
    does not count); 01-03 -> 01-13 is six sessions and is out."""
    assert _rt5([("F", "ACME", "2025-01-03", 1, 0), ("F", "ACME", "2025-01-10", 0, 1)])
    assert not _rt5([("F", "ACME", "2025-01-03", 1, 0), ("F", "ACME", "2025-01-13", 0, 1)])


def test_same_side_twice_is_accumulation_not_a_round_trip():
    assert not _rt5([("F", "ACME", "2025-01-02", 1, 0), ("F", "ACME", "2025-01-06", 1, 0)])


def test_a_same_day_pair_is_left_to_the_same_day_flag():
    assert not _rt5([("F", "ACME", "2025-01-02", 1, 1)])


def test_another_participant_or_another_stock_is_not_a_round_trip():
    assert not _rt5([("F", "ACME", "2025-01-02", 1, 0), ("G", "ACME", "2025-01-06", 0, 1)])
    assert not _rt5([("F", "ACME", "2025-01-02", 1, 0), ("F", "OTHER", "2025-01-06", 0, 1)])


def test_only_the_undone_side_of_a_mixed_day_is_flagged():
    """A day with a buy and a sell, followed by a buy: the SELL on that day was
    undone; the buy was not (the later leg is also a buy)."""
    got = _rt5([("F", "ACME", "2025-01-02", 1, 1), ("F", "ACME", "2025-01-06", 1, 0)])
    assert ("F", "2025-01-02", "SELL") in got
    assert ("F", "2025-01-02", "BUY") not in got


def test_the_flag_never_decides_eligibility():
    """Monday's buy is flagged from Thursday's sell. Using that to drop Monday's
    buy from a study is a look-ahead, so the reason ladder must not read it."""
    src = inspect.getsource(clean.build)
    ladder = src[src.index("WHEN side IS NULL"): src.index("AS reason")]
    assert "five_day" not in ladder and "r5." not in ladder
