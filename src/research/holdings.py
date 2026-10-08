"""holdings.py — exp_004: quarterly institutional holding change, cross-sectional.

THE STUDY, BUILT BEFORE THE DATA IS COMPLETE AND BEHIND THE REGISTRATION GUARD.

Two halves, deliberately separated by what they may touch:

  `signals()`   reads the holdings table only. Change since the previous
                filing, per ISIN, for three signals. No price, no return. It may
                run at any time — it is a parse, not a look.

  `panel()` and `run()`   join those signals to forward returns and rank them.
                That is the study, and it REFUSES TO RUN UNREGISTERED: the
                registry must hold exp_004 with status REGISTERED, and the hash
                is printed on every output so the report can cite it. The
                preliminary dispersion in `holdings_power.py` never reads a
                signal; this module never runs without a registration. Between
                them there is no path to a conditional mean before the spec is
                frozen.

THE ESTIMATOR. Within each cohort (the calendar quarter containing the
filing's period-end), rank names by the signal into deciles, long the top,
short the bottom, equal weight, hold 63 sessions from the OPEN of the first
session after `broadcast_date` (never the quarter-end — the filing is not
public until broadcast). The statistic is the mean across cohorts of the
top-minus-bottom CHAR_MATCHED abnormal return; its standard error carries the
Bartlett serial correction from `power.py`; the null is a within-cohort label
permutation; three tests share one Benjamini-Hochberg family.

THE TAIL RULE, chosen 2026-09-18 before any signal was ranked: a name is in
the universe only if the pessimistic participation cap can build the position
— 5 sessions x 5% of ADV20 >= the per-name notional of a Rs 100 crore
long-short book (Rs 50 crore a side, equal weight across the decile). The
preliminary measured an 8x-short MDE dominated by micro-caps that tripled or
collapsed inside a quarter; a spread that exists only in names the cost model
cannot trade fails kill criterion 2 anyway. Winsorisation is REPORTED as
robustness, never used for the primary.

CHAR_MATCHED here IS `outcomes.py`'s construction, not a mirror of it: the
ASOF cell at the entry date, the cell means, the self-excluded degradation
ladder and `min_names_per_cell` all come from `charmatch.py`, which both
consumers call. Until 2026-09-20 this module carried a second copy, kept
equal by hand and recorded as a cost; a hand-kept copy under a frozen spec
is how a registered study drifts from the table it claims to reproduce.
What is still this module's own is the PEER POOL — forward returns over
HORIZON sessions per identified security — because the study's horizon is
fixed and the outcome table's is a grid.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

import duckdb
import numpy as np
import pandas as pd

from src.common.paths import COLLECTED, DOCS, SEED, governance_db, research_db, warehouse_dir
from src.research import charmatch, power
from src.research.delisting import RECOVERY_FACTORS, STILL_TRADING_SESSIONS
from src.research.measure import identified_px_ctes

# _v2 (owner, 2026-10-08, option B): `exp_004_holdings_change` was registered
# at 20:16 IST that day by a coverage probe, without the owner's confirmation,
# with a coverage line read through a bug (2300/2290). It is RETIRED unrun; the
# primary key keeps the name, so the confirmed registration takes this one.
EXPERIMENT_ID = "exp_004_holdings_change_v2"
FAMILY = "TRACK_H_HOLDINGS"
HOLDINGS = COLLECTED / "shp" / "shp_holdings.parquet"
REPORT = DOCS / "reports" / "HOLDINGS_VERDICT.md"

HORIZON = 63
HORIZONS_REPORTED = (21, 63, 126, 252)
#: 0028's plausible bound, 0.5%/month, over a 63-session quarter.
BOUND = 0.005 * 3
FDR_ALPHA = 0.05
#: Owner decision 2026-09-29, before registration: at least 10 names in each
#: decile. It was 20 — two names a decile — and the quarters that met only
#: that were 2018-2021-Q2, when 13-40 early filers carried a filing each: pure
#: noise that set the MDE. The dispersion-only run (0035) at 50, 100 and 200
#: gave the SAME MDE (3.80%/quarter vs 10.30% at 20), because nothing sits
#: between 40 names and the 829 of 2021-Q3; 100 is the principled floor, not a
#: number tuned to an answer. The study therefore starts at 2021-Q3.
MIN_NAMES_PER_COHORT = 100
DECILE = 10
#: Owner decision 2026-09-18 (interval_policy = a). A change since the previous
#: filing that spans more than this is a resumption after a filing gap, not a
#: quarterly signal; 86 of 3,253 changes spanned 201-1,096 days on the sample.
INTERVAL_CAP_DAYS = 200

#: Kill criterion 4 (0076): a change between two filings is a CORPORATE ACTION,
#: not a holding decision, when shares outstanding moved by more than this.
#: Fixed 2026-10-02 before registration; the draft said "abnormal" and named
#: no number, which is a threshold the result would have chosen.
SHARE_CHANGE_FLAG = 0.05

#: The three tested signals: which parsed categories sum to each.
#: FPI is one series across two taxonomies: undivided to 2024, Cat I + II from
#: 2025. They never co-occur in a filing, so the sum is the series. FOREIGN
#: (all foreign institutions) has no counterpart in the old taxonomy and
#: starts where the new one does; its shorter depth is a fact of the data,
#: reported, not patched.
SIGNALS: dict[str, tuple[str, ...]] = {
    "FPI": ("FPI_Cat1", "FPI_Cat2", "FPI_Undivided"),
    "FOREIGN": ("ForeignInst_Total",),
    "MF": ("MutualFund",),
}

#: The tail rule's one declared parameter. Rs 100 crore long-short, Rs 50 crore
#: a side. A name is tradeable if 5 sessions at the pessimistic 5% of ADV20
#: absorb its equal-weight share of a side.
NOTIONAL_INR = 100 * 1e7
CAP_SESSIONS = 5
CAP_PCT_ADV = 0.05

#: CHAR_MATCHED IS DEFINED ONCE, IN charmatch.py (2026-09-20). This module
#: used to carry its own copy of the ladder, the cell minimum and the
#: self-exclusion, "mirrored" from outcomes.py — and a mirror kept by hand is
#: the way a registered study drifts from the table it claims to reproduce
#: after its spec is frozen. Now both consumers ask the same function.
MATCH_LEVELS = charmatch.MATCH_LEVELS


# --- half one: signals, from the holdings table only ---------------------------


def signals(path=HOLDINGS) -> pd.DataFrame:
    """One row per (ISIN, filing): the three signals as changes since the
    PREVIOUS filing, the interval between them, and the cohort quarter.

    Excluded here, and counted: filings whose identity_total is off by more
    than a point (a bad file), a company's first filing (no prior to
    difference), and changes spanning more than INTERVAL_CAP_DAYS. Off-cycle
    filings are KEPT; so are REVISED filings (owner decisions 2026-09-18,
    revised_policy = a): NSE's master replaces the original with the revision
    and keeps no copy, so the revision is the only version that exists, and
    its `broadcast_date` — the day the corrected figures became public — is
    the point-in-time entry. `revised` and `interval_days` ride on every row.
    """
    con = duckdb.connect()
    # ABSENT MEANS ZERO, WITHIN THE FILING'S OWN TAXONOMY. The 2020-2022
    # taxonomy writes every category, zeros included; V1.1+ omits a category
    # whose holding is zero. Without this a fund's EXIT (2% -> 0) reads as a
    # missing signal and drops out of exactly the decile it belongs in. The
    # old taxonomy has no foreign-institutions total at all, so FOREIGN stays
    # NULL there — a category the taxonomy cannot express is unknown, not zero.
    wide = con.execute(f"""
        SELECT isin, quarter_end, broadcast_date, is_calendar_quarter, revised, identity_total,
               COALESCE(SUM(CASE WHEN category IN ('FPI_Cat1','FPI_Cat2','FPI_Undivided') THEN pct_shares END), 0) AS fpi,
               CASE WHEN BOOL_OR(category = 'Institutions_Total_OldTaxonomy') THEN NULL
                    ELSE COALESCE(SUM(CASE WHEN category = 'ForeignInst_Total' THEN pct_shares END), 0) END AS foreign,
               COALESCE(SUM(CASE WHEN category = 'MutualFund' THEN pct_shares END), 0) AS mf,
               -- The holder-count twins (robustness only, never tested): the
               -- same members, counting holders instead of shares.
               COALESCE(SUM(CASE WHEN category IN ('FPI_Cat1','FPI_Cat2','FPI_Undivided') THEN num_shareholders END), 0) AS n_fpi,
               CASE WHEN BOOL_OR(category = 'Institutions_Total_OldTaxonomy') THEN NULL
                    ELSE COALESCE(SUM(CASE WHEN category = 'ForeignInst_Total' THEN num_shareholders END), 0) END AS n_foreign,
               COALESCE(SUM(CASE WHEN category = 'MutualFund' THEN num_shareholders END), 0) AS n_mf,
               -- Shares outstanding: the three top-level classes, as identity_total sums them.
               SUM(CASE WHEN lower(category_raw) IN ('shareholdingofpromoterandpromotergroupmember',
                       'publicshareholdingmember', 'nonpromoternonpublicmember') THEN num_shares END) AS shares
        FROM read_parquet('{path}')
        WHERE broadcast_date <> ''
        GROUP BY 1,2,3,4,5,6
    """).df()
    con.close()
    counts = {"filings": len(wide), "revised_kept": int(wide["revised"].sum())}
    ok = wide[wide["identity_total"].isna() | ((wide["identity_total"] - 100).abs() <= 1)].copy()
    counts["identity_excluded"] = len(wide) - len(ok)
    ok = ok.sort_values(["isin", "quarter_end"])
    prev = ok.groupby("isin").shift(1)
    ok["prev_quarter_end"] = prev["quarter_end"]
    for s in ("fpi", "foreign", "mf"):
        ok[f"d_{s}"] = ok[s] - prev[s]
        ok[f"d_n_{s}"] = ok[f"n_{s}"] - prev[f"n_{s}"]
    # KILL CRITERION 4's flag: the share count moved by more than
    # SHARE_CHANGE_FLAG between the two filings — a bonus, rights issue, QIP
    # or merger, where a holding's percentage moves without anyone trading.
    ok["share_change"] = ((ok["shares"] / prev["shares"] - 1).abs() > SHARE_CHANGE_FLAG).fillna(False)
    ok = ok[ok["prev_quarter_end"].notna()].copy()
    counts["first_filings_excluded"] = len(wide) - counts["identity_excluded"] - len(ok)
    ok["interval_days"] = (pd.to_datetime(ok["quarter_end"]) - pd.to_datetime(ok["prev_quarter_end"])).dt.days
    before = len(ok)
    ok = ok[ok["interval_days"] <= INTERVAL_CAP_DAYS].copy()
    counts["interval_excluded"] = before - len(ok)
    q = pd.to_datetime(ok["quarter_end"])
    ok["cohort"] = q.dt.year.astype(str) + "Q" + q.dt.quarter.astype(str)
    ok.attrs["counts"] = counts
    return ok.reset_index(drop=True)


# --- the guard ------------------------------------------------------------------


def registered_hash(env: str | None = None) -> str:
    con = sqlite3.connect(str(governance_db(env)))
    try:
        row = con.execute("SELECT spec_hash, status FROM experiment_registry WHERE experiment_id = ?",
                          (EXPERIMENT_ID,)).fetchone()
    except sqlite3.OperationalError:
        row = None
    finally:
        con.close()
    if not row or row[1] != "REGISTERED":
        raise RuntimeError(
            f"{EXPERIMENT_ID} is not REGISTERED (found {row}). This module joins signals to "
            f"forward returns and MUST NOT run before scripts/register_exp004.py has frozen the spec.")
    return row[0]


def market_series_sql(index_key: str = "NIFTY50") -> str:
    """The market leg: (d, close) for one index, COLLECTED FIRST, SEED FALLBACK.

    The seed's `global_indices_daily.parquet` ends 2026-07-07; the archive
    (`src/ingest/index_close.py`) runs 2021-10-18 -> today. Reconciled
    2026-09-18: zero difference on all 1,161 overlapping sessions, so the two
    are one series. The seed still supplies four sessions the archive lacks
    (three April-2023 files NSE dated MM-DD, refused rather than guessed, and
    the 2025-02-01 Saturday budget session) and everything before 2021-10-18.
    """
    collected = COLLECTED / "index_close" / "index_close.parquet"
    seed = f"{SEED}/global_indices_daily.parquet"
    return f"""
        SELECT d, close FROM (
            SELECT date AS d, close, 0 AS pri FROM read_parquet('{collected}') WHERE index_key = '{index_key}'
            UNION ALL
            SELECT CAST(date AS DATE) AS d, close, 1 AS pri FROM read_parquet('{seed}') WHERE symbol = '{index_key}'
        ) QUALIFY ROW_NUMBER() OVER (PARTITION BY d ORDER BY pri) = 1"""


def market_tri_sql(index_key: str = "NIFTY500") -> str:
    """The market leg as a TOTAL RETURN: (d, close) from `collected:index_tri`.

    WHY THE SECONDARY MEASURE MOVED TO THIS (0077). `mkt_rel` subtracts the
    market's return from the name's, and until 2026-09-19 the only market
    series available was a PRICE index — it omits dividends, so it understates
    what the market did and flatters every long-side result by the yield. On
    the NIFTY 500 that is ~1.2%/yr, ~0.3% per quarter, against this study's own
    plausible-effect bound of 1.5% per quarter. A fifth of the bound, from a
    column that was never the thing it was being used as.

    benchmarks.yml has named NIFTY500_TR its `headline_index` since 2026-08-18
    and pointed at a table nothing wrote; this is that table, at last. One
    source, no fallback and no union: the series starts 1995-01-01, decades
    before anything else here, so there is nothing to fall back TO.

    `tri`, never `ntr` — see `src/warehouse/benchmarks._nifty500_tri_sql`.
    """
    tri = COLLECTED / "index_tri" / "index_tri.parquet"
    return f"""
        SELECT date AS d, tri AS close
        FROM read_parquet('{tri}')
        WHERE index_key = '{index_key}' AND tri > 0"""


# --- half two: the panel, behind the guard ------------------------------------


#: The signal columns the panel carries: the three tested signals, their
#: holder-count twins (robustness, reported never tested) and the
#: share-count-change flag kill criterion 4 reads.
SIGNAL_COLS = ["d_fpi", "d_foreign", "d_mf", "d_n_fpi", "d_n_foreign", "d_n_mf", "share_change"]


def panel(env: str | None = None, sig: pd.DataFrame | None = None,
          horizon: int = HORIZON) -> pd.DataFrame:
    """Signals joined to entry, the exit at `horizon` sessions (`price_exits`),
    the CHAR_MATCHED benchmark and the tradeable flag. Refuses to run
    unregistered.

    EVERY ROW THAT DOES NOT REACH THE PANEL IS COUNTED BY REASON, as the
    spec's universe definition promises (`.attrs["counts"]`): no security
    for the ISIN, no EQ session after broadcast, a window still open
    (CENSORED). The first version dropped all three in inner joins."""
    from src.ingest.listing_history import closes as allseries_closes

    registered_hash(env)
    sig = sig if sig is not None else signals()
    spine = str(warehouse_dir(env) / "price_spine_adj" / "**" / "*.parquet")
    raw = str(warehouse_dir(env) / "price_spine" / "**" / "*.parquet")
    charp = str(warehouse_dir(env) / "char_panel" / "**" / "*.parquet")
    min_cell = charmatch.min_names_per_cell()
    counts: dict[str, int] = {"signal_rows": len(sig)}
    con = duckdb.connect(str(research_db(env)), read_only=True)
    try:
        con.register("sig", sig[["isin", "quarter_end", "broadcast_date", "cohort", "interval_days",
                                 "is_calendar_quarter", *SIGNAL_COLS]])
        con.execute(f"""CREATE TEMP TABLE ordered AS
            WITH {identified_px_ctes(spine)}
            SELECT security_id, symbol, CAST(date AS DATE) AS d, open, close,
                   median(close * volume) OVER (PARTITION BY security_id ORDER BY date
                                                ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) AS adv20,
                   ROW_NUMBER() OVER (PARTITION BY security_id ORDER BY date) AS rn
            FROM sec""")
        counts["excluded_no_security"] = con.execute(
            "SELECT COUNT(*) FROM sig s LEFT JOIN security_master m ON m.isin = s.isin"
            " WHERE m.isin IS NULL").fetchone()[0]
        con.execute(f"""CREATE TEMP TABLE ev AS
            SELECT s.*, m.security_id, o.symbol, o.d AS entry_date, o.open AS entry_open,
                   o.rn AS entry_rn, o.adv20, r.open AS entry_open_raw
            FROM sig s
            JOIN security_master m ON m.isin = s.isin
            JOIN ordered o ON o.security_id = m.security_id AND o.d > CAST(s.broadcast_date AS DATE)
            LEFT JOIN (SELECT UPPER(TRIM(symbol)) AS symbol, CAST(date AS DATE) AS d, open
                       FROM read_parquet('{raw}')) r ON r.symbol = o.symbol AND r.d = o.d
            QUALIFY ROW_NUMBER() OVER (PARTITION BY s.isin, s.quarter_end ORDER BY o.d) = 1""")
        n_ev = con.execute("SELECT COUNT(*) FROM ev").fetchone()[0]
        counts["excluded_no_eq_session_after_broadcast"] = (
            len(sig) - counts["excluded_no_security"] - n_ev)
        evdf = con.execute(f"""
            WITH last AS (
                SELECT security_id, MAX(d) AS last_eq_date,
                       arg_max(close, d) AS last_eq_close FROM ordered GROUP BY 1)
            SELECT e.isin, e.quarter_end, e.symbol, e.entry_date, e.entry_open,
                   COALESCE(e.entry_open_raw, e.entry_open) AS entry_open_raw,
                   x.d AS own_exit_date, x.close AS own_exit_close,
                   l.last_eq_date, l.last_eq_close
            FROM ev e
            LEFT JOIN ordered x ON x.security_id = e.security_id AND x.rn = e.entry_rn + {horizon}
            JOIN last l ON l.security_id = e.security_id""").df()
        calendar = [r[0] for r in con.execute("SELECT DISTINCT d FROM ordered ORDER BY d").fetchall()]
        # Trades after a name left EQ: the same symbol in EQ under a new ISIN
        # (adjusted spine) and every other series (raw bhavcopy). Read only for
        # the names that need them.
        gone = evdf[evdf["own_exit_close"].isna()]
        later = pd.DataFrame(columns=["symbol", "d", "close", "adjusted"])
        if len(gone):
            syms = set(gone["symbol"])
            con.register("gone_syms", pd.DataFrame({"symbol": sorted(syms)}))
            eq_later = con.execute(
                "SELECT symbol, d, close, TRUE AS adjusted FROM ordered"
                " WHERE symbol IN (SELECT symbol FROM gone_syms)").df()
            lo = str(gone["last_eq_date"].min())
            other = pd.DataFrame(allseries_closes(syms, lo, str(calendar[-1]) if calendar else lo),
                                 columns=["symbol", "series", "isin", "d", "close"])
            other = other[other["series"] != "EQ"]
            other = other.assign(d=pd.to_datetime(other["d"]).dt.date, adjusted=False)[
                ["symbol", "d", "close", "adjusted"]]
            later = pd.concat([eq_later, other], ignore_index=True)
            # One price per (symbol, session): the adjusted EQ row when both exist.
            later = (later.sort_values("adjusted", ascending=False)
                     .drop_duplicates(["symbol", "d"]).reset_index(drop=True))
        # One date type throughout: DuckDB hands pandas timestamps and the
        # calendar plain dates, and a bisect across the two silently misses.
        for c in ("entry_date", "own_exit_date", "last_eq_date"):
            evdf[c] = [None if pd.isna(x) else pd.Timestamp(x).date() for x in evdf[c]]
        later["d"] = [pd.Timestamp(x).date() for x in later["d"]]
        priced = price_exits(evdf, calendar, later, horizon)
        by_reason = priced["exit_reason"].value_counts().to_dict() if len(priced) else {}
        for k in ("HORIZON", "MOVED", "STOPPED", "CENSORED"):
            counts[f"exit_{k.lower()}"] = int(by_reason.get(k, 0))
        priced = priced[priced["exit_reason"] != "CENSORED"].copy()
        # The market leg runs over the WINDOW, whatever the name did inside it.
        priced["window_end"] = [
            r.own_exit_date if r.exit_reason == "HORIZON"
            else calendar[min(calendar.index(r.entry_date) + horizon, len(calendar) - 1)]
            for r in priced.itertuples()]
        con.register("px_exit", priced[["isin", "quarter_end", "exit_reason", "exit_date", "window_end",
                                        "ret", *[c for c in priced.columns if c.startswith("ret_rf")]]])
        # CHAR_MATCHED, on outcomes.py's construction (see the module docstring).
        con.execute("CREATE TEMP TABLE cellmap AS " + charmatch.cellmap_sql(
            "SELECT DISTINCT symbol, d FROM ordered WHERE d IN (SELECT DISTINCT entry_date FROM ev)", charp))
        con.execute(f"""CREATE TEMP TABLE cells AS
            WITH f AS (SELECT symbol, d, LEAD(close, {horizon}) OVER (PARTITION BY security_id ORDER BY d)
                                         / open - 1 AS ret FROM ordered)
            SELECT f.symbol, f.d, f.ret, c.size_q, c.mom_q, c.vol_q
            FROM f JOIN cellmap c ON c.symbol = f.symbol AND c.d = f.d
            WHERE f.ret IS NOT NULL""")
        for level, keys in MATCH_LEVELS:
            con.execute(f"CREATE TEMP TABLE cm_{level} AS " + charmatch.cell_means_sql(level, keys))
        lad = charmatch.ladder(min_cell, event="ec", own="own")
        # The headline index, total return (0077). `market_series_sql` is the
        # price leg and is kept for anything that needs NIFTY 50 specifically.
        con.execute(f"CREATE TEMP TABLE mkt AS {market_tri_sql()}")
        rf_cols = ", ".join(f"f.{c} - ({lad.bench}) AS char_rel_{c[4:]}"
                            for c in priced.columns if c.startswith("ret_rf"))
        df = con.execute(f"""
            SELECT e.isin, e.quarter_end, e.cohort, e.interval_days, e.is_calendar_quarter,
                   {", ".join(f"e.{c}" for c in SIGNAL_COLS)},
                   e.entry_date, f.exit_date, f.exit_reason, e.adv20,
                   f.ret AS raw_ret,
                   f.ret - (mx.close / me.close - 1) AS mkt_rel,
                   f.ret - ({lad.bench}) AS char_rel,
                   {rf_cols + "," if rf_cols else ""}
                   {lad.match_level} AS match_level,
                   ec.size_q, ec.mom_q, ec.vol_q
            FROM ev e
            JOIN px_exit f ON f.isin = e.isin AND f.quarter_end = e.quarter_end
            LEFT JOIN mkt me ON me.d = e.entry_date
            LEFT JOIN mkt mx ON mx.d = f.window_end
            LEFT JOIN cellmap ec ON ec.symbol = e.symbol AND ec.d = e.entry_date
            LEFT JOIN cells own ON own.symbol = e.symbol AND own.d = e.entry_date
            {lad.joins}
        """).df()
    finally:
        con.close()
    counts["excluded_no_char_match"] = int(df["char_rel"].isna().sum())
    out = tradeable(df)
    out.attrs["counts"] = counts
    return out


def tradeable(df: pd.DataFrame) -> pd.DataFrame:
    """THE TAIL RULE. Per cohort, the per-name notional is a side divided by the
    decile size; a name is tradeable if CAP_SESSIONS x CAP_PCT_ADV x ADV20 covers it.
    Decided per cohort from the names IN that cohort, so the rule does not
    depend on the full-panel size."""
    out = df.copy()
    n = out.groupby("cohort")["isin"].transform("count")
    per_name = (NOTIONAL_INR / 2) / (n // DECILE).clip(lower=2)
    out["tradeable"] = (CAP_SESSIONS * CAP_PCT_ADV * out["adv20"]) >= per_name
    return out


# --- exits, pure: what a name returned when it did not reach the horizon -------


def price_exits(ev: pd.DataFrame, calendar: list, later: pd.DataFrame, h: int) -> pd.DataFrame:
    """Every event's exit at `h` sessions, including the names that left.

    THE OWNER'S DECISION 2026-10-02 (0076). The draft's universe required 63
    sessions after entry, and its exit policy cited 0052; the two contradict,
    and the first is survivorship: of 26,443 filing pairs, 111 stopped trading
    in EQ inside the window — 105 MOVED to the BE/BZ surveillance series
    (0082's LEFT_UNIVERSE), usually after bad news, and kept trading there.
    Dropping them is the silent drop Plan 2 §3.4 says was worth the whole
    effect in MICCV2. So:

      HORIZON   the name's own h-th session after entry exists in EQ.
      MOVED     it left EQ and was still trading at the exit date — under the
                same symbol in EQ as a new ISIN (adjusted spine, so the entry
                is the adjusted open) or in another series (raw bhavcopy, so
                the entry is the RAW open). Exit = its last close on or before
                the calendar exit date.
      STOPPED   no trade anywhere on or after the exit date. 0052: last close
                x recovery factor; rf 0.0 is the headline, 0.25 and 0.50
                reported. The last close is the latest of EQ and later trades.
      CENSORED  the window runs past the data — the calendar has no session
                h after entry, or the name still trades in EQ but has not had
                h sessions yet. No outcome exists; excluded and counted.

    `ev` columns: entry_date, entry_open, entry_open_raw, own_exit_date,
    own_exit_close, last_eq_date, last_eq_close, symbol (+ any keys).
    `calendar`: sorted session dates (the market's). `later`: symbol, d,
    close, adjusted — trades after the name left EQ.
    Returns `ev` + exit_reason, exit_date, ret, and ret_rf{25,50} for the
    reported recovery factors (equal to ret except for STOPPED).
    """
    from bisect import bisect_left

    cal = list(calendar)
    end = cal[-1] if cal else None
    alive_line = cal[-1 - STILL_TRADING_SESSIONS] if len(cal) > STILL_TRADING_SESSIONS else None
    by_sym = {s: g.sort_values("d") for s, g in later.groupby("symbol")} if len(later) else {}
    rows = []
    for r in ev.itertuples(index=False):
        rec = r._asdict()
        rf_ret = {}
        i = bisect_left(cal, r.entry_date)
        cal_exit = cal[i + h] if i < len(cal) and cal[i] == r.entry_date and i + h < len(cal) else None
        if pd.notna(r.own_exit_close):
            reason, exit_d, ret = "HORIZON", r.own_exit_date, r.own_exit_close / r.entry_open - 1
        elif cal_exit is None or (alive_line is not None and r.last_eq_date >= alive_line):
            reason, exit_d, ret = "CENSORED", None, float("nan")
        else:
            g = by_sym.get(r.symbol)
            g = g[g["d"] > r.last_eq_date] if g is not None else None
            if g is not None and len(g) and (g["d"] >= cal_exit).any():
                last = g[g["d"] <= cal_exit].iloc[-1] if (g["d"] <= cal_exit).any() else g.iloc[0]
                base = r.entry_open if bool(last["adjusted"]) else r.entry_open_raw
                reason, exit_d, ret = "MOVED", last["d"], float(last["close"]) / base - 1
            else:
                if g is not None and len(g):
                    last = g.iloc[-1]
                    px, base, exit_d = (float(last["close"]),
                                        r.entry_open if bool(last["adjusted"]) else r.entry_open_raw,
                                        last["d"])
                else:
                    px, base, exit_d = r.last_eq_close, r.entry_open, r.last_eq_date
                reason = "STOPPED"
                ret = px * RECOVERY_FACTORS[0] / base - 1
                rf_ret = {f: px * f / base - 1 for f in RECOVERY_FACTORS[1:]}
        rec.update(exit_reason=reason, exit_date=exit_d, ret=ret)
        for f in RECOVERY_FACTORS[1:]:
            rec[f"ret_rf{int(round(f * 100))}"] = rf_ret.get(f, ret)
        rows.append(rec)
    out = pd.DataFrame(rows)
    out.attrs["data_end"] = end
    return out


# --- the estimator, pure --------------------------------------------------------


@dataclass
class TestResult:
    signal: str
    outcome: str
    n_cohorts: int
    n_names: int
    spread_mean: float
    spread_se: float          # serial-corrected
    t: float
    p_perm: float
    q_fdr: float = float("nan")
    mde: float = float("nan")
    ci_low: float = float("nan")    # 95%, moving-block bootstrap over cohorts
    ci_high: float = float("nan")
    cohorts: pd.Series = field(default_factory=pd.Series, repr=False)

    @property
    def clears_bound(self) -> bool:
        return abs(self.spread_mean) > BOUND and self.mde <= BOUND


def decile_spreads(df: pd.DataFrame, signal_col: str, outcome_col: str) -> pd.Series:
    """Per cohort: mean outcome of the top decile of `signal_col` minus the bottom.
    Cohorts with fewer than MIN_NAMES_PER_COHORT names are dropped, not padded."""
    out = {}
    for cohort, g in df.dropna(subset=[signal_col, outcome_col]).groupby("cohort"):
        if len(g) < MIN_NAMES_PER_COHORT:
            continue
        g = g.sort_values(signal_col)
        k = max(2, len(g) // DECILE)
        out[cohort] = float(g[outcome_col].iloc[-k:].mean() - g[outcome_col].iloc[:k].mean())
    return pd.Series(out).sort_index()


#: The spec's permutation_policy: "Moving-block bootstrap over cohorts (block 2)
#: for the CI". Block 2 keeps adjacent quarters together, because a 63-session
#: holding overlaps the next cohort's window and the spreads are serially
#: correlated (the same reason the SE carries the Bartlett correction).
BOOT_BLOCK = 2
BOOT_DRAWS = 1000


def block_bootstrap_ci(x: pd.Series, block: int = BOOT_BLOCK, draws: int = BOOT_DRAWS,
                       seed: int = 20260918, level: float = 0.95) -> tuple[float, float]:
    """Percentile CI of the mean of `x` (cohort spreads in time order) by
    moving-block bootstrap: resample overlapping blocks of `block` consecutive
    cohorts with replacement until the series length is reached."""
    v = x.to_numpy(dtype=float)
    n = len(v)
    if n < block + 1:
        return float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    starts = np.arange(n - block + 1)
    k = int(np.ceil(n / block))
    means = np.empty(draws)
    for i in range(draws):
        idx = (rng.choice(starts, size=k)[:, None] + np.arange(block)).ravel()[:n]
        means[i] = v[idx].mean()
    a = (1 - level) / 2
    return float(np.quantile(means, a)), float(np.quantile(means, 1 - a))


def _test(df, signal_col, outcome_col, permutations=1000, seed=20260918) -> TestResult:
    rng = np.random.default_rng(seed)
    cohorts = decile_spreads(df, signal_col, outcome_col)
    if len(cohorts) < 2:
        raise RuntimeError(f"{signal_col}: only {len(cohorts)} cohort(s) with >= {MIN_NAMES_PER_COHORT} names")
    mean = float(cohorts.mean())
    infl, _ = power.serial_inflation(cohorts, label_periods=1)
    se = float(cohorts.std(ddof=1) / np.sqrt(len(cohorts)) * np.sqrt(infl))
    mde = power.mde_serial_corrected(cohorts, label_periods=1)
    # WITHIN-COHORT LABEL PERMUTATION: the signal is shuffled among the names
    # of each cohort, so cohort composition and outcome dispersion are kept
    # and only the ranking is destroyed.
    obs = abs(mean)
    hits = 0
    work = df.dropna(subset=[signal_col, outcome_col]).copy()
    for _ in range(permutations):
        work[signal_col + "_p"] = work.groupby("cohort")[signal_col].transform(lambda s: rng.permutation(s.to_numpy()))
        if abs(decile_spreads(work, signal_col + "_p", outcome_col).mean()) >= obs:
            hits += 1
    p_perm = (hits + 1) / (permutations + 1)
    n_names = int(work.groupby("cohort").size().loc[cohorts.index].sum())
    lo, hi = block_bootstrap_ci(cohorts, seed=seed)
    return TestResult(signal_col, outcome_col, len(cohorts), n_names, mean, se,
                      mean / se if se > 0 else float("nan"), p_perm, mde=mde,
                      ci_low=lo, ci_high=hi, cohorts=cohorts)


def bh(results: list[TestResult]) -> None:
    ordered = sorted(results, key=lambda r: r.p_perm)
    m = len(ordered)
    running = 1.0
    for rank in range(m, 0, -1):
        r = ordered[rank - 1]
        running = min(running, r.p_perm * m / rank)
        r.q_fdr = min(running, 1.0)


# --- run: guarded -----------------------------------------------------------------


#: Robustness section names. verdict() reads the kill criteria by these keys.
KILL2 = "untradeable names only (kill 2: liquidity)"
KILL3 = "raw_return (kill 3: momentum)"
KILL4 = "without share-count changes (kill 4: corporate action)"


def winsorise(x: pd.Series, lo: float = 0.01, hi: float = 0.99) -> pd.Series:
    """Clip at the POOLED 1st/99th percentiles — the tail_rule's robustness."""
    return x.clip(x.quantile(lo), x.quantile(hi))


def run(env: str | None = None, permutations: int = 1000) -> tuple[str, list[TestResult], dict]:
    """The registered study: three tests on the primary, then EVERY robustness
    line the spec promises, each reported and never tested (200 permutations,
    no family charge). Until 2026-10-02 the spec named seven of these and the
    code computed three; the rehearsal for registration found it (0076)."""
    sh = registered_hash(env)
    sig = signals()
    pnl = panel(env, sig)
    prim = pnl[pnl["tradeable"] & pnl["char_rel"].notna()].copy()
    results = [_test(prim, f"d_{s.lower()}", "char_rel", permutations) for s in SIGNALS]
    bh(results)
    sigs = [s.lower() for s in SIGNALS]

    def each(df, outcome, cols=None):
        return [_test(df, c, outcome, 200) for c in (cols or [f"d_{s}" for s in sigs])]

    prim["char_rel_w"] = winsorise(prim["char_rel"])
    robustness = {
        KILL3: each(prim, "raw_ret"),
        KILL2: each(pnl[(~pnl["tradeable"]) & pnl["char_rel"].notna()], "char_rel"),
        KILL4: each(prim[~prim["share_change"].astype(bool)], "char_rel"),
        "calendar filings only": each(prim[prim["is_calendar_quarter"]], "char_rel"),
        "market-relative (NIFTY 500 TR)": each(prim[prim["mkt_rel"].notna()], "mkt_rel"),
        "winsorised 1st/99th": each(prim, "char_rel_w"),
        "holder-count signal": each(prim, "char_rel", [f"d_n_{s}" for s in sigs]),
    }
    for c in [c for c in prim.columns if c.startswith("char_rel_rf")]:
        robustness[f"stopped names at recovery factor 0.{c[-2:]}"] = each(prim, c)
    for hz in [x for x in HORIZONS_REPORTED if x != HORIZON]:
        other = panel(env, sig, hz)
        robustness[f"horizon {hz} sessions"] = each(other[other["tradeable"] & other["char_rel"].notna()],
                                                     "char_rel")
    thin = prim.groupby("cohort").size()
    counts = {**sig.attrs["counts"], **pnl.attrs.get("counts", {}),
              "panel_rows": len(pnl), "tradeable": int(pnl["tradeable"].sum()),
              "untradeable": int((~pnl["tradeable"]).sum()),
              "with_char_match": int(pnl["char_rel"].notna().sum()),
              "share_change_rows": int(prim["share_change"].astype(bool).sum()),
              "cohorts_below_min_names": int((thin < MIN_NAMES_PER_COHORT).sum())}
    return sh, results, {"robustness": robustness, "counts": counts, "panel": pnl}


# --- verdict, gate, report, charge -------------------------------------------------


@dataclass
class Verdict:
    landing: str                      # POWERED_ALIVE / POWERED_DEAD / UNDERPOWERED
    reasons: list[str]
    event_gate: dict[str, bool]       # per signal
    portfolio_gate: dict[str, float]  # per signal: net-of-cost spread at the pessimistic level
    kills: dict[str, list[str]]       # per signal: kill criteria tripped


def net_of_costs(spread: float, cohorts: int, avg_adv: float, notional: float = NOTIONAL_INR) -> float:
    """The portfolio gate (0003): the decile spread minus the PESSIMISTIC
    round-trip cost of building and unwinding both sides, per quarter.

    Turnover per quarter is the whole book (every name is replaced when the
    deciles are re-ranked — the conservative assumption, since some names stay).
    Impact uses the mean ADV of the tradeable names; per-name quantity is the
    equal-weight share of a side. sigma_daily 2% is costs.yml's small-cap
    default; the registered run reports the realised figure alongside.
    """
    from datetime import date

    from src.research import costs
    per_name = (notional / 2) / max(2, cohorts // DECILE if cohorts else 2)
    sc = costs.cost_scenarios(turnover=notional, on=date.today(), quantity=per_name,
                              adv=avg_adv if avg_adv and avg_adv > 0 else 1.0, sigma_daily=0.02)
    pess = next(s for s in sc.scenarios if s.name == "pessimistic")
    return spread - pess.total_bps / 10_000 * 2  # long AND short legs each pay


def verdict(results: list[TestResult], robustness: dict, panel: pd.DataFrame) -> Verdict:
    avg_adv = float(panel.loc[panel["tradeable"], "adv20"].mean()) if "adv20" in panel else 0.0
    names_per_cohort = int(panel[panel["tradeable"]].groupby("cohort").size().median()) if len(panel) else 0
    event, port, kills = {}, {}, {}
    raw = {r.signal: r for r in robustness.get(KILL3, [])}
    untr = {r.signal: r for r in robustness.get(KILL2, [])}
    noca = {r.signal: r for r in robustness.get(KILL4, [])}
    for r in results:
        k = []
        if r.mde > BOUND:
            k.append(f"kill 1: MDE {r.mde:.2%} > bound {BOUND:.2%} — UNDERPOWERED")
        u = untr.get(r.signal)
        if u is not None and abs(u.spread_mean) > BOUND and abs(r.spread_mean) < BOUND / 2:
            k.append("kill 2: spread lives in the untradeable names, absent in the tradeable")
        w = raw.get(r.signal)
        if w is not None and abs(w.spread_mean) > BOUND and abs(r.spread_mean) < BOUND / 2:
            k.append("kill 3: spread present in raw returns, absent under CHAR_MATCHED — momentum")
        x = noca.get(r.signal)
        if x is not None and abs(r.spread_mean) > BOUND and abs(x.spread_mean) < BOUND / 2:
            k.append("kill 4: spread vanishes without the share-count changes — corporate action")
        kills[r.signal] = k
        event[r.signal] = (abs(r.spread_mean) > BOUND and r.mde <= BOUND
                           and not np.isnan(r.q_fdr) and r.q_fdr < FDR_ALPHA)
        port[r.signal] = net_of_costs(r.spread_mean, names_per_cohort, avg_adv)
    if all(r.mde > BOUND for r in results):
        landing = "UNDERPOWERED"
        reasons = [f"every signal's MDE exceeds the bound; smallest ratio "
                   f"{min(r.mde for r in results) / BOUND:.2f}x. No fit is run."]
    elif any(event[s] and port[s] > 0 for s in event):
        landing = "POWERED_ALIVE"
        reasons = [f"{s}: event gate passed (q={next(r for r in results if r.signal == s).q_fdr:.3f}) "
                   f"and net-of-cost spread {port[s]:+.2%}" for s in event if event[s] and port[s] > 0]
    else:
        landing = "POWERED_DEAD"
        reasons = [f"{r.signal}: spread {r.spread_mean:+.2%}, q={r.q_fdr:.3f}, MDE {r.mde:.2%}, "
                   f"net {port[r.signal]:+.2%}" for r in results]
    return Verdict(landing, reasons, event, port, kills)


def render(sh: str, results: list[TestResult], extra: dict, v: Verdict) -> str:
    L = [f"# HOLDINGS_VERDICT.md — exp_004 landing: **{v.landing}**", "",
         f"**Generated by `python -m src.research.holdings` against the registered spec "
         f"(`spec_hash {sh[:12]}…`, decision 0076). Three tests, BH-FDR {FDR_ALPHA:.0%}, "
         f"primary CHAR_MATCHED at {HORIZON} sessions, tail rule = participation cap.**", ""]
    L += ["## Landing", ""] + [f"- {r}" for r in v.reasons] + [""]
    L += ["## Primary", "", "| signal | cohorts | names | spread | 95% CI (block bootstrap) | SE (serial) | t | p (perm) | q (BH) | MDE | bound | net of cost | event gate |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in results:
        L.append(f"| {r.signal} | {r.n_cohorts} | {r.n_names:,} | {r.spread_mean:+.2%} | "
                 f"[{r.ci_low:+.2%}, {r.ci_high:+.2%}] | {r.spread_se:.2%} | {r.t:.2f} | "
                 f"{r.p_perm:.3f} | {r.q_fdr:.3f} | {r.mde:.2%} | {BOUND:.2%} | {v.portfolio_gate[r.signal]:+.2%} | "
                 f"{'PASS' if v.event_gate[r.signal] else 'fail'} |")
    L += ["", "## Kill criteria", ""]
    for s, ks in v.kills.items():
        L += [f"- **{s}**: " + ("; ".join(ks) if ks else "none tripped")]
    L += ["", "## Robustness (reported, never tested)", ""]
    for name, rs in extra.get("robustness", {}).items():
        L += [f"### {name}", "", "| signal | cohorts | spread | 95% CI | p (perm) | MDE |", "|---|---|---|---|---|---|"]
        L += [f"| {r.signal} | {r.n_cohorts} | {r.spread_mean:+.2%} | [{r.ci_low:+.2%}, {r.ci_high:+.2%}] | "
              f"{r.p_perm:.3f} | {r.mde:.2%} |" for r in rs] + [""]
    L += ["## Counts — every row that left, by reason", ""] + [f"- {k}: {v_:,}" if isinstance(v_, int) else f"- {k}: {v_}" for k, v_ in extra.get("counts", {}).items()]
    return "\n".join(L) + "\n"


def main() -> int:
    from src.research import families
    sh, results, extra = run()
    pnl = extra.get("panel")
    v = verdict(results, extra["robustness"], pnl if pnl is not None else pd.DataFrame())
    text = render(sh, results, extra, v)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(text)
    print(text)
    # ONE charge, the declared width: three tests. The robustness rows are
    # reported and never tested, and do not widen the family.
    charge = families.commit_charge(FAMILY, trials_added=len(results),
                                    description=f"exp_004 primary: {len(results)} signals x 1 horizon, spec {sh[:12]}",
                                    experiment_id=EXPERIMENT_ID)
    print(f"\n  charged {FAMILY}: +{len(results)} trials -> {charge.trials_after}")
    print(f"  wrote {REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
