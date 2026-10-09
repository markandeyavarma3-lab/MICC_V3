"""The scheduled power re-measurements (configs/remeasure.yml) reach the digest."""

from __future__ import annotations

from datetime import date

import pytest

from src.monitor import remeasure

pytestmark = pytest.mark.unit


def _cfg(tmp_path, due="2027-09-15", last="2026-09-29"):
    p = tmp_path / "r.yml"
    p.write_text(f"warn_days: 30\nitems:\n  - id: x\n    what: a study\n    due: {due}\n"
                 f"    last_done: {last}\n    command: run-it\n")
    return p


def test_an_item_is_quiet_until_its_warning_window_then_due_then_overdue(tmp_path):
    p = _cfg(tmp_path)
    assert "ok" in remeasure.lines(date(2027, 8, 1), p)[0]
    soon = remeasure.lines(date(2027, 8, 20), p)
    assert "DUE SOON" in soon[0] and "run-it" in soon[1]
    assert "OVERDUE" in remeasure.lines(date(2027, 10, 1), p)[0]


def test_moving_last_done_past_the_due_date_clears_it(tmp_path):
    p = _cfg(tmp_path, last="2027-09-20")
    assert remeasure.lines(date(2027, 10, 1), p) == ["  ok       x                        due 2027-09-15  (a study)"]


def test_the_real_schedule_loads_and_every_command_names_a_module_that_exists():
    from src.common.paths import ROOT
    items, _ = remeasure.load()
    assert {i.id for i in items} >= {"insider_promoter_sell", "mf_holding_change"}
    for i in items:
        mod = i.command.split(" -m ")[1].split()[0]
        assert (ROOT / (mod.replace(".", "/") + ".py")).exists(), mod


def test_the_digest_carries_the_schedule():
    from src.monitor import digest
    assert "SCHEDULED" in digest.render()
