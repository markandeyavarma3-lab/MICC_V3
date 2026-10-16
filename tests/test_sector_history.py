"""Point-in-time industries from the fund portfolios (src/warehouse/sector_history.py)."""

from __future__ import annotations

from datetime import date

import pytest

from src.warehouse import sector_history as H


@pytest.mark.unit
def test_a_label_is_known_from_the_tenth_of_the_next_month():
    assert H.known_from(date(2026, 9, 30)) == date(2026, 10, 10)
    assert H.known_from(date(2025, 12, 31)) == date(2026, 1, 10)


@pytest.mark.unit
def test_the_month_label_is_the_majority_across_schemes_ignoring_spelling():
    rows = [("INE1", date(2026, 8, 31), "Banks"), ("INE1", date(2026, 8, 31), "banks "),
            ("INE1", date(2026, 8, 31), "BANKS"), ("INE1", date(2026, 8, 31), "Finance")]
    got = H.monthly_labels(rows)[("INE1", date(2026, 8, 31))]
    assert got == ("Banks", "HIGH")                   # 3 of 4 agree; the commonest exact spelling
    lone = H.monthly_labels([("INE2", date(2026, 8, 31), "Power")])
    assert lone[("INE2", date(2026, 8, 31))][1] == "MEDIUM"   # unanimous but one row


@pytest.mark.unit
def test_months_merge_and_a_change_closes_the_interval_the_day_before_it_is_known():
    lab = {("INE1", date(2026, 6, 30)): ("Software", "HIGH"), ("INE1", date(2026, 7, 31)): ("Software", "LOW"),
           ("INE1", date(2026, 9, 30)): ("IT - Software", "HIGH")}
    got = H.intervals(lab)
    assert got == [("INE1", "Software", date(2026, 7, 10), date(2026, 10, 9), "LOW"),
                   ("INE1", "IT - Software", date(2026, 10, 10), None, "HIGH")]
