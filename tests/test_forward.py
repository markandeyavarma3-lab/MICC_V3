"""exp_006's forward machinery (src/scan/forward.py): when scoring may start,
how the frozen 100 are chosen and parsed, and the one read's arithmetic."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pytest

from src.scan import forward as F


def _sessions(start: date, n: int) -> list[date]:
    out, d = [], start
    while len(out) < n:
        d += timedelta(days=1)
        if d.weekday() < 5:
            out.append(d)
    return out


@pytest.mark.unit
def test_scoring_starts_on_the_22nd_session_after_the_grid_and_not_before():
    s = [date(2026, 9, 30), date(2026, 10, 1), *_sessions(date(2026, 10, 1), 30)]
    assert F.first_entry(s) == [d for d in s if d > F.TRAIN_END][21]
    assert F.first_entry(s[:20]) is None                      # not yet happened


@pytest.mark.unit
def test_a_key_round_trips_in_the_atlas_format():
    c = (("hi_252", 1), ("downvol_126", -1))
    assert F.parse_key(F._key(c)) == c
    assert F.parse_key("+x") == (("x", 1),)


@pytest.mark.unit
def test_the_selection_is_the_largest_absolute_means_deterministically():
    m = np.array([0.01, -0.05, np.nan, 0.05, 0.002])
    assert F.top_by_abs(m, 3).tolist() == [1, 3, 0]           # tie at 0.05 breaks on the lower index


@pytest.mark.unit
def test_the_read_passes_only_above_both_bars():
    rng = np.random.default_rng(1)
    names, comp = np.full(100, 400), np.ones(100, dtype=bool)
    strong = rng.normal(0.03, 0.07, 100)
    tiny = rng.normal(0.004, 0.002, 100)                      # significant, below MIN_EFFECT
    noise = rng.normal(0.0, 0.07, 100)
    assert F.decide(strong, names, comp, F.T_BAR)["verdict"] == "PERSISTS"
    assert F.decide(tiny, names, comp, F.T_BAR)["verdict"] == "SIGNIFICANT_BUT_SMALL"
    assert F.decide(noise, names, comp, F.T_BAR)["verdict"] == "DOES_NOT_PERSIST"


@pytest.mark.unit
def test_the_kill_criteria_stop_the_read():
    x = np.full(100, 0.03)
    assert F.decide(x, np.full(100, 90), np.ones(100, dtype=bool), F.T_BAR)["verdict"] == "UNDERPOWERED"
    lost = np.ones(100, dtype=bool)
    lost[:21] = False
    assert F.decide(x, np.full(100, 400), lost, F.T_BAR)["verdict"] == "UNREADABLE"
