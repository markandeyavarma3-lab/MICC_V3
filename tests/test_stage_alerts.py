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
from src.monitor import stage_alert

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


# --- the collection branch, which had no test until it paged for nothing ------


def _exposure(monkeypatch, at_risk: bool):
    from src.monitor import health
    why = ("newest held 2026-09-15; the endpoint is serving 2026-09-16, which is NOT held — Fetch now"
           if at_risk else
           "newest held 2026-09-16 is what the endpoint is serving; nothing at risk, the next slot retries")
    monkeypatch.setattr(health, "rolling_exposure",
                        lambda rows=None: [(s, at_risk, why) for s in health.ROLLING])


def test_a_failed_deal_fetch_of_a_session_already_held_does_not_say_re_run(monkeypatch):
    """2026-09-17 08:37: DNS failed, the endpoint was serving 09-16, 09-16 was
    held. The alert said "recoverable only until the file turns over ... Re-run
    now". Nothing was at risk. The message must say so, per source."""
    _exposure(monkeypatch, at_risk=False)
    msg = stage_alert.compose(["deals"], log="x.log")
    assert "COLLECTION: deals" in msg
    assert "nothing at risk" in msg
    assert "Nothing on the endpoint is missing" in msg
    assert "Re-run now" not in msg and "turns over" not in msg


def test_a_failed_deal_fetch_of_a_session_not_held_says_re_run(monkeypatch):
    """The morning after a fully missed evening — the case the boilerplate was
    written for, now stated with the actual session and where it is."""
    _exposure(monkeypatch, at_risk=True)
    msg = stage_alert.compose(["deals"], log="x.log")
    assert "AT RISK" in msg and "2026-09-16" in msg and "NOT held" in msg
    assert "Re-run now" in msg and "/collect" in msg


def test_a_failed_dated_feed_is_not_treated_as_a_rolling_loss(monkeypatch):
    """prices/bhavcopy/insider can be re-fetched for any past date. They must
    not inherit the rolling feeds' urgency."""
    _exposure(monkeypatch, at_risk=True)  # would be alarming if consulted
    msg = stage_alert.compose(["prices"], log="x.log")
    assert "COLLECTION: prices" in msg
    assert "dated feeds" in msg and "re-fetchable" in msg
    assert "AT RISK" not in msg and "Re-run now" not in msg


def test_the_alert_still_goes_out_if_the_exposure_lookup_dies(monkeypatch):
    """The lookup reads the manifest. A broken manifest must not turn a stage
    alert into no alert."""
    from src.monitor import health

    def boom(rows=None):
        raise RuntimeError("manifest unreadable")

    monkeypatch.setattr(health, "rolling_exposure", boom)
    msg = stage_alert.compose(["deals"], log="x.log")
    assert "COLLECTION: deals" in msg
    assert "exposure unavailable: RuntimeError" in msg


def test_the_digest_is_sent_after_the_backup_not_before():
    """It ran first, so every digest reported the backup as it stood BEFORE
    this run's backup: "AT RISK, 1 archived session not in it" on any day the
    run collected anything — the owner pasted exactly that on 2026-09-25."""
    s = (ROOT / "scripts" / "collect_daily.sh").read_text()
    assert s.index('"$REPO/scripts/backup.sh"') < s.index("-m src.monitor.digest"), (
        "the digest reports on the backup, so it must run after it"
    )


def test_feeds_ignore_sources_whose_session_date_is_not_a_session(tmp_path, monkeypatch):
    """An SHP XBRL row's session_date is the filing's QUARTER-END. Counted as a
    session it read "1 session, newest 2026-09-23" in the week thousands of
    files were fetched."""
    import json
    from datetime import UTC, datetime
    from src.monitor import digest
    today = datetime.now(UTC).date().isoformat()
    (tmp_path / "manifest.jsonl").write_text("\n".join(json.dumps(r) for r in [
        {"source_id": "nse_bulk_deals", "status": "STORED", "session_date": today},
        {"source_id": "nse_shp_xbrl", "status": "STORED", "session_date": today},
    ]))
    monkeypatch.setattr(digest, "ARCHIVE", tmp_path)
    held = digest._sessions_held()
    assert "nse_bulk_deals" in held and "nse_shp_xbrl" not in held
