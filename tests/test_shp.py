"""The shareholding-pattern sweep: what it archives, what it refuses to trust.

The bytes are collected before any registration because the endpoint's
five-year floor may be a rolling window — the insider endpoint's was, and the
months before it were gone by the time anyone looked. Nothing here parses a
holding; that is a research decision, taken elsewhere.
"""

from __future__ import annotations

import gzip
import io
import json
import zipfile
from datetime import UTC, datetime, timedelta

import pytest

from src.archive import shp

pytestmark = pytest.mark.unit


# --- the universe -------------------------------------------------------------


def _bhavcopy(tmp_path, monkeypatch, rows):
    hdr = "TradDt,TckrSymb,SctySrs,ClsPric"
    body = "\n".join([hdr, *rows]).encode()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("BhavCopy_NSE_CM_0_0_0_20260916_F_0000.csv", body)
    d = tmp_path / "PRICE" / "NSE" / "year=2026" / "month=09"
    d.mkdir(parents=True)
    with gzip.open(d / "PRICE_NSE_20260916_abc.csv.zip.gz", "wb") as fh:
        fh.write(buf.getvalue())
    monkeypatch.setattr(shp, "ARCHIVE", tmp_path)


def test_the_universe_is_main_board_equities_from_the_newest_bhavcopy(tmp_path, monkeypatch):
    """The exchange's own daily list, not a hand-kept one. SME (SM) and bonds
    (GB/GS) file under other regimes and are excluded on purpose."""
    _bhavcopy(tmp_path, monkeypatch, [
        "2026-09-16,RELIANCE,EQ,1", "2026-09-16,SOMEBE,BE,1",
        "2026-09-16,SMECO,SM,1", "2026-09-16,SGBJUN28,GB,1", "2026-09-16,RELIANCE,EQ,1",
    ])
    assert shp.universe() == ["RELIANCE", "SOMEBE"]


def test_no_bhavcopy_is_a_loud_error_not_an_empty_sweep(tmp_path, monkeypatch):
    """An empty universe would sweep nothing and report a clean run."""
    monkeypatch.setattr(shp, "ARCHIVE", tmp_path)
    with pytest.raises(RuntimeError, match="no archived bhavcopy"):
        shp.universe()


# --- the master's quarter field ------------------------------------------------


def test_quarter_end_parses_the_masters_date_format():
    from datetime import date
    assert shp._quarter_end({"date": "30-Jun-2026"}) == date(2026, 6, 30)
    assert shp._quarter_end({"date": "30-JUN-2026"}) == date(2026, 6, 30)
    assert shp._quarter_end({"date": "garbage"}) is None
    assert shp._quarter_end({}) is None


# --- one symbol ---------------------------------------------------------------


def _fake_get(responses: dict[str, bytes | Exception]):
    def get(op, url, referer):
        for key, v in responses.items():
            if key in url:
                if isinstance(v, Exception):
                    raise v
                return v
        raise AssertionError(f"unexpected url {url}")
    return get


def _master(n=2, xbrl=True):
    rows = [{"date": f"{30 if i % 2 == 0 else 31}-{'Jun' if i % 2 == 0 else 'Mar'}-202{6 - i // 2}",
             "recordId": 1000 + i,
             "xbrl": f"https://nsearchives.nseindia.com/corporate/xbrl/SHP_{i}_WEB.xml" if xbrl else ""}
            for i in range(n)]
    return json.dumps({"data": rows}).encode()


def test_an_empty_master_is_empty_not_failed(tmp_path, monkeypatch):
    """A new listing genuinely has no filings. FAILED would drown the manifest."""
    monkeypatch.setattr(shp, "ARCHIVE", tmp_path)
    monkeypatch.setattr(shp, "MANIFEST", tmp_path / "m.jsonl")
    monkeypatch.setattr(shp, "_get", _fake_get({"share-holdings-master": b'{"data": []}'}))
    e = shp.capture_symbol(None, "NEWCO", set(), [10])
    assert e["status"] == "EMPTY" and e["filings"] == 0


def test_a_master_and_its_xbrl_are_stored_and_recorded_with_symbol_and_quarter(tmp_path, monkeypatch):
    monkeypatch.setattr(shp, "ARCHIVE", tmp_path)
    monkeypatch.setattr(shp, "MANIFEST", tmp_path / "m.jsonl")
    monkeypatch.setattr(shp, "RATE_LIMIT", 0)
    monkeypatch.setattr(shp, "_get", _fake_get({
        "share-holdings-master": _master(2),
        "SHP_0_WEB": b"<xbrl>in-bse-shp:NameOfTheShareholder A</xbrl>",
        "SHP_1_WEB": b"<xbrl>in-bse-shp:NameOfTheShareholder B</xbrl>",
    }))
    seen: set[str] = set()
    e = shp.capture_symbol(None, "ACME", seen, [10])
    assert e["status"] == "STORED" and e["filings"] == 2 and e["details_stored"] == 2
    assert e["quarter_first"] == "2026-03-31" and e["quarter_last"] == "2026-06-30"
    xrows = [json.loads(l) for l in (tmp_path / "m.jsonl").read_text().splitlines()]
    assert {r["source_id"] for r in xrows} == {shp.XBRL_SOURCE}
    assert {r["symbol"] for r in xrows} == {"ACME"}
    assert sorted(r["session_date"] for r in xrows) == ["2026-03-31", "2026-06-30"]
    assert all((tmp_path / "SHP_XBRL" / "NSE").rglob("*.xml.gz"))


def test_the_xbrl_budget_stops_detail_but_not_the_master(tmp_path, monkeypatch):
    """~60,000 files behind the first sweep. The master must still land so the
    index of every symbol exists after one run; detail resumes next run."""
    monkeypatch.setattr(shp, "ARCHIVE", tmp_path)
    monkeypatch.setattr(shp, "MANIFEST", tmp_path / "m.jsonl")
    monkeypatch.setattr(shp, "RATE_LIMIT", 0)
    monkeypatch.setattr(shp, "_get", _fake_get({
        "share-holdings-master": _master(3),
        "SHP_0_WEB": b"<x>0</x>", "SHP_1_WEB": b"<x>1</x>", "SHP_2_WEB": b"<x>2</x>"}))
    budget = [1]
    e = shp.capture_symbol(None, "ACME", set(), budget)
    assert e["status"] == "STORED" and e["details_stored"] == 1 and budget[0] == 0


def test_every_xbrl_failing_fails_the_symbol_even_though_the_master_succeeded(tmp_path, monkeypatch):
    """The green-but-empty failure from insider.py's own history: an index that
    succeeds while the detail host refuses everything must not read as healthy."""
    monkeypatch.setattr(shp, "ARCHIVE", tmp_path)
    monkeypatch.setattr(shp, "MANIFEST", tmp_path / "m.jsonl")
    monkeypatch.setattr(shp, "RATE_LIMIT", 0)
    monkeypatch.setattr(shp, "_get", _fake_get({
        "share-holdings-master": _master(2),
        "SHP_0_WEB": RuntimeError("403"), "SHP_1_WEB": RuntimeError("403")}))
    e = shp.capture_symbol(None, "ACME", set(), [10])
    assert e["status"] == "FAILED" and "ALL 2 XBRL" in e["error"]
    failed = [json.loads(l) for l in (tmp_path / "m.jsonl").read_text().splitlines()]
    assert len(failed) == 2 and all(r["status"] == "FAILED" for r in failed)


def test_a_previously_seen_digest_is_a_duplicate_and_is_not_rewritten(tmp_path, monkeypatch):
    monkeypatch.setattr(shp, "ARCHIVE", tmp_path)
    monkeypatch.setattr(shp, "MANIFEST", tmp_path / "m.jsonl")
    monkeypatch.setattr(shp, "RATE_LIMIT", 0)
    body = _master(1, xbrl=False)
    monkeypatch.setattr(shp, "_get", _fake_get({"share-holdings-master": body}))
    from src.common.hashing import hash_bytes
    e = shp.capture_symbol(None, "ACME", {hash_bytes(body)}, [10])
    assert e["status"] == "DUPLICATE"
    assert not list((tmp_path / "SHP").rglob("*.gz"))


# --- the run --------------------------------------------------------------------


def test_a_mostly_empty_run_is_a_retired_endpoint_and_fails(tmp_path, monkeypatch, capsys):
    """/api/corporates-pit answered 200 with [] for two months. 1,500 companies
    do not stop filing at once; the endpoint did."""
    monkeypatch.setattr(shp, "ARCHIVE", tmp_path)
    monkeypatch.setattr(shp, "MANIFEST", tmp_path / "m.jsonl")
    monkeypatch.setattr(shp, "RATE_LIMIT", 0)
    monkeypatch.setattr(shp, "_opener", lambda: None)
    monkeypatch.setattr(shp, "_get", lambda op, url, ref: b'{"data": []}')
    out = shp.collect(["A", "B", "C", "D"], max_detail=0)
    assert all(o.status == "EMPTY" for o in out)
    rows = [json.loads(l) for l in (tmp_path / "m.jsonl").read_text().splitlines()]
    assert rows[-1]["status"] == "FAILED" and "retired endpoint" in rows[-1]["error"]
    assert "RUN FAILED" in capsys.readouterr().out


def test_a_few_empties_in_a_healthy_run_do_not_fail_it(tmp_path, monkeypatch):
    monkeypatch.setattr(shp, "ARCHIVE", tmp_path)
    monkeypatch.setattr(shp, "MANIFEST", tmp_path / "m.jsonl")
    monkeypatch.setattr(shp, "RATE_LIMIT", 0)
    monkeypatch.setattr(shp, "_opener", lambda: None)
    monkeypatch.setattr(shp, "_get", lambda op, url, ref: (b'{"data": []}' if "symbol=NEW" in url
                                                          else _master(1, xbrl=False)))
    shp.collect(["A", "B", "C", "NEW"], max_detail=0)
    rows = [json.loads(l) for l in (tmp_path / "m.jsonl").read_text().splitlines()]
    assert not any(r["status"] == "FAILED" for r in rows)


def test_a_master_fetched_this_quarter_is_skipped_unless_forced(tmp_path, monkeypatch):
    """2,886 masters at 2s is 1.6 hours. A quarterly filing does not need that
    nightly; the manifest is the checkpoint."""
    monkeypatch.setattr(shp, "ARCHIVE", tmp_path)
    man = tmp_path / "m.jsonl"; monkeypatch.setattr(shp, "MANIFEST", man)
    monkeypatch.setattr(shp, "RATE_LIMIT", 0)
    monkeypatch.setattr(shp, "_opener", lambda: None)
    man.write_text(json.dumps({"source_id": shp.MASTER_SOURCE, "symbol": "OLD", "status": "STORED",
                               "sha256": "x", "fetched_at": (datetime.now(UTC) - timedelta(days=100)).isoformat()}) + "\n"
                   + json.dumps({"source_id": shp.MASTER_SOURCE, "symbol": "FRESH", "status": "STORED",
                                 "sha256": "y", "fetched_at": datetime.now(UTC).isoformat()}) + "\n")
    fetched = []
    def get(op, url, ref):
        fetched.append(url.rsplit("=", 1)[1]); return _master(1, xbrl=False)
    monkeypatch.setattr(shp, "_get", get)
    shp.collect(["OLD", "FRESH"], max_detail=0)
    assert fetched == ["OLD"]
    fetched.clear()
    shp.collect(["OLD", "FRESH"], max_detail=0, force=True)
    assert sorted(fetched) == ["FRESH", "OLD"]
