"""Collection health, and the alert that did not exist when it was needed.

Two sessions went missing in two weeks. 19 August is gone forever. 28 August was
recovered two days late, by hand, after all three slots failed on DNS and the
collector correctly logged "may be permanently lost" and exited 1.

Detection was never the problem. Nothing carried it anywhere.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta

import pytest

from src.monitor import health

pytestmark = pytest.mark.unit


def _manifest(tmp_path, monkeypatch, rows):
    p = tmp_path / "manifest.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in rows))
    monkeypatch.setattr(health, "MANIFEST", p)
    return p


def _rec(source, session, status="STORED"):
    return {"source_id": source, "session_date": session, "status": status,
            "fetched_at": datetime.now(UTC).isoformat()}


def _days_ago(n: int) -> str:
    return (datetime.now(UTC).date() - timedelta(days=n)).isoformat()


def test_current_collection_does_not_alert(tmp_path, monkeypatch):
    _manifest(tmp_path, monkeypatch,
              [_rec(s, _days_ago(0)) for s in health.REQUIRED])
    assert not [r for r in health.read() if r.alerting]


def test_a_stale_required_source_alerts(tmp_path, monkeypatch):
    """THE CASE THAT FAILED TWICE. Both real losses would have tripped this on
    the following morning."""
    _manifest(tmp_path, monkeypatch,
              [_rec(s, _days_ago(10)) for s in health.REQUIRED])
    alerting = [r for r in health.read() if r.alerting]
    assert len(alerting) == len(health.REQUIRED)
    assert all(r.sessions_stale >= health.STALE_SESSIONS for r in alerting)


def test_a_weekend_is_not_a_missed_session(tmp_path, monkeypatch):
    """Staleness counts trading sessions, not days. Reporting Saturday as two
    days stale trains the reader to ignore the alert."""
    friday = datetime.now(UTC).date()
    while friday.weekday() != 4:
        friday -= timedelta(days=1)
    assert health._weekday_sessions_between(friday, friday + timedelta(days=2)) == 0, (
        "Saturday and Sunday are not missed sessions"
    )
    assert health._weekday_sessions_between(friday, friday + timedelta(days=3)) == 1


def test_an_optional_source_does_not_alert(tmp_path, monkeypatch):
    """sources.yml marks FII/DII optional. Alerting on it would dilute the
    signal for the two sources that actually matter."""
    rows = [_rec(s, _days_ago(0)) for s in health.REQUIRED]
    _manifest(tmp_path, monkeypatch, rows)  # fii_dii absent entirely
    alerting = [r for r in health.read() if r.alerting]
    assert not alerting


def test_a_never_collected_required_source_alerts(tmp_path, monkeypatch):
    _manifest(tmp_path, monkeypatch, [_rec("nse_bulk_deals", _days_ago(0))])
    alerting = [r.source_id for r in health.read() if r.alerting]
    assert "nse_block_deals" in alerting


def test_failed_fetches_do_not_count_as_collection(tmp_path, monkeypatch):
    """A FAILED poll is exactly the condition being alerted on. Counting it as a
    successful collection would silence the alarm it should raise."""
    _manifest(tmp_path, monkeypatch, [
        *[_rec(s, _days_ago(10)) for s in health.REQUIRED],
        {"source_id": "nse_bulk_deals", "status": "FAILED",
         "fetched_at": datetime.now(UTC).isoformat(), "session_date": None},
    ])
    assert [r for r in health.read() if r.alerting]


def test_email_never_raises_and_says_what_happened(monkeypatch):
    """An alert that crashes the collector is worse than no alert — it would
    turn a missed session into a missed session AND a broken run."""
    for k in ("ALERT_EMAIL_TO", "ALERT_EMAIL_FROM", "ALERT_EMAIL_PASSWORD",
              "ALERT_EMAIL_PASSWORD_FILE"):
        monkeypatch.delenv(k, raising=False)
    assert "not configured" in health.notify_email("s", "b")


def test_no_credential_is_stored_in_the_repository():
    """The repo has no backup and may become a public remote."""
    src = (health.__file__ and open(health.__file__).read()) or ""
    assert "ALERT_EMAIL_PASSWORD" in src, "the password must come from the environment"
    for marker in ("password =", "app_password", "smtp_password"):
        assert f'{marker} "' not in src.lower(), "a literal credential is present"


def test_the_local_channel_needs_no_network(monkeypatch):
    """The 28 August failure WAS a network failure. An alert that needs the
    network to report the network is down is not an alert."""
    src = (health.__file__ and open(health.__file__).read()) or ""
    body = src.split("def notify_desktop")[1].split("def notify_email")[0]
    assert "osascript" in body
    assert "smtp" not in body.lower() and "http" not in body.lower()


def test_a_hole_behind_the_latest_session_is_detected(tmp_path, monkeypatch):
    """THE DEFECT THIS CLOSES. read() kept only the LATEST session per source,
    so it could see that collection had STOPPED and could not see a hole behind
    it. 2026-08-19 and 2026-08-27 were both lost while HEALTH.md said "all
    sources current" — the alert was structurally incapable of the observation.
    """
    rows = []
    # the price collector's record of which days actually traded
    for d in ("2026-08-18", "2026-08-19", "2026-08-20"):
        rows.append({"source_id": "nse_bhavcopy", "session_date": d,
                     "status": "STORED",
                     "fetched_at": datetime.now(UTC).isoformat()})
    # a deal source that holds the outer two and not the middle
    for d in ("2026-08-18", "2026-08-20"):
        rows.append(_rec("nse_bulk_deals", d))
    _manifest(tmp_path, monkeypatch, rows)
    monkeypatch.setattr(health, "MANIFEST", tmp_path / "manifest.jsonl")

    monkeypatch.setattr(health, "acknowledged_gaps", dict)
    bulk = next(r for r in health.read() if r.source_id == "nse_bulk_deals")
    assert bulk.gaps == (date(2026, 8, 19),), f"gaps were {bulk.gaps}"
    # ASSERT ON open_gaps, NOT alerting. This fixture's last session is weeks
    # behind today, so `alerting` is True on staleness alone and would pass with
    # gap detection ripped out entirely. That is what it did when acknowledged
    # gaps landed on 2026-09-05: the test stayed green while proving nothing.
    assert bulk.open_gaps == (date(2026, 8, 19),)
    assert bulk.alerting, "a permanently lost session must alert"


def test_a_holiday_is_not_a_gap(tmp_path, monkeypatch):
    """A weekday calendar would count Diwali as missing and the alert would be
    muted within a week. The trading calendar comes from the price collector's
    own manifest: a day it recorded no bhavcopy for is a day NSE did not trade.
    """
    rows = [{"source_id": "nse_bhavcopy", "session_date": d, "status": "STORED",
             "fetched_at": datetime.now(UTC).isoformat()}
            for d in ("2026-08-18", "2026-08-20")]          # 08-19 did not trade
    rows += [_rec("nse_bulk_deals", d) for d in ("2026-08-18", "2026-08-20")]
    _manifest(tmp_path, monkeypatch, rows)
    monkeypatch.setattr(health, "MANIFEST", tmp_path / "manifest.jsonl")

    bulk = next(r for r in health.read() if r.source_id == "nse_bulk_deals")
    assert bulk.gaps == (), "a non-trading day was reported as a lost session"


def test_an_empty_day_answer_is_not_a_loss(tmp_path, monkeypatch):
    """We asked and the exchange said "NO RECORDS". That is a different fact
    from never asking, and only the second is a loss.

    An empty file carries no session date — there is no first data row to read
    one from — so it cannot go in `held`. Measured on the real archive: block
    deals on 2026-08-25 were flagged LOST until this was handled, and a false
    LOST trains the reader to ignore the alert.
    """
    rows = [{"source_id": "nse_bhavcopy", "session_date": d, "status": "STORED",
             "fetched_at": datetime.now(UTC).isoformat()}
            for d in ("2026-08-24", "2026-08-25", "2026-08-26")]
    rows += [_rec("nse_block_deals", d) for d in ("2026-08-24", "2026-08-26")]
    rows.append({"source_id": "nse_block_deals", "session_date": None,
                 "status": "EMPTY_DAY",
                 "fetched_at": "2026-08-25T14:00:00+00:00"})
    _manifest(tmp_path, monkeypatch, rows)
    monkeypatch.setattr(health, "MANIFEST", tmp_path / "manifest.jsonl")

    blk = next(r for r in health.read() if r.source_id == "nse_block_deals")
    assert blk.gaps == (), f"an answered empty day was reported lost: {blk.gaps}"


# --- the alert that could never be cleared -----------------------------------


def test_an_acknowledged_gap_stops_paging_but_stays_visible(tmp_path, monkeypatch):
    """WHY THIS EXISTS. Gap detection landed 2026-09-03 and immediately began
    alerting by email on 2026-08-19 and 2026-08-27 — three times a session,
    forever, for sessions nobody can ever recover because the historical
    endpoint answers 503. The terminal printed `STALE ... 0 session(s) stale`,
    a flag and a number describing two different conditions.

    This project lost 2026-08-19 because a signal reached nothing. A channel
    that is permanently red ends in the same place, by a different route.
    """
    # DATES NEAR TODAY, DELIBERATELY. With a fixture weeks in the past this
    # source is stale anyway, `alerting` is True for that reason alone, and the
    # assertion below would pass with the acknowledgement logic deleted. That is
    # how the first version of this test was written and it proved nothing.
    hole, before, after = _days_ago(3), _days_ago(4), _days_ago(2)
    rows = [{"source_id": "nse_bhavcopy", "session_date": d, "status": "STORED",
             "fetched_at": datetime.now(UTC).isoformat()}
            for d in (before, hole, after)]
    rows += [_rec("nse_bulk_deals", d) for d in (before, after)]
    _manifest(tmp_path, monkeypatch, rows)
    monkeypatch.setattr(health, "acknowledged_gaps",
                        lambda: {"nse_bulk_deals": (date.fromisoformat(hole),)})

    bulk = next(r for r in health.read() if r.source_id == "nse_bulk_deals")
    assert bulk.gaps == (date.fromisoformat(hole),), "the loss must remain recorded"
    assert bulk.open_gaps == (), "an acknowledged loss must not stay open"
    assert "acknowledged" in bulk.render(), "an acknowledged loss must stay visible"
    # THE ASSERTION THAT MATTERS: no email. Everything above can hold while the
    # thing still pages three times a session forever.
    assert not bulk.alerting, "an acknowledged, unrecoverable loss must not page"


def test_an_unacknowledged_gap_still_pages(tmp_path, monkeypatch):
    """The default is to alert. Acknowledging is a deliberate act with a date
    and a reason in sources.yml, not a threshold that decays on its own."""
    hole, before, after = _days_ago(3), _days_ago(4), _days_ago(2)
    rows = [{"source_id": "nse_bhavcopy", "session_date": d, "status": "STORED",
             "fetched_at": datetime.now(UTC).isoformat()}
            for d in (before, hole, after)]
    rows += [_rec("nse_bulk_deals", d) for d in (before, after)]
    _manifest(tmp_path, monkeypatch, rows)
    monkeypatch.setattr(health, "acknowledged_gaps", dict)

    bulk = next(r for r in health.read() if r.source_id == "nse_bulk_deals")
    # Same fixture, same recency: the ONLY difference from the test above is
    # whether the gap is written down. So `alerting` here isolates that.
    assert bulk.open_gaps == (date.fromisoformat(hole),)
    assert bulk.alerting


def test_every_acknowledged_gap_carries_a_reason_and_a_date():
    """A loss written down without a why is a loss nobody can re-examine."""
    import yaml

    from src.common.paths import CONFIGS

    spec = yaml.safe_load((CONFIGS / "sources.yml").read_text())
    entries = spec.get("acknowledged_gaps") or []
    assert entries, "the acknowledged-gap list vanished; every gap now pages"
    for e in entries:
        assert e.get("source_id") and e.get("session")
        assert e.get("acknowledged"), f"{e['source_id']} {e['session']}: no date"
        assert len(str(e.get("reason", ""))) > 40, (
            f"{e['source_id']} {e['session']} was acknowledged without a reason"
        )


def test_the_acknowledged_list_only_covers_gaps_that_are_real():
    """A stale acknowledgement silences a gap that has since been recovered, or
    one that never existed. Every entry must correspond to a gap health.read()
    actually observes."""
    observed = {r.source_id: set(r.gaps) for r in health.read()}
    for sid, dates in health.acknowledged_gaps().items():
        for d in dates:
            assert d in observed.get(sid, set()), (
                f"{sid} {d} is acknowledged but is not a gap — the entry is "
                f"stale and would silence a future loss on that session"
            )
