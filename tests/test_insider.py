"""The insider collector and parser, and the two-month silent failure they exist to prevent.

MICC's fetcher went "silently green-but-empty for ~2 months" because
/api/corporates-pit was retired and kept answering HTTP 200 with
{"acqNameList":[],"data":[]}. Every check it had stayed green. The bytes for
those two months are gone.
"""

from __future__ import annotations

import pytest

from src.archive import insider as archive
from src.ingest import insider as parse

pytestmark = pytest.mark.unit


def test_the_live_endpoint_is_the_gg_one():
    """The retired route still answers 200. Using it is the silent failure."""
    assert "corporates-pit-gg" in archive.INDEX_URL, (
        "/api/corporates-pit (without -gg) was retired around April 2026 and "
        "answers 200 with an empty envelope"
    )


def test_an_empty_envelope_is_a_failure_not_a_quiet_day():
    """THE GUARD THAT MATTERS. A well-formed 200 carrying data:[] must not be
    recorded as success. Verified against the real retired endpoint on
    2026-09-01: 28 bytes, status FAILED."""
    import inspect

    src = inspect.getsource(archive.capture_window)
    assert "EMPTY ENVELOPE" in src
    assert 'if not rows:' in src, "no explicit empty-payload branch"
    i, j = src.index("if not rows:"), src.index("digest = hash_bytes")
    assert '"FAILED"' in src[i:j], (
        "an empty payload must be recorded FAILED; anything else reproduces the "
        "two-month silent loss"
    )


def test_one_filing_can_hold_many_transactions():
    """22 archived filings held 39 transactions. Parsing one row per file would
    have dropped 44% of them, and the drop would look like sparse data."""
    import inspect

    src = inspect.getsource(parse.parse_file)
    assert "by_ctx" in src, "no per-context grouping — this parses one row per file"
    assert "SecuritiesAcquiredOrDisposedTransactionType" in src


@pytest.mark.parametrize("raw,expected", [
    ("Promoter", "Promoters"),
    ("Promoter Group", "Promoter Group"),
    ("Promoter and Director", "Promoters"),
    ("KMP", "Key Managerial Personnel"),
])
def test_category_maps_onto_the_vocabulary_0046_measured_on(raw, expected):
    """0046's promoter power figures were measured on the SEED's vocabulary
    (Promoters / Promoter Group). XBRL says 'Promoter' and 'Promoter and
    Director'. A new row that fails to map is silently outside the population
    that measurement was about.

    'Promoter and Director' maps to Promoters because MICC's fetcher did, with
    the comment "promoter is the stronger class", and the seed was normalised
    that way.
    """
    assert parse._CATEGORY.get(raw.strip().lower(), raw) == expected


@pytest.mark.parametrize("raw,expected", [
    ("Acquisition", "Buy"), ("Disposal", "Sell"),
    ("acquired", "Buy"), ("Sale", "Sell"),
])
def test_transaction_type_maps_onto_buy_and_sell(raw, expected):
    assert parse._TXN.get(raw.strip().lower(), raw) == expected


def test_an_unknown_category_passes_through_rather_than_becoming_null():
    """Standing rule 9: UNKNOWN beats inference. 'Trust' and 'Other' are real
    values with no seed equivalent; nulling them would delete information, and
    category_raw always keeps the original either way."""
    assert parse._CATEGORY.get("trust", "Trust") == "Trust"


def test_the_parser_derives_no_eligibility():
    """Transactions in, transactions out. Whether one is an EVENT is the study's
    question; deciding it here is how a filter becomes invisible."""
    import inspect

    src = inspect.getsource(parse)
    for banned in ("eligible", "adv20", "min_value", "ret"):
        assert f"def {banned}" not in src
    assert "price_spine" not in src, "the parser must not read prices"


# --- the detail fetch knows what it holds (2026-09-18) ---------------------------


def _index_body(n=3):
    import json
    return json.dumps({"data": [
        {"appId": str(100 + i), "symbol": "ACME", "broadcastDateTime": "01-Jun-2026 10:00",
         "xmlFileName": f"https://nsearchives.nseindia.com/corporate/xbrl/PIT_{i}_WebXMLFile.xml"}
        for i in range(n)]}).encode()


def test_a_held_or_gone_xml_costs_no_request_so_the_budget_reaches_new_filings(tmp_path, monkeypatch):
    """Every daily run re-fetched held files in index order, spent its budget
    on duplicates and reported '0 new' while 1,580 of 2,672 distinct filings
    had never been fetched. A known URL is now skipped without a request."""
    from datetime import date
    from src.archive import insider as ins
    monkeypatch.setattr(ins, "ARCHIVE", tmp_path)
    monkeypatch.setattr(ins, "MANIFEST", tmp_path / "m.jsonl")
    monkeypatch.setattr(ins, "RATE_LIMIT", 0)
    calls = []
    def get(op, url, ref):
        calls.append(url)
        if "corporates-pit" in url:
            return _index_body(3)
        return f"<xbrl>{url[-20:]}</xbrl>".encode()
    monkeypatch.setattr(ins, "_get", get)
    ins._prior_xbrl.clear()
    ins._prior_xbrl["https://nsearchives.nseindia.com/corporate/xbrl/PIT_0_WebXMLFile.xml"] = "STORED"
    ins._prior_xbrl["https://nsearchives.nseindia.com/corporate/xbrl/PIT_1_WebXMLFile.xml"] = "GONE"
    e = ins.capture_window(None, date(2026, 6, 1), date(2026, 6, 30), set(), [10])
    xml_calls = [u for u in calls if "WebXMLFile" in u]
    assert xml_calls == ["https://nsearchives.nseindia.com/corporate/xbrl/PIT_2_WebXMLFile.xml"]
    assert e["details_stored"] == 1 and e["details_already_held"] == 2
    import json
    rows = [json.loads(l) for l in (tmp_path / "m.jsonl").read_text().splitlines()]
    xr = [r for r in rows if r["source_id"] == ins.XBRL_SOURCE_ID]
    assert len(xr) == 1 and xr[0]["status"] == "STORED" and xr[0]["url"].endswith("PIT_2_WebXMLFile.xml")


def test_one_xml_shared_by_many_index_rows_is_fetched_once(tmp_path, monkeypatch):
    """NSE lists one row per PERSON; the XML is per filing. 17,634 rows, 2,672 files."""
    import json
    from datetime import date
    from src.archive import insider as ins
    monkeypatch.setattr(ins, "ARCHIVE", tmp_path)
    monkeypatch.setattr(ins, "MANIFEST", tmp_path / "m.jsonl")
    monkeypatch.setattr(ins, "RATE_LIMIT", 0)
    body = json.dumps({"data": [{"appId": "7", "symbol": "ACME", "xmlFileName": "https://x/PIT_7.xml"}] * 4}).encode()
    calls = []
    def get(op, url, ref):
        calls.append(url)
        if "corporates-pit" in url:
            return body
        raise RuntimeError("HTTP Error 503")  # a FAILING file: the index does not skip it, the loop must
    monkeypatch.setattr(ins, "_get", get)
    ins._prior_xbrl.clear()
    e = ins.capture_window(None, date(2026, 6, 1), date(2026, 6, 30), set(), [10])
    assert calls.count("https://x/PIT_7.xml") == 1 and e["detail_failures"] == 1


# --- stopping: the 159-minute run of 2026-09-19 -----------------------------------


def test_consecutive_network_failures_trip_the_breaker_and_stop_the_run(tmp_path, monkeypatch):
    """THE 159-MINUTE RUN. On 2026-09-19 the 22:30 stage spent two hours and
    thirty-nine minutes against a refusing host, retrieved 12 files, failed,
    and was still going when the 01:00 SHP session started. Each failing fetch
    costs three attempts at (TIMEOUT + 15s) plus backoff, so proving the host
    is down one file at a time is the most expensive way to learn it."""
    import json
    from datetime import date
    from src.archive import insider as ins
    monkeypatch.setattr(ins, "ARCHIVE", tmp_path)
    monkeypatch.setattr(ins, "MANIFEST", tmp_path / "m.jsonl")
    monkeypatch.setattr(ins, "RATE_LIMIT", 0)
    calls = []
    def get(op, url, ref):
        calls.append(url)
        if "corporates-pit" in url:
            return _index_body(40)
        raise RuntimeError("<urlopen error [Errno 8] nodename nor servname provided>")
    monkeypatch.setattr(ins, "_get", get)
    ins._prior_xbrl.clear()
    out = ins.collect(date(2026, 6, 1), date(2026, 6, 30))
    assert out[-1].status == "FAILED" and "THROTTLED" in out[-1].detail
    # Five tries, not forty. The breaker is the whole point.
    assert len([u for u in calls if "WebXMLFile" in u]) == ins.BREAKER_FAILURES
    rows = [json.loads(l) for l in (tmp_path / "m.jsonl").read_text().splitlines()]
    assert rows[-1]["status"] == "FAILED" and "THROTTLED" in rows[-1]["error"]


def test_a_404_does_not_trip_the_breaker_because_it_is_one_gone_file(tmp_path, monkeypatch):
    """12 old filings 404 permanently. A gone file says nothing about the
    host's willingness to serve the next one, and a breaker that counted them
    would stop every run on the same twelve."""
    from datetime import date
    from src.archive import insider as ins
    monkeypatch.setattr(ins, "ARCHIVE", tmp_path)
    monkeypatch.setattr(ins, "MANIFEST", tmp_path / "m.jsonl")
    monkeypatch.setattr(ins, "RATE_LIMIT", 0)
    def get(op, url, ref):
        if "corporates-pit" in url:
            return _index_body(20)
        raise RuntimeError("HTTP Error 404: Not Found")
    monkeypatch.setattr(ins, "_get", get)
    ins._prior_xbrl.clear()
    out = ins.collect(date(2026, 6, 1), date(2026, 6, 30))
    assert not any(o.status == "FAILED" and "THROTTLED" in o.detail for o in out)


def test_the_wall_clock_stops_the_run_and_is_not_a_failure(tmp_path, monkeypatch):
    """A backlog run ending on the clock is how a catch-up is EXPECTED to end.
    Reporting it as FAILED pages the owner nightly for working as designed,
    which is the alert nobody reads (0074, same rule as shp.py)."""
    import json
    from datetime import date
    from src.archive import insider as ins
    monkeypatch.setattr(ins, "ARCHIVE", tmp_path)
    monkeypatch.setattr(ins, "MANIFEST", tmp_path / "m.jsonl")
    monkeypatch.setattr(ins, "RATE_LIMIT", 0)
    monkeypatch.setattr(ins, "_get", lambda op, url, ref: _index_body(1))
    ins._prior_xbrl.clear()
    out = ins.collect(date(2026, 1, 1), date(2026, 6, 30), max_minutes=0)
    assert out[-1].status == "STOPPED" and "wall clock" in out[-1].detail
    assert len(out) == 1, "stopped before the first window, not after all of them"
    rows = [json.loads(l) for l in (tmp_path / "m.jsonl").read_text().splitlines()]
    assert rows[-1]["status"] == "STOPPED" and "error" not in rows[-1]


def test_the_index_still_lands_when_the_clock_stops_only_the_detail(tmp_path, monkeypatch):
    """The index is one cheap fetch and the detail is many expensive ones, so
    the deadline cuts the detail and keeps the index — the next run resumes
    from the URL index rather than re-fetching the window."""
    from datetime import UTC, date, datetime
    from src.archive import insider as ins
    monkeypatch.setattr(ins, "ARCHIVE", tmp_path)
    monkeypatch.setattr(ins, "MANIFEST", tmp_path / "m.jsonl")
    monkeypatch.setattr(ins, "RATE_LIMIT", 0)
    calls = []
    def get(op, url, ref):
        calls.append(url)
        if "corporates-pit" in url:
            return _index_body(5)
        return b"<xbrl/>"
    monkeypatch.setattr(ins, "_get", get)
    ins._prior_xbrl.clear()
    past = datetime.now(UTC)
    e = ins.capture_window(None, date(2026, 6, 1), date(2026, 6, 30), set(), [10], deadline_at=past)
    assert e["status"] in ("STORED", "DUPLICATE"), "the index must still be archived"
    assert e["filings"] == 5 and e["details_stored"] == 0
    assert e.get("details_stopped") == "wall clock"
    assert not [u for u in calls if "WebXMLFile" in u]
