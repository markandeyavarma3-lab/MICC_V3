"""Stage failures must page, not just be logged. Decision 0070.

`health.py` watches whether DATA is stale. Nothing watched whether a STAGE ran.
`charmatch` failed on every scheduled run from 2026-09-11 to 2026-09-16 — twenty
consecutive failures — and the only signal was the line "one or more stages
FAILED" in a file nobody opens. The mart's foreign-key failure before it ran for
five days the same way.

Both were loud in the log and silent everywhere a person would look. These tests
are written before the alert exists.
"""

from __future__ import annotations

import pytest

from src.common.paths import ROOT

pytestmark = pytest.mark.unit

SH = ROOT / "scripts" / "collect_daily.sh"


def test_note_records_which_stage_failed_not_just_that_one_did():
    """`RC=1` says something broke. It does not say charpanel broke, which is
    the only part a person can act on."""
    s = SH.read_text()
    assert "FAILED_STAGES" in s, "the script does not accumulate failed stage names"


def test_a_failed_stage_reaches_the_alert_channels():
    """The same channels health.py already uses. A new notification path would
    be a second thing to configure and a second thing to go quietly missing."""
    s = SH.read_text()
    assert "src.monitor.stage_alert" in s, "failed stages are not routed to an alerter"


def test_the_alert_names_the_stages_and_the_log_line():
    from src.monitor import stage_alert

    msg = stage_alert.compose(["charpanel", "mart"], log="logs/collect_2026-09.log")
    assert "charpanel" in msg and "mart" in msg
    assert "collect_2026-09.log" in msg


def test_a_clean_run_sends_nothing():
    """An alert that fires on success is an alert that gets filtered."""
    from src.monitor import stage_alert

    assert stage_alert.compose([], log="x.log") == ""


def test_the_alerter_never_raises(monkeypatch):
    """It runs as the last act of a collector that has already failed. An
    exception here would replace a useful message with a stack trace."""
    from src.monitor import stage_alert

    def boom(*a, **k):
        raise RuntimeError("smtp down")

    monkeypatch.setattr(stage_alert.health, "notify_email", boom)
    monkeypatch.setattr(stage_alert.health, "notify_desktop", boom)
    assert stage_alert.send(["charpanel"], log="x.log") is not None


# --- the digest ---------------------------------------------------------------


@pytest.mark.needs_data
def test_the_digest_answers_the_question_a_person_actually_asks():
    """HEALTH.md, STATUS.md and DATA_INVENTORY.md each answer a question
    correctly and none answers "did last night work". The digest does."""
    from src.monitor import digest

    t = digest.render()
    for section in ("LAST RUNS", "FEEDS", "STALENESS", "WHERE TO LOOK"):
        assert section in t, f"digest lost its {section} section"


@pytest.mark.needs_data
def test_the_digest_reports_stage_failures_not_only_data_staleness():
    """The gap this closes. A run where every feed is current but charpanel
    died must NOT read as a good night."""
    from src.monitor import digest

    runs = digest._runs()
    assert runs, "no runs parsed from the collector log"
    assert any(failed for _stamp, failed in runs), (
        "September's charpanel failures are in the log; the parser sees none"
    )


@pytest.mark.needs_data
def test_the_digest_does_not_emit_markdown_into_a_terminal():
    """`health.SourceHealth.render()` returns a MARKDOWN TABLE ROW, shaped for
    HEALTH.md. Reusing it here printed `| \\`nse_bulk_deals\\` | ... |` to the
    screen. A digest is read in a terminal."""
    from src.monitor import digest

    stale = digest.render().split("STALENESS")[1].split("WHERE TO LOOK")[0]
    assert "|" not in stale, "the staleness section is emitting table rows again"


@pytest.mark.needs_data
def test_a_stage_reported_twice_in_one_run_counts_once():
    from src.monitor import digest

    for _stamp, failed in digest._runs():
        assert len(failed) == len(set(failed)), f"duplicated stage names: {failed}"
