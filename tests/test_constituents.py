"""Index constituents: six daily snapshots whose history starts the day archiving does."""

from __future__ import annotations

from datetime import date

import pytest

from src.archive import constituents as cs

pytestmark = pytest.mark.unit

CSV = b"Company Name,Industry,Symbol,Series,ISIN Code\nReliance,Oil,RELIANCE,EQ,INE002A01018\nTCS,IT,TCS,EQ,INE467B01029\n"
# Multi-line on purpose: the real niftyindices error page is 415 lines, so a
# row count alone would read it as a 414-row constituents list.
HTML = b"<!DOCTYPE html>\n<html>\n<head>\n<title>Error 404</title>\n</head>\n<body>\nError 404\n</body>\n</html>\n"


def test_an_html_error_page_served_as_200_is_refused_not_archived(tmp_path, monkeypatch):
    """niftyindices.com answers 200 with a 78,919-byte HTML error for every
    date that does not exist. A collector that archives it has archived a
    lie with a valid sha256."""
    monkeypatch.setattr(cs, "ARCHIVE", tmp_path)
    monkeypatch.setattr(cs, "_manifest_rows", lambda: [])
    monkeypatch.setattr(cs, "_fetch", lambda url: HTML)
    e = cs.capture("nifty50_constituents", "ind_nifty50list.csv", today=date(2026, 9, 18))
    assert e["status"] == "FAILED" and "header mismatch" in e["error"]
    assert not list(tmp_path.rglob("*.gz"))


def test_a_real_list_is_stored_with_its_row_count(tmp_path, monkeypatch):
    monkeypatch.setattr(cs, "ARCHIVE", tmp_path)
    monkeypatch.setattr(cs, "_manifest_rows", lambda: [])
    monkeypatch.setattr(cs, "_fetch", lambda url: CSV)
    e = cs.capture("nifty50_constituents", "ind_nifty50list.csv", today=date(2026, 9, 18))
    assert e["status"] == "STORED" and e["rows"] == 2
    assert (tmp_path / "INDEX_CONSTITUENTS" / "NSE" / "year=2026" / "month=09").exists()


def test_an_unchanged_list_is_a_duplicate_so_the_archive_is_the_change_log(tmp_path, monkeypatch):
    """On an ordinary day all six are DUPLICATE; on a rebalance day the changed
    list is STORED. The archive holds one file per change, not one per day."""
    from src.common.hashing import hash_bytes
    monkeypatch.setattr(cs, "ARCHIVE", tmp_path)
    monkeypatch.setattr(cs, "_fetch", lambda url: CSV)
    monkeypatch.setattr(cs, "_manifest_rows", lambda: [
        {"source_id": "nifty50_constituents", "sha256": hash_bytes(CSV), "status": "STORED", "path": "x"}])
    e = cs.capture("nifty50_constituents", "ind_nifty50list.csv", today=date(2026, 9, 18))
    assert e["status"] == "DUPLICATE"
    assert not list(tmp_path.rglob("*.gz"))


def test_the_same_bytes_under_a_different_index_id_are_not_a_duplicate(tmp_path, monkeypatch):
    """Dedupe is per series. Two indices with identical membership (it happens
    with thematic lists) must each keep their own record."""
    from src.common.hashing import hash_bytes
    monkeypatch.setattr(cs, "ARCHIVE", tmp_path)
    monkeypatch.setattr(cs, "_fetch", lambda url: CSV)
    monkeypatch.setattr(cs, "_manifest_rows", lambda: [
        {"source_id": "niftynext50_constituents", "sha256": hash_bytes(CSV), "status": "STORED", "path": "x"}])
    e = cs.capture("nifty50_constituents", "ind_nifty50list.csv", today=date(2026, 9, 18))
    assert e["status"] == "STORED"


def test_the_six_lists_are_the_size_buckets_and_the_500():
    ids = [s for s, _ in cs.LISTS]
    assert "nifty500_constituents" in ids  # the 2026-09-15 proof's id, kept
    assert len(ids) == len(set(ids)) == 6
