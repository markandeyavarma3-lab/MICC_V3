"""Parsing archived bytes, and bounding when a disclosure became observable.

`available_from` is the field Plan 1 §7.1 says the whole study rests on, and
nothing in this project or its predecessor had ever measured it. These tests
cover the measurement and, more importantly, the ways it could be wrong in the
dangerous direction — a publication time assumed EARLIER than the truth is a
look-ahead that manufactures an effect.
"""

from __future__ import annotations

import gzip
import json
from datetime import datetime, timedelta

import pytest

from src.ingest import parse, publication

pytestmark = pytest.mark.unit


BULK_HEADER = ("Date,Symbol,Security Name,Client Name,Buy/Sell,Quantity Traded,"
               "Trade Price / Wght. Avg. Price,Remarks")
BLOCK_HEADER = ("Date,Symbol,Security Name,Client Name,Buy/Sell,Quantity Traded,"
                "Trade Price / Wght. Avg. Price")


# --- parsing ------------------------------------------------------------------


def test_bulk_and_block_have_different_column_counts():
    """Measured on the live archive: bulk 8 columns, block 7 — block has no
    Remarks. Reading them with one positional schema shifts every field."""
    bulk = f"{BULK_HEADER}\n21-AUG-2026,AHIMSA,Ahimsa Ltd,BHANSALI,BUY,81000,28.50,-\n"
    block = f"{BLOCK_HEADER}\n21-AUG-2026,AMAGI,Amagi Ltd,SBI MUTUAL FUND,BUY,142857,560.00\n"
    sb, rb, _ = parse.parse_csv(bulk.encode(), "BULK")
    sk, rk, _ = parse.parse_csv(block.encode(), "BLOCK")
    assert sb == sk == "OK"
    assert rb[0]["remarks"] == "-"
    assert rk[0]["remarks"] is None, "block has no Remarks column and must not invent one"
    # The load-bearing part: the client is not shifted into another field.
    assert rb[0]["client"] == "BHANSALI"
    assert rk[0]["client"] == "SBI MUTUAL FUND"
    assert rk[0]["price"] == "560.00"


def test_columns_are_mapped_by_header_not_position():
    """An added column must be ignored, not silently shift everything right."""
    body = (f"{BULK_HEADER},Extra\n"
            f"21-AUG-2026,AHIMSA,Ahimsa Ltd,BHANSALI,BUY,81000,28.50,-,junk\n")
    status, rows, _ = parse.parse_csv(body.encode(), "BULK")
    assert status == "OK"
    assert rows[0]["symbol"] == "AHIMSA" and rows[0]["qty"] == "81000"


def test_quantity_and_price_stay_TEXT():
    """Plan 1 §5.3 keeps them verbatim: the source sometimes carries commas.
    Parsing them to numbers here would make the repair invisible."""
    body = f'{BULK_HEADER}\n21-AUG-2026,X,X Ltd,C,BUY,"1,234,567",28.50,-\n'
    _, rows, _ = parse.parse_csv(body.encode(), "BULK")
    assert rows[0]["qty"] == "1,234,567", "must not be coerced or cleaned"
    assert isinstance(rows[0]["price"], str)


def test_the_original_row_is_retained_verbatim():
    body = f"{BULK_HEADER}\n21-AUG-2026,AHIMSA,Ahimsa Ltd,BHANSALI,BUY,81000,28.50,-\n"
    _, rows, _ = parse.parse_csv(body.encode(), "BULK")
    raw = json.loads(rows[0]["raw_row_json"])
    assert raw["Symbol"] == "AHIMSA" and raw["Buy/Sell"] == "BUY"


def test_an_empty_day_is_not_a_failure():
    """'No deals' and 'the fetch broke' are different facts, and conflating them
    is how the predecessor lost a Friday without noticing."""
    status, rows, err = parse.parse_csv(b"NO RECORDS", "BLOCK")
    assert status == "EMPTY" and rows == [] and err is None


def test_an_unrecognised_header_is_recorded_not_raised():
    """A source format change must produce a recorded failure, never an
    exception that stops a batch — the bytes are already safe."""
    status, rows, err = parse.parse_csv(b"Col1,Col2\n1,2\n", "BULK")
    assert status == "PARSE_FAILED" and rows == [] and "unrecognised header" in err


def test_undated_rows_fail_rather_than_defaulting_to_today():
    status, _, err = parse.parse_csv(
        f"{BULK_HEADER}\nNOT-A-DATE,X,X,C,BUY,1,1.0,-\n".encode(), "BULK")
    assert status == "PARSE_FAILED" and "parseable date" in err


def test_malformed_json_is_recorded_not_raised():
    status, _, err = parse.parse_fii_dii(b"{not json")
    assert status == "PARSE_FAILED" and "invalid json" in err


def test_parse_archive_never_raises_on_a_corrupt_file(tmp_path):
    bad = tmp_path / "BULK_NSE_20260821_dead.csv.gz"
    bad.write_bytes(b"this is not gzip")
    got = parse.parse_archive(bad)
    assert got.status == "PARSE_FAILED" and not got.ok


def test_a_real_archived_file_round_trips(tmp_path):
    p = tmp_path / "BULK" / "NSE" / "year=2026" / "month=08" / "BULK_NSE_20260821_ab.csv.gz"
    p.parent.mkdir(parents=True)
    with gzip.open(p, "wb") as fh:
        fh.write(f"{BULK_HEADER}\n21-AUG-2026,AHIMSA,A Ltd,C,BUY,81000,28.50,-\n".encode())
    got = parse.parse_archive(p)
    assert got.status == "OK" and got.session_date == "2026-08-21"
    assert got.report_type == "BULK" and got.exchange == "NSE" and len(got.sha256) == 64


# --- publication bounds --------------------------------------------------------


def _rec(source, session, when_ist, status="STORED"):
    """A manifest row, given an IST wall-clock time."""
    utc = datetime.fromisoformat(when_ist) - timedelta(hours=5, minutes=30)
    return {"source_id": source, "session_date": session, "status": status,
            "fetched_at": utc.replace(tzinfo=None).isoformat() + "+00:00"}


def _manifest(tmp_path, rows):
    p = tmp_path / "manifest.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in rows))
    return p


def test_publication_is_bracketed_by_two_observations(tmp_path):
    """The bound is (last poll returning a DIFFERENT session, first poll
    returning THIS one]. Both ends are observations."""
    m = _manifest(tmp_path, [
        _rec("nse_bulk_deals", "2026-08-20", "2026-08-21T08:00", "DUPLICATE"),
        _rec("nse_bulk_deals", "2026-08-21", "2026-08-21T22:30"),
    ])
    # bounds() is sorted by session date, so index 0 is the EARLIER session,
    # which is legitimately unbounded. Select the one under test.
    b = next(x for x in publication.bounds(m) if x.session_date == "2026-08-21")
    assert b.is_bounded
    assert b.last_absent_ist.hour == 8 and b.first_present_ist.hour == 22
    assert b.width_hours == pytest.approx(14.5)


def test_an_unbounded_first_observation_says_so(tmp_path):
    """With no earlier poll, publication is unbounded below. Reporting a bound
    anyway would assert an observation nobody made."""
    m = _manifest(tmp_path, [_rec("nse_bulk_deals", "2026-08-17", "2026-08-17T20:49")])
    b = publication.bounds(m)[0]
    assert not b.is_bounded and b.width_hours is None


def test_failed_fetches_are_not_evidence_of_absence(tmp_path):
    """A FAILED poll says nothing about whether the file existed. Counting it
    would bias every bound EARLIER, which is the look-ahead direction."""
    m = _manifest(tmp_path, [
        _rec("nse_bulk_deals", "2026-08-20", "2026-08-21T08:00", "DUPLICATE"),
        {"source_id": "nse_bulk_deals", "status": "FAILED",
         "fetched_at": "2026-08-21T14:00:00+00:00", "session_date": None},
        _rec("nse_bulk_deals", "2026-08-21", "2026-08-21T22:30"),
    ])
    b = next(x for x in publication.bounds(m) if x.session_date == "2026-08-21")
    assert b.last_absent_ist.hour == 8, "the FAILED poll must not tighten the bound"


def test_utc_is_converted_to_ist(tmp_path):
    """NSE publishes on IST and the manifest records UTC. A 5.5h error here
    would move publication across the polling boundary."""
    m = _manifest(tmp_path, [_rec("nse_bulk_deals", "2026-08-21", "2026-08-21T22:30")])
    assert publication.bounds(m)[0].first_present_ist.hour == 22


def test_no_manifest_yields_no_claims(tmp_path):
    assert publication.bounds(tmp_path / "absent.jsonl") == []
