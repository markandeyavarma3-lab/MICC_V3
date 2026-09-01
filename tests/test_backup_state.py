"""The backup check, written because the backup itself was not the hard part.

`scripts/backup.sh` was committed on 2026-08-23, passed its own restore drill,
and wrote nothing for eight days: its default destination was a cloud mount
nobody had launched. Meanwhile `docs/STATUS.md` reported step 1.10 as BLOCKED
from a hand-written string that named the wrong obstacle.

Nothing in the repository was in a position to notice. These tests are what
notices.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from src.monitor import backup_state

pytestmark = pytest.mark.unit

STAMP = "20260901-070000"
TAKEN = datetime(2026, 9, 1, 7, 0, 0).astimezone().astimezone(UTC)


def _dest(tmp_path, monkeypatch, *, with_bundle=True):
    d = tmp_path / "backup"
    d.mkdir()
    if with_bundle:
        (d / f"repo-{STAMP}.bundle").write_bytes(b"not a real bundle")
    monkeypatch.setenv("BACKUP_DEST", str(d))
    return d


def _manifest(tmp_path, monkeypatch, rows):
    p = tmp_path / "manifest.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in rows))
    monkeypatch.setattr(backup_state, "MANIFEST", p)
    return p


def _rec(fetched: datetime, session="2026-09-01", status="STORED"):
    return {"source_id": "nse_bulk_deals", "session_date": session,
            "status": status, "fetched_at": fetched.isoformat()}


def test_backup_state_notices_a_session_outside_the_backup(tmp_path, monkeypatch):
    """THE CASE THAT MATTERS. A session archived after the last backup exists on
    exactly one disk, and the historical endpoint answers 503, so it cannot be
    re-fetched at any price. That must alert."""
    _dest(tmp_path, monkeypatch)
    _manifest(tmp_path, monkeypatch, [_rec(TAKEN + timedelta(hours=3))])

    s = backup_state.read()
    assert s.sessions_at_risk == 1, "a session fetched after the backup is not in it"
    assert s.alerting, "an irreplaceable session outside every backup must alert"


def test_a_session_already_inside_the_backup_does_not_alert(tmp_path, monkeypatch):
    _dest(tmp_path, monkeypatch)
    _manifest(tmp_path, monkeypatch, [_rec(TAKEN - timedelta(hours=3))])

    s = backup_state.read()
    assert s.sessions_at_risk == 0
    assert not s.alerting


def test_no_backup_at_all_alerts(tmp_path, monkeypatch):
    """The eight-day state. A destination that exists and holds nothing read as
    'fine' to every check in the repo until this one."""
    _dest(tmp_path, monkeypatch, with_bundle=False)
    _manifest(tmp_path, monkeypatch, [_rec(TAKEN - timedelta(days=30))])

    s = backup_state.read()
    assert s.bundle is None
    assert s.alerting, "no backup is the loudest case, not a quiet one"


def test_a_duplicate_fetch_puts_nothing_at_risk(tmp_path, monkeypatch):
    """DUPLICATE means the sha256 already matched something stored, so no new
    bytes exist. Counting it would alert three times a day, every day, and an
    alert that always fires is one nobody reads."""
    _dest(tmp_path, monkeypatch)
    _manifest(tmp_path, monkeypatch,
              [_rec(TAKEN + timedelta(hours=3), status="DUPLICATE")])
    assert backup_state.read().sessions_at_risk == 0


def test_an_empty_day_still_counts_as_bytes_worth_keeping(tmp_path, monkeypatch):
    """EMPTY_DAY is a real observation — the exchange published no deals — and
    losing it is indistinguishable from never having collected."""
    _dest(tmp_path, monkeypatch)
    _manifest(tmp_path, monkeypatch,
              [_rec(TAKEN + timedelta(hours=3), status="EMPTY_DAY")])
    assert backup_state.read().sessions_at_risk == 1


def test_destination_is_read_from_the_script_not_restated(monkeypatch):
    """The defect this module exists to prevent is the two disagreeing. If
    backup.sh's default moves and this does not follow, the check reports on a
    folder nothing writes to — which is precisely how 1.10 stayed wrong."""
    monkeypatch.delenv("BACKUP_DEST", raising=False)
    d = backup_state.destination()
    assert d is not None, "backup.sh's DEST default must be parseable"
    assert str(d).startswith("/"), f"unexpanded destination: {d}"
    assert "$" not in str(d), f"unexpanded variable in destination: {d}"


def test_backup_dest_env_overrides_exactly_as_the_script_does(tmp_path, monkeypatch):
    """An external SSD run must be visible to the check, or backing up to the
    SSD would report as 'no backup'."""
    monkeypatch.setenv("BACKUP_DEST", str(tmp_path))
    assert backup_state.destination() == tmp_path
