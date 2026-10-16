"""The new-event power preview reads when events happened, never their size."""

from __future__ import annotations

import inspect
import re
from datetime import date

import pytest

from src.research import event_power as E


@pytest.mark.unit
def test_the_module_never_reads_a_size_direction_or_text_column():
    code = inspect.getsource(E).split('"""', 2)[2]
    for col in ("pct", "shares", "num_shares", "pct_shares", "attchmntText", "revenue", "pat", "eps"):
        assert not re.search(rf"\b{col}\b", code), f"the preview names the value column {col!r}"


@pytest.mark.unit
def test_announcement_events_are_one_per_company_day_and_category():
    rows = [{"desc": "Acquisition", "sm_isin": "INE1", "sort_date": "2025-03-04 10:00:00"},
            {"desc": "Acquisition ", "sm_isin": "INE1", "sort_date": "2025-03-04 18:00:00"},
            {"desc": "Credit Rating", "sm_isin": "INE1", "sort_date": "2025-03-04 10:00:00"},
            {"desc": "Acquisition", "sm_isin": None, "sort_date": "2025-03-05 10:00:00"}]
    assert E.announce_events("Acquisition", rows) == [("2025-03-04", "INE1")]


@pytest.mark.unit
def test_the_bound_scales_with_the_horizon():
    r = E.Row("x", "63s (3m)", 3.0, 100, 40, "2023-01", 0.02, 0.012)
    assert r.bound == pytest.approx(0.015) and r.ratio == pytest.approx(0.8)
    assert date(2026, 1, 1)                                      # imports stay used under ruff
