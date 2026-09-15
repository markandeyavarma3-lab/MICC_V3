"""Forward returns are attached by security_id, never by the raw ticker string.

THE DEFECT THIS PINS. Until 2026-09-15 measure._returns_sql partitioned the
price spine by `symbol` and every study joined `r.symbol = UPPER(TRIM(
raw.symbol_raw))`. A ticker is not an identity: 331 spine symbols were held by
more than one security over time, and 275 securities traded under more than
one symbol. On a recycled ticker the LEAD window ran one company's history
into the next company's prices; on a rename the window broke at the old
ticker's last row and the event vanished.

The identity layer already resolves every deal to a security_id
(src/identity/master.py RESOLVE_SQL: covering window, else nearest). These
tests build a tiny spine + symbol_history + mart in a temp directory and check
that the production SQL follows the security, not the string. The legacy SQL
is kept HERE, as a negative fixture, so the test proves the old join was wrong
on the same data. It does not exist in production.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from src.research import consensus, measure, selling

pytestmark = pytest.mark.unit


# --- the legacy join, verbatim from measure.py before 2026-09-15 ------------

def _returns_sql_legacy(spine: str, sessions: int) -> str:
    return f"""
    WITH px AS (
        SELECT symbol, date, open, close, volume,
               ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY date) AS i
        FROM read_parquet('{spine}') WHERE close > 0 AND open > 0
    ),
    f AS (
        SELECT a.symbol, a.date,
               LEAD(a.open, 1) OVER w AS entry,
               LEAD(a.close, {sessions}) OVER w AS exit_px,
               LEAD(a.date, {sessions}) OVER w AS exit_date,
               median(a.close * a.volume) OVER (
                   PARTITION BY a.symbol ORDER BY a.i ROWS BETWEEN 19 PRECEDING AND CURRENT ROW
               ) AS adv20
        FROM px a WINDOW w AS (PARTITION BY a.symbol ORDER BY a.i)
    )
    SELECT symbol, date, adv20,
           CASE WHEN date_diff('day', CAST(date AS DATE), CAST(exit_date AS DATE))
                     <= {measure.max_span_days(sessions)}
                THEN exit_px / entry - 1 END AS ret
    FROM f WHERE entry > 0
    """


LEGACY_JOIN = (
    "SELECT cl.deal_id, r.ret"
    " FROM institutional_deals_clean cl"
    " JOIN institutional_deals_raw raw USING (raw_deal_id)"
    " JOIN rets r ON r.symbol = UPPER(TRIM(raw.symbol_raw))"
    "            AND r.date = cl.trade_date"
    " WHERE cl.eligible_for_research"
)


# --- fixture: two tickers, three securities --------------------------------
#
# RECYCLE : security 1 until 2020-06-30, security 2 from 2020-07-01 — the
#           ticker changes hands with no gap, so max_span_days cannot save the
#           old join. Security 1 trades at ~100, security 2 at ~10.
# OLDNAME / NEWNAME : security 3 renamed on 2021-04-01, trading continuously.

SPINE_ROWS = [
    # symbol,     date,          open,  close, volume
    ("RECYCLE",  "2020-06-29",  100.0, 100.0, 1000.0),
    ("RECYCLE",  "2020-06-30",  100.0, 100.0, 1000.0),
    ("RECYCLE",  "2020-07-01",   10.0,  10.0, 1000.0),
    ("RECYCLE",  "2020-07-02",   10.0,  12.0, 1000.0),
    ("OLDNAME",  "2021-03-30",  100.0, 100.0, 1000.0),
    ("OLDNAME",  "2021-03-31",  100.0, 100.0, 1000.0),
    ("NEWNAME",  "2021-04-01",  100.0, 110.0, 1000.0),
    ("NEWNAME",  "2021-04-05",  110.0, 120.0, 1000.0),
    # a symbol with prices but NO identity row: must never contribute a return
    ("ORPHAN",   "2020-06-29",   50.0,  50.0, 1000.0),
    ("ORPHAN",   "2020-06-30",   50.0,  60.0, 1000.0),
    ("ORPHAN",   "2020-07-01",   60.0,  70.0, 1000.0),
]

SYMBOL_HISTORY = [
    # security_id, symbol,    valid_from,   valid_to
    (1, "RECYCLE", "2010-01-01", "2020-06-30"),
    (2, "RECYCLE", "2020-07-01", None),
    (3, "OLDNAME", "2015-01-01", "2021-03-31"),
    (3, "NEWNAME", "2021-04-01", None),
]

DEALS = [
    # deal_id, raw_deal_id, security_id, symbol_raw, trade_date, side, eligible
    (1, 101, 1,    "RECYCLE", "2020-06-29", "BUY",  True),   # recycled ticker
    (2, 102, 3,    "OLDNAME", "2021-03-30", "BUY",  True),   # renamed security
    (3, 103, None, "ORPHAN",  "2020-06-29", "BUY",  True),   # unresolved identity
    (4, 104, 1,    "RECYCLE", "2020-06-29", "SELL", False),  # for selling.EVENT_SQL
    (5, 105, 3,    "OLDNAME", "2021-03-30", "SELL", False),
    (6, 106, None, "ORPHAN",  "2020-06-29", "SELL", False),
]


@pytest.fixture
def fixture_db(tmp_path: Path) -> tuple[duckdb.DuckDBPyConnection, str]:
    """A spine parquet + the three mart/identity tables the join touches, in a
    throwaway DuckDB. Columns are the subset the SQL under test reads."""
    spine_dir = tmp_path / "price_spine_adj"
    spine_dir.mkdir()
    con = duckdb.connect(str(tmp_path / "research.duckdb"))
    con.execute("CREATE TABLE _px(symbol VARCHAR, date VARCHAR, open DOUBLE, close DOUBLE, volume DOUBLE)")
    con.executemany("INSERT INTO _px VALUES (?,?,?,?,?)", SPINE_ROWS)
    con.execute(f"COPY _px TO '{spine_dir / 'data_0.parquet'}' (FORMAT PARQUET)")
    con.execute("DROP TABLE _px")

    con.execute("CREATE TABLE symbol_history(security_id BIGINT, symbol VARCHAR, valid_from DATE, valid_to DATE)")
    con.executemany("INSERT INTO symbol_history VALUES (?,?,?,?)", SYMBOL_HISTORY)

    con.execute("""
        CREATE TABLE institutional_deals_raw(raw_deal_id BIGINT, symbol_raw VARCHAR,
                                             client_name_raw VARCHAR)""")
    con.execute("""
        CREATE TABLE institutional_deals_clean(
            deal_id BIGINT, raw_deal_id BIGINT, security_id BIGINT, trade_date DATE,
            side VARCHAR, eligible_for_research BOOLEAN,
            same_day_round_trip_flag BOOLEAN DEFAULT FALSE,
            ineligibility_reason VARCHAR DEFAULT NULL,
            deal_value_to_adv20 DOUBLE DEFAULT 0.1,
            gross_deal_value DOUBLE DEFAULT 5e7,
            unresolved_symbol_flag BOOLEAN DEFAULT FALSE,
            uncovered_symbol_flag BOOLEAN DEFAULT FALSE)""")
    for deal_id, raw_id, sec, sym, d, side, elig in DEALS:
        con.execute("INSERT INTO institutional_deals_raw VALUES (?,?,?)", [raw_id, sym, f"CLIENT{deal_id}"])
        con.execute(
            "INSERT INTO institutional_deals_clean"
            " (deal_id, raw_deal_id, security_id, trade_date, side, eligible_for_research,"
            "  unresolved_symbol_flag)"
            " VALUES (?,?,?,?,?,?,?)",
            [deal_id, raw_id, sec, d, side, elig, sec is None],
        )
    return con, str(spine_dir / "*.parquet")


def _rets(con, sql: str):
    con.execute(f"CREATE OR REPLACE TEMP VIEW rets AS {sql}")


# --- the negative fixture: the old join was wrong on this data -------------

def test_legacy_join_reads_the_wrong_company_on_a_recycled_ticker(fixture_db):
    con, spine = fixture_db
    _rets(con, _returns_sql_legacy(spine, sessions=2))
    got = dict(con.execute(LEGACY_JOIN).fetchall())
    # Security 1 stopped trading on 2020-06-30; a two-session window from
    # 06-29 does not exist for it. The string join found one anyway — in
    # security 2's prices — and returned a -90% "return".
    assert got[1] == pytest.approx(10.0 / 100.0 - 1)
    # Security 3 kept trading as NEWNAME; the string join lost it.
    assert got.get(2) is None


# --- the production SQL must follow the security ---------------------------

def test_returns_are_partitioned_by_security_not_symbol(fixture_db):
    con, spine = fixture_db
    _rets(con, measure._returns_sql(spine, sessions=2))
    rows = con.execute(
        "SELECT security_id, symbol, date, ret FROM rets ORDER BY security_id, date"
    ).fetchall()
    by_sec_date = {(r[0], r[2]): r[3] for r in rows}

    # security 1 has no 2-session forward window: NULL, not another company's price
    assert by_sec_date[(1, "2020-06-29")] is None
    # security 3 continues across the rename: 03-30 -> entry open(03-31)=100,
    # exit close two sessions later = NEWNAME 04-01 close 110
    assert by_sec_date[(3, "2021-03-30")] == pytest.approx(0.10)
    # every rets row carries an identity; the ORPHAN ticker is absent
    assert all(r[0] is not None for r in rows)
    assert not any(r[1] == "ORPHAN" for r in rows)
    # security 2 exists as its own series under the same string
    assert (2, "2020-07-01") in by_sec_date


def test_measure_joins_on_security_id_and_excludes_unresolved(fixture_db):
    con, spine = fixture_db
    _rets(con, measure._returns_sql(spine, sessions=2))
    con.execute("CREATE OR REPLACE TEMP VIEW mkt AS SELECT date, avg(ret) m FROM rets GROUP BY 1")
    df = con.execute(measure.EVENT_JOIN_SQL).df().dropna(subset=["ab"])
    # deal 1 (recycle) has no window; deal 3 (null identity) is excluded by
    # policy; deal 2 (rename) survives with the security's own forward return.
    assert len(df) == 1
    assert df["tdate"].astype(str).iloc[0] == "2021-03-30"
    assert "symbol_raw" not in measure.EVENT_JOIN_SQL
    assert "security_id IS NOT NULL" in measure.EVENT_JOIN_SQL
    assert con.execute(measure.UNRESOLVED_SQL).fetchone()[0] == 1


def test_selling_event_sql_carries_security_id_not_symbol_raw(fixture_db):
    con, spine = fixture_db
    _rets(con, measure._returns_sql(spine, sessions=2))
    con.execute("CREATE OR REPLACE TEMP VIEW mkt AS SELECT date, avg(ret) m FROM rets GROUP BY 1")
    con.execute(f"CREATE OR REPLACE TEMP VIEW ev AS {selling.EVENT_SQL}")
    ev = con.execute("SELECT security_id, tdate FROM ev ORDER BY 1").fetchall()
    assert ev == [(1, __import__("datetime").date(2020, 6, 29)),
                  (3, __import__("datetime").date(2021, 3, 30))], (
        "the null-identity sell must be excluded and no symbol_raw column produced"
    )
    df = con.execute(selling.RETURNS_JOIN_SQL).df().dropna(subset=["ab"])
    assert len(df) == 1 and str(df["tdate"].iloc[0])[:10] == "2021-03-30"
    assert "symbol_raw" not in selling.EVENT_SQL
    assert "institutional_deals_raw" not in selling.EVENT_SQL
    assert con.execute(selling.UNRESOLVED_SQL).fetchone()[0] == 1


def test_consensus_groups_convergence_by_security(fixture_db):
    con, spine = fixture_db
    # Three distinct clients buy security 3 within the window: CLIENT2 (deal 2,
    # 03-30, OLDNAME), A (03-31, OLDNAME), C (04-01, NEWNAME — after the
    # rename). Keyed by ticker that is 2 under OLDNAME + 1 under NEWNAME and
    # no threshold is crossed; keyed by security it is 3 on 04-01.
    con.execute("INSERT INTO institutional_deals_raw VALUES (201,'OLDNAME','A'),(203,'NEWNAME','C')")
    con.execute("""INSERT INTO institutional_deals_clean
        (deal_id, raw_deal_id, security_id, trade_date, side, eligible_for_research)
        VALUES (201,201,3,'2021-03-31','BUY',TRUE),(203,203,3,'2021-04-01','BUY',TRUE)""")
    con.execute(f"CREATE OR REPLACE TEMP VIEW px AS SELECT * FROM read_parquet('{spine}')")
    con.execute(f"CREATE OR REPLACE TEMP VIEW ev AS {consensus._events_sql(strict=True)}")
    events = [(sid, str(d)[:10]) for sid, d in con.execute("SELECT security_id, date FROM ev").fetchall()]
    assert events == [(3, "2021-04-01")]
    assert "symbol_raw" not in consensus._events_sql(strict=True)
    assert "security_id IS NOT NULL" in consensus._events_sql(strict=False)
    _rets(con, measure._returns_sql(spine, sessions=1))
    con.execute("CREATE OR REPLACE TEMP VIEW mkt AS SELECT date, avg(ret) m FROM rets GROUP BY 1")
    df = con.execute(consensus.RETURNS_JOIN_SQL).df().dropna(subset=["ab"])
    assert len(df) == 1


def _code_strings(mod) -> str:
    """Every string literal in the module EXCEPT docstrings. The docstrings
    legitimately name the old join to explain the correction; a grep over the
    whole source would punish the explanation of the fix."""
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(mod))
    docstrings = {
        id(n.value) for n in ast.walk(tree)
        if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)
        and isinstance(n.value.value, str)
    }
    out = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docstrings:
            out.append(n.value)
    return "\n".join(out)


def test_no_study_module_joins_prices_on_symbol_raw():
    """The design rule, pinned on the source: none of the three modules may
    key a price join on the raw ticker string. security_id or nothing."""
    for mod in (measure, consensus, selling):
        code = _code_strings(mod)
        assert "r.symbol = " not in code, f"{mod.__name__} still joins rets on symbol"
        assert "raw.symbol_raw" not in code, (
            f"{mod.__name__} still derives an identity from symbol_raw"
        )
        assert "security_id IS NOT NULL" in code, (
            f"{mod.__name__} has no explicit unresolved-identity exclusion"
        )
