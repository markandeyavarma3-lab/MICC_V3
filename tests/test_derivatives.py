"""The derivatives collectors, fired by decision 0058.

Written BEFORE src/archive/derivatives.py exists and watched failing, which is
the pattern decision 0055 named after char_panel: a feed whose staleness nothing
reports will rot without anyone noticing, so the alert is part of the build
rather than a follow-up.
"""

from __future__ import annotations

from datetime import date

import pytest

pytestmark = pytest.mark.unit


def test_the_module_exposes_both_feeds():
    from src.archive import derivatives

    ids = {f.source_id for f in derivatives.FEEDS}
    assert ids == {"nse_participant_oi", "nse_fo_bhavcopy"}


def test_every_feed_declares_its_route_and_report_type():
    from src.archive import derivatives

    for f in derivatives.FEEDS:
        assert f.url_template.startswith("https://nsearchives.nseindia.com/")
        assert "{" in f.url_template, "the date must be templated into the URL"
        assert f.report_type in {"PARTICIPANT_OI", "FO"}


def test_archive_path_follows_the_layout_sources_yml_declares():
    """`raw/archive/{report_type}/{exchange}/year=/month=/` — the same layout as
    every other collector, so the backup and status globs keep working."""
    from src.archive import derivatives

    f = derivatives.feed("nse_participant_oi")
    p = derivatives.archive_path(f, date(2026, 9, 10), "abcdef0123456789")
    parts = p.parts
    assert "PARTICIPANT_OI" in parts and "NSE" in parts
    assert "year=2026" in parts and "month=09" in parts
    assert p.name.endswith(".gz"), "every archived file in this project is .gz"


def test_weekends_are_never_probed():
    from src.archive import derivatives

    f = derivatives.feed("nse_fo_bhavcopy")
    # 2026-09-12 is a Saturday, 2026-09-13 a Sunday
    got = derivatives.missing(f, date(2026, 9, 11), date(2026, 9, 14), settled=set())
    assert date(2026, 9, 12) not in got
    assert date(2026, 9, 13) not in got
    assert date(2026, 9, 11) in got


def test_a_settled_session_is_never_asked_for_again():
    from src.archive import derivatives

    f = derivatives.feed("nse_fo_bhavcopy")
    got = derivatives.missing(f, date(2026, 9, 9), date(2026, 9, 11),
                              settled={"2026-09-10"})
    assert date(2026, 9, 10) not in got
    assert date(2026, 9, 9) in got


def test_the_staleness_alert_fires_when_a_feed_stops_moving():
    """THE POINT OF BUILDING THIS TODAY.

    participant_oi sat 77 days stale and fno_spine 27 days, and nothing said so
    — they were PARKED behind a trigger, which was honest, but once collection
    resumes silence becomes the char_panel failure instead. A feed that is
    supposed to move must report when it stops.
    """
    from src.archive import derivatives

    f = derivatives.feed("nse_participant_oi")
    fresh = derivatives.staleness(f, last=date(2026, 9, 10), today=date(2026, 9, 11))
    stale = derivatives.staleness(f, last=date(2026, 6, 25), today=date(2026, 9, 11))
    assert not fresh.alerting
    assert stale.alerting
    assert stale.sessions_stale > 50
    assert "nse_participant_oi" in stale.render()


def test_a_feed_that_has_never_run_alerts_rather_than_reporting_zero():
    from src.archive import derivatives

    f = derivatives.feed("nse_fo_bhavcopy")
    never = derivatives.staleness(f, last=None, today=date(2026, 9, 11))
    assert never.alerting
    assert "never" in never.render().lower()


@pytest.mark.needs_data
def test_the_trigger_is_recorded_as_fired_rather_than_quietly_dropped():
    """A parked feed that starts collecting without the trigger being marked is
    a decision that left no trace. `sources.yml` must show FIRED with a
    rationale, and the PARKED entry in the inventory must be gone."""
    import yaml

    from src.common.paths import CONFIGS
    from src.monitor import inventory

    spec = yaml.safe_load((CONFIGS / "sources.yml").read_text())
    entry = next(d for d in spec["deferred"]
                 if d["id"] == "fno_institutional_positioning")
    assert entry.get("status") == "FIRED"
    assert len(entry.get("fired_rationale", "")) > 150
    assert "participant_oi" not in inventory.PARKED, (
        "participant_oi is collecting again; leaving it PARKED hides its staleness"
    )


@pytest.mark.needs_data
def test_both_feeds_are_monitored_for_staleness():
    """The alert is the point. A collecting feed that rots silently is the
    char_panel failure, which is what firing this trigger must not reintroduce."""
    from src.monitor import health

    assert "nse_participant_oi" in health.REQUIRED
    assert "nse_fo_bhavcopy" in health.REQUIRED


@pytest.mark.needs_data
def test_the_collector_runs_the_derivatives_stage():
    from src.common.paths import ROOT

    sh = (ROOT / "scripts" / "collect_daily.sh").read_text()
    assert "src.archive.derivatives" in sh
    assert 'note "derivatives"' in sh
