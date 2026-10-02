"""Why each security left the EQ price universe (Plan 1 step 3.3, decision 0082).

Every case below was wrong or unanswerable before: a rename read as a
delisting, a one-session gap read as a delisting, a face-value split read as a
delisting, a stock moved to the BE surveillance series read as a delisting,
and every real delisting read as UNKNOWN.
"""

from __future__ import annotations

from datetime import date, timedelta

import duckdb
import pytest

from src.identity import master

pytestmark = pytest.mark.unit

END = date(2026, 9, 30)
# 60 weekday sessions ending END; enough for the 20-session stale rule.
SESSIONS = [d for d in (END - timedelta(days=i) for i in range(90)) if d.weekday() < 5][:60][::-1]


def _exit(tmp_path, isin_rows, spine_rows, listing_rows, nse=(), bse=(), listing=True):
    """isin_rows: (isin, symbol, first, last|None); spine_rows: (symbol, date);
    listing_rows: (symbol, series, isin, first, last). Returns {isin: row}."""
    con = duckdb.connect()

    def put(sql, rows):
        if rows:
            con.executemany(sql, rows)

    con.execute("CREATE TABLE im (isin VARCHAR, symbol VARCHAR, first_date VARCHAR, last_date VARCHAR)")
    put("INSERT INTO im VALUES (?,?,?,?)", [(i, s, str(f), str(t) if t else None) for i, s, f, t in isin_rows])
    con.execute(f"COPY im TO '{tmp_path / 'im.parquet'}' (FORMAT PARQUET)")
    con.execute("CREATE TABLE sp (symbol VARCHAR, date VARCHAR)")
    put("INSERT INTO sp VALUES (?,?)", [(s, str(d)) for s, d in spine_rows])
    con.execute(f"COPY sp TO '{tmp_path / 'sp.parquet'}' (FORMAT PARQUET)")
    con.execute("CREATE TABLE ls (symbol VARCHAR, series VARCHAR, isin VARCHAR,"
                " first_date DATE, last_date DATE, sessions INTEGER)")
    put("INSERT INTO ls VALUES (?,?,?,?,?,1)", list(listing_rows))
    con.execute(f"COPY ls TO '{tmp_path / 'ls.parquet'}' (FORMAT PARQUET)")
    con.execute("CREATE TEMP TABLE _nse_delisted (symbol VARCHAR, reason VARCHAR, delisted_on DATE)")
    put("INSERT INTO _nse_delisted VALUES (?,?,?)", list(nse))
    con.execute("CREATE TEMP TABLE _bse (isin VARCHAR, listing_status VARCHAR)")
    put("INSERT INTO _bse VALUES (?,?)", list(bse))
    src = (f"SELECT * FROM read_parquet('{tmp_path / 'ls.parquet'}')" if listing
           else master._listing_src())
    con.execute(master.EXIT_SQL.format(
        im=tmp_path / "im.parquet", spine=tmp_path / "sp.parquet", listing=src,
        stale=master.STALE_SESSIONS - 1,
        first_date=master._date("first_date"), last_date=master._date("last_date")))
    cols = [d[0] for d in con.execute("SELECT * FROM _exit LIMIT 0").description]
    out = {r[0]: dict(zip(cols, r, strict=True)) for r in con.execute("SELECT * FROM _exit").fetchall()}
    con.close()
    return out


def _px(symbol, upto=None, start=0):
    return [(symbol, d) for d in SESSIONS[start:] if upto is None or d <= upto]


def _eq_listing(symbol, isin, last=END):
    return (symbol, "EQ", isin, SESSIONS[0], last)


def test_a_renamed_company_is_active_not_delisted(tmp_path):
    """The canonical symbol is the longest-held one; it stopped at the rename."""
    rename = SESSIONS[10]
    got = _exit(tmp_path,
                [("INE1", "OLDNAME", "2005-01-01", rename), ("INE1", "NEWNAME", rename, None)],
                _px("OLDNAME", upto=rename) + _px("NEWNAME", start=11),
                [_eq_listing("NEWNAME", "INE1")])
    assert not got["INE1"]["stopped"] and got["INE1"]["reason"] is None


def test_a_few_missing_sessions_is_not_a_delisting(tmp_path):
    got = _exit(tmp_path, [("INE1", "A", "2005-01-01", None)],
                _px("A", upto=SESSIONS[-6]) + [("B", d) for d in SESSIONS], [])
    assert not got["INE1"]["stopped"], "5 sessions without a trade is not dead (stale rule is 20)"


def test_a_stop_past_the_stale_line_is_a_stop(tmp_path):
    got = _exit(tmp_path, [("INE1", "A", "2005-01-01", None)],
                _px("A", upto=SESSIONS[-30]) + [("B", d) for d in SESSIONS], [])
    assert got["INE1"]["stopped"] and got["INE1"]["reason"] == "UNKNOWN"


def test_a_new_isin_on_the_same_symbol_is_an_isin_change(tmp_path):
    split = SESSIONS[20]
    got = _exit(tmp_path,
                [("INE1OLD", "GSFC", "2005-01-01", split), ("INE1NEW", "GSFC", SESSIONS[21], None)],
                _px("GSFC"), [])
    assert got["INE1OLD"]["reason"] == "ISIN_CHANGE"
    assert got["INE1OLD"]["successor_isin"] == "INE1NEW"
    assert not got["INE1NEW"]["stopped"], "the current holder of a reused ticker keeps its trades"


def test_a_replaced_holder_does_not_borrow_the_new_holders_trades(tmp_path):
    """A recycled ticker: the old company died years before the new one listed."""
    got = _exit(tmp_path,
                [("INEOLD", "ACME", "2005-01-01", SESSIONS[5]), ("INENEW", "ACME", SESSIONS[40], None)],
                _px("ACME", upto=SESSIONS[5]) + _px("ACME", start=40), [])
    assert got["INEOLD"]["stopped"], "the old company looked alive on the new one's prices"
    assert got["INEOLD"]["reason"] != "ISIN_CHANGE", "35 sessions apart is not a split"


def test_a_stock_moved_to_a_surveillance_series_left_the_universe(tmp_path):
    got = _exit(tmp_path, [("INE1", "PPAP", "2005-01-01", None)],
                _px("PPAP", upto=SESSIONS[5]) + [("B", d) for d in SESSIONS],
                [("PPAP", "EQ", "INE1", SESSIONS[0], SESSIONS[5]),
                 ("PPAP", "BE", "INE1", SESSIONS[6], END)])
    assert got["INE1"]["reason"] == "LEFT_UNIVERSE"


def test_a_fund_unit_is_found_by_symbol_after_its_isin_changed(tmp_path):
    got = _exit(tmp_path, [("INF1", "GOLDBEES", "2005-01-01", None)],
                _px("GOLDBEES", upto=SESSIONS[5]) + [("B", d) for d in SESSIONS],
                [("GOLDBEES", "EQ", "INF2", SESSIONS[0], END)])
    assert got["INF1"]["reason"] == "LEFT_UNIVERSE"


def test_nse_says_why_and_an_old_delisting_of_a_reused_ticker_does_not_match(tmp_path):
    stop = SESSIONS[5]
    got = _exit(tmp_path,
                [("INE1", "HEXAWARE", "2005-01-01", None), ("INE2", "OLDCO", "2005-01-01", None)],
                _px("HEXAWARE", upto=stop) + _px("OLDCO", upto=stop) + [("B", d) for d in SESSIONS],
                [],
                nse=[("HEXAWARE", "ACQUISITION", stop),
                     ("OLDCO", "SUSPENSION", stop - timedelta(days=3000))])
    assert got["INE1"]["reason"] == "ACQUISITION"
    assert got["INE2"]["reason"] == "UNKNOWN"


def test_bse_suspended_is_a_suspension(tmp_path):
    got = _exit(tmp_path, [("INE1", "A", "2005-01-01", None)],
                _px("A", upto=SESSIONS[5]) + [("B", d) for d in SESSIONS], [],
                bse=[("INE1", "Suspended")])
    assert got["INE1"]["reason"] == "SUSPENSION"


def test_without_a_listing_history_the_stage_still_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(master, "LISTING", tmp_path / "absent.parquet")
    got = _exit(tmp_path, [("INE1", "A", "2005-01-01", None)],
                _px("A", upto=SESSIONS[5]) + [("B", d) for d in SESSIONS], [], listing=False)
    assert got["INE1"]["reason"] == "UNKNOWN"


def test_merger_is_never_guessed():
    """universe.yml requires a merged_into_id link for MERGER; no source names
    the acquirer of an absorbed company, so the classifier must not emit it."""
    assert "'MERGER'" not in master.EXIT_SQL


def test_every_reason_the_classifier_emits_is_declared_in_config():
    import re

    import yaml

    from src.common.paths import CONFIGS

    declared = set(yaml.safe_load((CONFIGS / "universe.yml").read_text())["delisting"]["classify_into"])
    emitted = set(re.findall(r"THEN '([A-Z_]+)'", master.EXIT_SQL))
    emitted |= {r for r in master_reasons() if r}
    assert emitted <= declared, f"undeclared reasons: {emitted - declared}"


def master_reasons():
    from src.archive import delisted

    return set(delisted.TYPE_TO_REASON.values())
