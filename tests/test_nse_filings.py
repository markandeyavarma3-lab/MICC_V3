"""NSE filing feeds (src/archive/nse_filings.py): windows, and the shape check
that keeps an un-warmed session's 200-with-junk out of the archive."""

from __future__ import annotations

import gzip
import json
from datetime import date

import pytest

from src.archive import nse_filings as N

pytestmark = pytest.mark.unit


def test_windows_cover_the_range_without_gaps_or_overlap():
    w = N.windows(date(2026, 1, 1), date(2026, 1, 20), 7)
    assert w[0][0] == date(2026, 1, 1) and w[-1][1] == date(2026, 1, 20)
    assert all((w[i + 1][0] - w[i][1]).days == 1 for i in range(len(w) - 1))


def test_a_valid_feed_is_archived_and_junk_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(N, "ARCHIVE", tmp_path)
    monkeypatch.setattr(N.ca, "_seen", lambda digest: None)
    bodies = iter([json.dumps([{"symbol": "ACME", "desc": "Credit Rating"}]).encode(), b"<html>nope</html>"])
    monkeypatch.setattr(N.ca, "_get", lambda op, url, ref: next(bodies))
    ok = N._store(None, "ANNOUNCE", "nse_announcements", "u", "r", "2026-10-01", {})
    bad = N._store(None, "ANNOUNCE", "nse_announcements", "u", "r", "2026-10-02", {})
    assert ok["status"] == "STORED" and ok["records"] == 1
    assert json.loads(gzip.decompress(open(ok["path"], "rb").read()))[0]["symbol"] == "ACME"
    assert bad["status"] == "FAILED" and "not JSON" in bad["error"]
    assert "session_date" not in ok                     # filings, not trading sessions
