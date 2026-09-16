"""An empty block-deals day is a dated fact, every day it happens.

THE DEFECT (decision 0066). NSE serves `NO RECORDS` for block.csv on a day
with no block deals — identical bytes, no date. `stopgap.capture` deduped on
sha256 before it classified, so only the FIRST empty day ever became an
EMPTY_DAY row; every later one was DUPLICATE with session=None.
`health.read()` credits an empty answer only from an EMPTY_DAY row, so
2026-09-08, 09, 10 and 15 — days with no block deals at all — read as
MISSING and the feed as STALE since 09-11. A false alarm that grew by one
session per quiet day.

Fetching is stubbed: nothing here touches NSE.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from src.archive import stopgap

pytestmark = pytest.mark.unit

SENTINEL = (b"Date,Symbol,Security Name,Client Name,Buy/Sell,Quantity Traded,"
            b"Trade Price / Wght. Avg. Price\nNO RECORDS,,,,,,\n")
BULK = (b"Date,Symbol,Security Name,Client Name,Buy/Sell,Quantity Traded,"
        b"Trade Price / Wght. Avg. Price,Remarks\n"
        b"15-SEP-2026,AAA,AAA Ltd,SOME FUND,BUY,1000,10.00,-\n")


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """Archive + manifest under tmp; _fetch answers from a dict by url."""
    arch = tmp_path / "archive"
    monkeypatch.setattr(stopgap, "ARCHIVE", arch)
    monkeypatch.setattr(stopgap, "MANIFEST", arch / "manifest.jsonl")
    answers: dict[str, bytes] = {}
    monkeypatch.setattr(stopgap, "_fetch", lambda url, referer=None: answers[url])
    monkeypatch.setattr(stopgap.time, "sleep", lambda s: None)
    return arch, answers


def _manifest(arch: Path) -> list[dict]:
    p = arch / "manifest.jsonl"
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()] if p.exists() else []


def test_an_empty_day_is_dated_from_the_hint_and_stored(sandbox):
    arch, answers = sandbox
    block = stopgap.feed_by_id("nse_block_deals") if hasattr(stopgap, "feed_by_id") else \
        next(s for s in stopgap.SOURCES if s.id == "nse_block_deals")
    answers[block.url] = SENTINEL
    e = stopgap.capture(block, session_hint="2026-09-15")
    assert e["status"] == "EMPTY_DAY"
    assert e["session_date"] == "2026-09-15"
    assert e["rows"] == 0
    assert Path(e["path"]).exists()


def test_the_second_empty_day_is_still_a_dated_empty_day_not_a_duplicate(sandbox):
    """Same bytes, a later session. The file need not be written twice; the
    manifest row must say EMPTY_DAY for the new session."""
    arch, answers = sandbox
    block = next(s for s in stopgap.SOURCES if s.id == "nse_block_deals")
    answers[block.url] = SENTINEL
    first = stopgap.capture(block, session_hint="2026-09-15")
    stopgap.record(first)
    second = stopgap.capture(block, session_hint="2026-09-16")
    assert second["status"] == "EMPTY_DAY", second
    assert second["session_date"] == "2026-09-16"
    assert second["path"] == first["path"], "bytes are written once; the row is what is dated"
    assert len(list(arch.glob("BLOCK/**/*.csv.gz"))) == 1


def test_a_dated_file_served_twice_is_still_a_duplicate(sandbox):
    """The dedupe rule is unchanged for real files: a stale re-serve of
    Friday's bulk.csv on Saturday must not become a second Friday."""
    arch, answers = sandbox
    bulk = next(s for s in stopgap.SOURCES if s.id == "nse_bulk_deals")
    answers[bulk.url] = BULK
    a = stopgap.capture(bulk)
    stopgap.record(a)
    b = stopgap.capture(bulk)
    assert a["status"] == "STORED" and b["status"] == "DUPLICATE"
    assert a["session_date"] == b["session_date"] == "2026-09-15"


def test_without_a_hint_the_empty_day_stays_undated_rather_than_guessing(sandbox):
    """No dated sibling in the run (bulk failed): the row is EMPTY_DAY with no
    session. health.py's fetch-date heuristic covers it; a guessed date would
    survive into the warehouse looking like fact."""
    arch, answers = sandbox
    block = next(s for s in stopgap.SOURCES if s.id == "nse_block_deals")
    answers[block.url] = SENTINEL
    e = stopgap.capture(block)
    assert e["status"] == "EMPTY_DAY" and e["session_date"] is None


def test_main_passes_the_bulk_session_to_the_undated_sources(sandbox, monkeypatch, capsys):
    """The plumbing: bulk resolves 15-SEP-2026, block's sentinel is credited
    to it, in one run, through main()."""
    arch, answers = sandbox
    for s in stopgap.SOURCES:
        answers[s.url] = BULK if s.id == "nse_bulk_deals" else SENTINEL if s.id == "nse_block_deals" else b"[]"
    answers["https://www.nseindia.com/"] = b"<html>"
    rc = stopgap.main()
    rows = {r["source_id"]: r for r in _manifest(arch)}
    assert rows["nse_bulk_deals"]["status"] == "STORED"
    assert rows["nse_block_deals"]["status"] == "EMPTY_DAY"
    assert rows["nse_block_deals"]["session_date"] == "2026-09-15"
    assert rc == 0


def test_health_credits_a_dated_empty_day_as_held():
    """The consumer side of the contract, pinned on the source: health.read()
    puts any STORED / DUPLICATE / EMPTY_DAY row WITH a session_date into `held`
    and `latest`, so a dated EMPTY_DAY advances the feed's last session."""
    import inspect

    from src.monitor import health

    src = inspect.getsource(health.read)
    assert '{"STORED", "DUPLICATE", "EMPTY_DAY"}' in src
    assert "held.setdefault(sid, set()).add(d)" in src
