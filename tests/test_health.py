"""Collection health, and the alert that did not exist when it was needed.

Two sessions went missing in two weeks. 19 August is gone forever. 28 August was
recovered two days late, by hand, after all three slots failed on DNS and the
collector correctly logged "may be permanently lost" and exited 1.

Detection was never the problem. Nothing carried it anywhere.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

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
