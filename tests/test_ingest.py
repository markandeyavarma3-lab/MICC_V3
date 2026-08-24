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


# --- landing: closing the break between parse and the warehouse --------------


class TestLanding:
    """An audit on 2026-08-23 found the pipeline severed: parse produced rows and
    nothing wrote them, 14 tables held 0 rows, and `research_db` was referenced
    by no module at all. These tests exist so it cannot silently re-open.
    """

    @staticmethod
    def _db(tmp_path, monkeypatch):
        """Isolate BOTH databases. Patching only `research_db` let every test run
        write artefacts into the PRODUCTION provenance graph — 23 spurious
        `warehouse:deal_source_files` nodes arrived that way on 2026-08-24, and
        `artefact` is append-only so they are permanent.

        This is the defect commit 7fd3e68 fixed for the trial ledger,
        reintroduced for artefacts because the second database was not obvious
        from land()'s signature.
        """
        from src.governance import provenance as prov_mod
        from src.ingest import land as land_mod

        db = tmp_path / "research_test.duckdb"
        gov = tmp_path / "governance_test.sqlite"
        monkeypatch.setattr(land_mod, "research_db", lambda e=None: db)
        monkeypatch.setattr(prov_mod, "governance_db", lambda e=None: gov)
        return db

    @staticmethod
    def _archive(tmp_path, session: str, client: str, name: str = "BULK_NSE_x.csv.gz"):
        p = tmp_path / "arch" / "BULK" / "NSE" / "year=2026" / "month=08" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(p, "wb") as fh:
            fh.write(
                f"{BULK_HEADER}\n{session},AHIMSA,A Ltd,{client},BUY,81000,28.50,-\n".encode()
            )
        return p

    def test_landing_is_idempotent_on_the_hash(self, tmp_path, monkeypatch):
        from src.ingest import land as land_mod

        self._db(tmp_path, monkeypatch)
        self._archive(tmp_path, "21-AUG-2026", "ALPHA")
        monkeypatch.setattr(land_mod, "parse_all",
                            lambda: parse.parse_all(tmp_path / "arch"))
        first = land_mod.land()
        assert first.files_landed == 1 and first.rows_landed == 1
        second = land_mod.land()
        assert second.files_landed == 0 and second.files_skipped == 1, (
            "re-landing identical bytes must skip, or the archive cannot be re-run"
        )

    def test_a_revision_is_detected_and_BOTH_versions_are_kept(self, tmp_path, monkeypatch):
        """Plan 1 §5.4: "Both versions are kept. Research uses the version
        available at the decision date."

        This was IMPOSSIBLE as specified — §5.2's UNIQUE(exchange, report_type,
        report_date, parser_version) rejected the second version outright.
        Migration 0002 exists solely for this test to be able to pass.
        """
        import duckdb

        from src.ingest import land as land_mod

        db = self._db(tmp_path, monkeypatch)
        self._archive(tmp_path, "21-AUG-2026", "ALPHA", "BULK_NSE_v1.csv.gz")
        monkeypatch.setattr(land_mod, "parse_all",
                            lambda: parse.parse_all(tmp_path / "arch"))
        land_mod.land()

        # NSE restates the same session with different content.
        self._archive(tmp_path, "21-AUG-2026", "ALPHA AND BETA", "BULK_NSE_v2.csv.gz")
        rep = land_mod.land()

        assert rep.revisions, "a new hash for a held session must be flagged as a revision"
        con = duckdb.connect(str(db))
        try:
            files = con.execute(
                "SELECT revision_number FROM deal_source_files"
                " WHERE report_date = '2026-08-21' ORDER BY revision_number"
            ).fetchall()
            revs = con.execute("SELECT COUNT(*) FROM source_revisions").fetchone()[0]
        finally:
            con.close()
        assert [r[0] for r in files] == [0, 1], "both versions must survive"
        assert revs == 1, "the revision must be recorded, not merely tolerated"

    def test_fii_dii_lands_as_a_file_but_not_as_deal_rows(self, tmp_path, monkeypatch):
        """institutional_deals_raw has grain 'one disclosed deal'. An FII/DII
        record is a market-wide aggregate with no symbol, client or side."""
        import duckdb

        from src.ingest import land as land_mod

        db = self._db(tmp_path, monkeypatch)
        p = tmp_path / "arch" / "FII_DII" / "NSE" / "year=2026" / "month=08" / "f.json.gz"
        p.parent.mkdir(parents=True)
        with gzip.open(p, "wb") as fh:
            fh.write(b'[{"date":"21-Aug-2026","category":"DII","buyValue":"1",'
                     b'"sellValue":"2","netValue":"-1"}]')
        monkeypatch.setattr(land_mod, "parse_all",
                            lambda: parse.parse_all(tmp_path / "arch"))
        rep = land_mod.land()
        assert rep.files_landed == 1
        assert rep.rows_landed == 0, "an aggregate must not enter a deal-grain table"
        con = duckdb.connect(str(db))
        try:
            assert con.execute(
                "SELECT row_count FROM deal_source_files").fetchone()[0] == 1, (
                "the row count is still recorded on the file"
            )
        finally:
            con.close()

    def test_quantity_and_price_survive_as_TEXT(self, tmp_path, monkeypatch):
        """Plan 1 §5.3. Landing must not quietly coerce what the parser
        deliberately kept verbatim."""
        import duckdb

        from src.ingest import land as land_mod

        db = self._db(tmp_path, monkeypatch)
        p = tmp_path / "arch" / "BULK" / "NSE" / "year=2026" / "month=08" / "b.csv.gz"
        p.parent.mkdir(parents=True)
        with gzip.open(p, "wb") as fh:
            fh.write(f'{BULK_HEADER}\n21-AUG-2026,X,X Ltd,C,BUY,"1,234,567",28.50,-\n'.encode())
        monkeypatch.setattr(land_mod, "parse_all",
                            lambda: parse.parse_all(tmp_path / "arch"))
        land_mod.land()
        con = duckdb.connect(str(db))
        try:
            assert con.execute(
                "SELECT quantity_raw FROM institutional_deals_raw").fetchone()[0] == "1,234,567"
        finally:
            con.close()


class TestSeedCorpus:
    """The twenty-year corpus, landed and honestly labelled.

    Until 2026-08-24 the 235,880 seed deals had never passed through the
    pipeline: eligibility.py read the parquet directly, so every number built on
    it — including the twelve-month result decision 0034 rests on — bypassed the
    archive, the identity layer and the provenance DAG.
    """

    @pytest.mark.data
    @pytest.mark.skipif(
        not (__import__("src.common.paths", fromlist=["SEED"]).SEED / "bulk_deals.parquet").is_file(),
        reason="seed not carried",
    )
    def test_seed_rows_are_distinguishable_from_live_rows(self):
        """The load-bearing property. Live-collected rows have an observed
        publication time; seed rows have none and never can. Blurring them would
        let 235,880 rows of unknown provenance inherit the credibility of 611
        rows of known provenance."""
        import duckdb

        from src.common.paths import research_db
        from src.ingest.seed_deals import SEED_PARSER_VERSION
        from src.ingest.land import PARSER_VERSION

        assert SEED_PARSER_VERSION != PARSER_VERSION, (
            "seed and live rows must not share a parser_version"
        )
        con = duckdb.connect(str(research_db("prod")))
        try:
            versions = {
                r[0]: r[1] for r in con.execute(
                    "SELECT f.parser_version, COUNT(*) FROM institutional_deals_raw r"
                    " JOIN deal_source_files f USING(source_file_id)"
                    " GROUP BY 1"
                ).fetchall()
            }
        finally:
            con.close()
        assert SEED_PARSER_VERSION in versions, "the seed corpus is not landed"
        assert versions[SEED_PARSER_VERSION] == 235_880
        assert versions.get(PARSER_VERSION, 0) > 0, "live rows are missing"

    @pytest.mark.unit
    def test_the_seed_declares_that_available_from_is_unrecoverable(self):
        """available_from is the field Plan 1 §7.1 says the study rests on. For
        2006-2026 nobody recorded it and nobody can. The module must say so
        rather than leaving a reader to assume the live measurement covers it."""
        from src.ingest import seed_deals

        text = seed_deals.__doc__ or ""
        assert "nobody recorded when any of it became public" in text.lower() \
            or "available_from" in text
        assert "LOW confidence" in text or "conservative bound" in text
