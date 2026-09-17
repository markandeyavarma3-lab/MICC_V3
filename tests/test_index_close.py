"""The all-index daily close archive: dated, backfillable to 2021-10-18."""

from __future__ import annotations

from datetime import date
from urllib.error import HTTPError

import pytest

from src.archive import index_close as ic

pytestmark = pytest.mark.unit


def test_the_declared_date_is_read_from_the_file_and_converted_to_iso():
    assert ic.declared_date(b"Index Name,Index Date,Close\nNifty 50,10-09-2026,1\n") == "2026-09-10"
    assert ic.declared_date(b"garbage") is None
    assert ic.declared_date(b"Index Name,Close\nNifty 50,1\n") is None


def test_nothing_before_the_measured_edge_is_ever_asked_for(monkeypatch):
    """2021-10-15 answers 404, 2021-10-18 answers 200 (bisected 2026-09-18).
    A collector that hammers a known-absent range is indistinguishable from a
    broken one in the logs."""
    monkeypatch.setattr(ic, "settled_sessions", lambda: set())
    got = ic.missing(date(2021, 9, 1), date(2021, 10, 22))
    assert got[0] == date(2021, 10, 18)
    assert all(d.weekday() < 5 for d in got)


def _http404(url):
    raise HTTPError(url, 404, "Not Found", {}, None)


def test_a_404_on_a_past_weekday_is_a_holiday_and_a_404_on_today_is_pending(monkeypatch):
    monkeypatch.setattr(ic, "_fetch", _http404)
    past = ic.capture(date(2026, 9, 14), today=date(2026, 9, 18))
    today = ic.capture(date(2026, 9, 18), today=date(2026, 9, 18))
    assert past["status"] == "NO_SESSION"
    assert today["status"] == "PENDING"


def test_a_file_declaring_a_different_date_than_requested_is_refused(monkeypatch, tmp_path):
    monkeypatch.setattr(ic, "ARCHIVE", tmp_path)
    monkeypatch.setattr(ic, "_manifest_rows", lambda: [])
    monkeypatch.setattr(ic, "_fetch", lambda url: b"Index Name,Index Date,Close\nNifty 50,10-09-2026,1\n")
    e = ic.capture(date(2026, 9, 11), today=date(2026, 9, 18))
    assert e["status"] == "FAILED" and "served Index Date 2026-09-10" in e["error"]
    assert not list(tmp_path.rglob("*.gz"))


def test_a_matching_file_is_stored_under_its_session_and_hashed(monkeypatch, tmp_path):
    monkeypatch.setattr(ic, "ARCHIVE", tmp_path)
    monkeypatch.setattr(ic, "_manifest_rows", lambda: [])
    body = b"Index Name,Index Date,Close\nNifty 50,11-09-2026,1\n"
    monkeypatch.setattr(ic, "_fetch", lambda url: body)
    e = ic.capture(date(2026, 9, 11), today=date(2026, 9, 18))
    assert e["status"] == "STORED" and e["session_date"] == "2026-09-11"
    assert (tmp_path / "INDEX_CLOSE" / "NSE" / "year=2026" / "month=09").exists()
    monkeypatch.setattr(ic, "_manifest_rows", lambda: [{"sha256": e["sha256"], "status": "STORED", "path": e["path"]}])
    assert ic.capture(date(2026, 9, 11), today=date(2026, 9, 18))["status"] == "DUPLICATE"
