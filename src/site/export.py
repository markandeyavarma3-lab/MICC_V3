"""export.py — the public website's data, written nightly as static JSON.

docs/plan/WEBSITE_PLAN.md. The site (a separate repository, research-website) is a
static Astro build; everything it shows comes from these files, written by
this module from the warehouse after the collector finishes.

WHAT IT WRITES under <out>/ (default: ../research-website/public/data):
  meta.json                 built_at, latest session, data health, counts
  sessions.json             [{date, deals, bulk, block, roundtrip_share}] newest first
  sessions/<YYYY-MM-DD>.json one session: deals with our participant labels,
                            FII/DII cash flows (where held), F&O positioning

WHAT IT NEVER WRITES (the plan's §1 and §7):
  * a forward return, a return after an event, a ranking by returns, or any
    signal — this is the SEBI line and the owner's ("no suggestions")
  * anything from Kite Connect (personal-use data, decision 0087): the
    exporter reads no Kite table, and a test asserts it

Deals are labelled through the RAW client name -> participant_aliases ->
participant_master: participant_id is reassigned on every rebuild (0083),
names are stable.
"""

from __future__ import annotations

import bisect
import gzip
import hashlib
import json
import math
import re
import sys
from collections import Counter, defaultdict
from datetime import UTC, date, datetime
from functools import lru_cache
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import duckdb  # noqa: E402

from src.common.paths import (  # noqa: E402
    ARCHIVE,
    COLLECTED,
    ROOT,
    SEED,
    research_db,
    warehouse_dir,
)
from src.site import labels, sme_prices  # noqa: E402

SITE_DATA = ROOT.parent / "research-website" / "public" / "data"
CR = 1e7   # rupees per crore

#: Display labels for participant types. The type codes stay in the data.
TYPE_LABEL = {
    "PROP_HFT": "HFT / round-trip", "MUTUAL_FUND": "Mutual fund", "FPI_OFFSHORE": "Foreign (offshore)",
    "FOREIGN_INSTITUTION": "Foreign institution", "BANK": "Bank", "INSURANCE": "Insurance",
    "PENSION_SOVEREIGN": "Pension / sovereign", "BROKER_SEC": "Broker", "AIF_PMS": "AIF / PMS",
    "FAMILY_OFFICE": "Family office", "PROMOTER_GROUP": "Promoter group", "CORPORATE": "Corporate",
    "GOVERNMENT": "Government", "INDIVIDUAL": "Individual", "UNKNOWN": "Unclassified",
}


def slug(name: str) -> str:
    """A stable, URL-safe file name: readable stem plus 6 hex of the full name,
    so two names that clean to the same stem never share a file."""
    stem = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")[:48] or "x"
    return f"{stem}-{hashlib.sha1((name or '').encode()).hexdigest()[:6]}"


def house_name(raw: str | None) -> str | None:
    """'FUND HOUSE SBI_FUNDS' -> 'SBI Funds': the group row's canonical name is
    an internal key (configs/fund_houses.yml), not a label for readers."""
    if not raw:
        return None
    key = re.sub(r"^FUND HOUSE\s+", "", raw).replace("_", " ")
    return " ".join(w if w in ("SBI", "HDFC", "ICICI", "UTI", "DSP", "IDFC", "LIC", "HSBC", "PPFAS", "JM",
                                "LNT", "AMC", "IIFL", "PGIM", "ITI", "NJ", "WOC", "BNP") else w.title()
                    for w in key.split())


def sym_file(sym: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "_", sym or "x")


SESSION_COLS = ["sym", "sid", "co", "client", "who", "pid", "type", "label", "how", "house",
                "side", "qty", "px", "cr", "ex", "kind", "rt"]

#: Ownership series shown on a stock page, from the SHP filings (share of equity, %).
OWNERSHIP = {
    "promoter": ("Promoter",), "fpi": ("FPI_Cat1", "FPI_Cat2", "FPI_Undivided"),
    "foreign_inst": ("ForeignInst_Total",), "mf": ("MutualFund",), "insurance": ("Insurance",),
    "aif": ("AIF",), "individual": ("Individual",),
}


def _deals_sql() -> str:
    return """
        SELECT CAST(c.trade_date AS VARCHAR) AS d, UPPER(TRIM(r.symbol_raw)) AS sym,
               sm.isin, sm.company_name, r.client_name_raw AS client,
               pm.canonical_name AS pname, pm.participant_type AS ptype,
               pm.classification_method AS method, fh.canonical_name AS house,
               c.side, c.quantity, c.deal_price, c.gross_deal_value, c.exchange, c.deal_type,
               c.same_day_round_trip_flag AS rt, c.eligible_for_research AS elig
        FROM institutional_deals_clean c
        JOIN institutional_deals_raw r USING (raw_deal_id)
        LEFT JOIN security_master sm USING (security_id)
        LEFT JOIN participant_aliases pa ON pa.raw_name = r.client_name_raw
        LEFT JOIN participant_master pm ON pm.participant_id = pa.participant_id
        LEFT JOIN participant_master fh ON fh.participant_id = pm.parent_group_id
        ORDER BY d, c.gross_deal_value DESC
    """


@lru_cache(maxsize=1)
def site_labels() -> dict[str, str]:
    return labels.load()


def _deal(row) -> dict:
    (_d, sym, isin, company, client, pname, ptype, method, house, side, qty, px, val,
     exch, kind, rt, elig) = row
    t = ptype or "UNKNOWN"
    fixed = site_labels().get(pname)  # the page's label only; the research table keeps its own (src/site/labels.py)
    if fixed:
        t, method = fixed, labels.METHOD
    return {"sym": sym, "sid": sym_file(sym), "isin": isin, "co": company, "client": client,
            "who": pname or client, "pid": slug(pname or client),
            "type": t, "label": TYPE_LABEL.get(t, t), "how": method, "house": house_name(house),
            "side": side, "qty": qty, "px": None if px is None else round(px, 2),
            "cr": None if val is None else round(val / CR, 2),
            "ex": exch, "kind": kind, "rt": bool(rt), "elig": bool(elig)}


def fii_dii(archive: Path | None = None) -> dict[str, dict]:
    """session -> {FII: net, DII: net} in Rs crore, from NSE's archived JSON.
    The path resolves at call time, never in the signature (the runreport.py
    and kite.py lesson: a default bound at import ignores a patched ARCHIVE)."""
    archive = archive or ARCHIVE
    out: dict[str, dict] = {}
    for f in sorted((archive / "FII_DII").glob("**/*.json.gz")):
        try:
            rows = json.loads(gzip.decompress(f.read_bytes()))
        except (OSError, ValueError):
            continue
        for r in rows if isinstance(rows, list) else []:
            try:
                d = datetime.strptime(r["date"], "%d-%b-%Y").date().isoformat()
                cat = "FII" if r["category"].startswith("FII") else r["category"]
                out.setdefault(d, {})[cat] = {k: float(r[k]) for k in ("buyValue", "sellValue", "netValue")}
            except (KeyError, ValueError):
                continue
    return out


def participant_oi(con) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    for d, cat, ifl, ifs, ifn, sfn in con.execute("""
            SELECT CAST(session_date AS VARCHAR), category, index_fut_long, index_fut_short,
                   index_fut_net, stock_fut_net FROM participant_oi
            WHERE category <> 'TOTAL' ORDER BY 1, 2""").fetchall():
        out[d].append({"cat": cat, "idx_long": ifl, "idx_short": ifs, "idx_net": ifn, "stk_net": sfn})
    return out


def export(out: Path = SITE_DATA, env: str | None = None, since: str = "2005-01-01") -> dict:
    out = Path(out)
    (out / "sessions").mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(research_db(env)), read_only=True)
    try:
        rows = [r for r in con.execute(_deals_sql()).fetchall() if r[0] >= since]
        oi = participant_oi(con)
    finally:
        con.close()
    flows = fii_dii()
    by_day: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_day[r[0]].append(_deal(r))
    index = []
    for d in sorted(by_day):
        deals = by_day[d]
        rt = sum(x["rt"] for x in deals)
        summary = {"date": d, "deals": len(deals),
                   "bulk": sum(x["kind"] == "BULK" for x in deals),
                   "block": sum(x["kind"] == "BLOCK" for x in deals),
                   "roundtrip_share": round(rt / len(deals), 4) if deals else 0.0,
                   "value_cr": round(sum(x["cr"] or 0 for x in deals), 2)}
        index.append(summary)
        # Column-wise, like every other shard: each row repeating its field
        # names made sessions/ 94 MB of mostly keys.
        (out / "sessions" / f"{d}.json").write_text(json.dumps(
            {**summary, "flows": flows.get(d), "oi": oi.get(d),
             "cols": SESSION_COLS, "rows": [[x[c] for c in SESSION_COLS] for x in deals]},
            separators=(",", ":")))
    index.reverse()
    (out / "sessions.json").write_text(json.dumps(index, separators=(",", ":")))
    meta = {"built_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "latest_session": index[0]["date"] if index else None,
            "sessions": len(index), "deals": len(rows),
            "source": "Public disclosures from NSE, BSE (shareholding), NSDL and fund houses; participant labels by this project",
            "health": _health()}
    export_markets(out, env)
    export_insights(out, rows)
    held = named_holdings()
    ms = market_structure(env)
    export_filings(out, ms)
    meta["pledge_rows"], meta["pledge_unmatched"] = ms["pledge_rows"], ms["pledge_unmatched"]
    meta["industry_coverage"] = len(ms["industry"])
    mf = mf_holdings()
    sym_of: dict[str, tuple] = {}
    meta["stocks"] = export_stocks(out, rows, env, held, ms, mf, sym_of)
    meta["funds"] = export_funds(out, mf, sym_of)
    meta["funds_as_of"] = mf["latest"] if mf else None
    meta["participants"] = export_participants(out, rows, env, held)
    meta["named_holders"] = len(held[0])
    _add_widest_holders(out, held)
    _add_fund_counts(out, mf, sym_of)
    export_system(out)
    (out / "meta.json").write_text(json.dumps(meta, indent=1))
    return meta


def nifty_valuation(q, collected: Path, seed: Path | None = None) -> list[list]:
    """NIFTY 50 P/E, P/B and yield by day: the collected series (from 2021-10-18)
    and, before it, the seed's, back to 2005. The two agree to 0.00% on P/E over
    all 1,154 days they share (measured 2026-11-06), so this is one series."""
    seed = seed or SEED
    rows = [[str(d), c, pe, pb, dy] for d, c, pe, pb, dy in q.execute(
        f"SELECT date, close, pe, pb, div_yield FROM read_parquet('{collected}') WHERE index_key = 'NIFTY50'"
        " AND pe IS NOT NULL ORDER BY date").fetchall()]
    val, idx = seed / "index_valuation.parquet", seed / "indices_data.parquet"
    if not rows or not val.exists():
        return rows
    close = f"(SELECT date, close FROM read_parquet('{idx}') WHERE name = 'NIFTY 50')" if idx.exists() \
        else "(SELECT NULL::VARCHAR AS date, NULL::DOUBLE AS close WHERE false)"
    older = q.execute(f"""SELECT v.date, c.close, v.pe, v.pb, v.div_yield FROM read_parquet('{val}') v
                          LEFT JOIN {close} c ON c.date = v.date
                          WHERE v.index_name = 'NIFTY 50' AND v.pe IS NOT NULL AND v.date < '{rows[0][0]}'
                          ORDER BY v.date""").fetchall()
    return [[str(d), c, pe, pb, dy] for d, c, pe, pb, dy in older] + rows


def market_micro(q, spine: str, delivery: Path) -> dict:
    """How the market trades, by month: stocks traded, turnover, the share of
    turnover in the ten busiest stocks, and the quantity-weighted delivery share.
    Whole-market descriptions from the raw price files: no return, no judgement."""
    series = ", ".join(f"'{x}'" for x in DELIVERY_SERIES)
    dlv = dict(q.execute(f"""
        SELECT substr(date, 1, 7), round(100 * sum(deliverable_qty) / sum(traded_qty), 1)
        FROM read_parquet('{delivery}') WHERE series IN ({series}) AND traded_qty > 0
        GROUP BY 1""").fetchall()) if delivery.exists() else {}
    rows = q.execute(f"""
        WITH t AS (SELECT substr(CAST(date AS VARCHAR), 1, 7) m, symbol, sum(close * volume) v
                   FROM read_parquet('{spine}', hive_partitioning=true) WHERE close > 0 AND volume > 0
                   GROUP BY 1, 2),
        r AS (SELECT *, row_number() OVER (PARTITION BY m ORDER BY v DESC) i FROM t)
        SELECT m, count(*), round(sum(v) / {CR}, 1), round(100 * sum(v) FILTER (WHERE i <= 10) / sum(v), 1)
        FROM r GROUP BY 1 ORDER BY 1""").fetchall()
    return _cols(["m", "stocks", "turnover_cr", "top10_pct", "delivery_pct"],
                 [[m, n, cr, top, dlv.get(m)] for m, n, cr, top in rows])


def export_markets(out: Path, env: str | None = None) -> None:
    """data/markets.json: foreign-investor flows (NSDL, 1999+), FII/DII cash,
    F&O index-futures positioning by category (2014+), the NIFTY 500 total
    return (1995+), NIFTY 50 valuation (2005+) and how the market trades by month.
    Levels and flows only."""
    q = duckdb.connect()
    doc: dict = {}
    try:
        spine_dir = warehouse_dir(env) / "price_spine"
        if list(spine_dir.glob("**/*.parquet")):
            doc["micro"] = market_micro(q, str(spine_dir / "**" / "*.parquet"),
                                        COLLECTED / "delivery" / "delivery.parquet")
        inv = COLLECTED / "fpi_nsdl" / "fpi_investment.parquet"
        if inv.exists():
            # Equity is one line ('' route) to 2009-11 and split by route after;
            # the 'Sub-total' line is the total there. Never both.
            eq = (f"FROM read_parquet('{inv}') WHERE is_daily_flow AND category = 'Equity'"
                  " AND route IN ('', 'Sub-total')")
            doc["fpi_monthly"] = _cols(["m", "net_cr"], [[m, round(v, 1)] for m, v in q.execute(
                f"SELECT strftime(reporting_date, '%Y-%m') m, sum(net_cr) {eq} GROUP BY 1 ORDER BY 1").fetchall()])
            doc["fpi_daily"] = _cols(["d", "net_cr", "secondary_cr"], [[str(d), round(n, 1), None if x is None else round(x, 1)]
                for d, n, x in q.execute(f"""
                SELECT t.reporting_date, t.net_cr, s.net_cr FROM (SELECT reporting_date, net_cr {eq}) t
                LEFT JOIN (SELECT reporting_date, net_cr FROM read_parquet('{inv}') WHERE is_daily_flow
                           AND category = 'Equity' AND route = 'Stock Exchange') s USING (reporting_date)
                WHERE t.reporting_date >= current_date - INTERVAL 400 DAY ORDER BY 1""").fetchall()])
        tri = COLLECTED / "index_tri" / "index_tri.parquet"
        if tri.exists():
            doc["nifty500_tri_monthly"] = _cols(["m", "tri"], [[m, round(v, 2)] for m, v in q.execute(
                f"SELECT strftime(date, '%Y-%m') m, arg_max(tri, date) FROM read_parquet('{tri}')"
                " WHERE index_key = 'NIFTY500' AND tri > 0 GROUP BY 1 ORDER BY 1").fetchall()])
        ic = COLLECTED / "index_close" / "index_close.parquet"
        if ic.exists():
            doc["nifty50_valuation"] = _cols(["d", "close", "pe", "pb", "dy"], nifty_valuation(q, ic))
    finally:
        q.close()
    flows = fii_dii()
    doc["fii_dii"] = _cols(["d", "fii", "dii"], [[d, f.get("FII", {}).get("netValue"), f.get("DII", {}).get("netValue")]
                                               for d, f in sorted(flows.items())])
    con = duckdb.connect(str(research_db(env)), read_only=True)
    try:
        doc["oi_index_futures"] = _cols(["d", "FII", "DII", "Pro", "Client"], [list(r) for r in con.execute("""
            SELECT CAST(session_date AS VARCHAR),
                   max(index_fut_net) FILTER (WHERE category = 'FII'), max(index_fut_net) FILTER (WHERE category = 'DII'),
                   max(index_fut_net) FILTER (WHERE category = 'Pro'), max(index_fut_net) FILTER (WHERE category = 'Client')
            FROM participant_oi GROUP BY 1 ORDER BY 1""").fetchall()])
    finally:
        con.close()
    (out / "markets.json").write_text(json.dumps(doc, separators=(",", ":")))


def export_insights(out: Path, rows: list) -> None:
    """data/insights.json: descriptive aggregates of the deal tape and the
    shareholding filings. Who traded, how much, how often — never what
    happened to prices afterwards, and no ranking by any return."""
    by_year_type: dict[tuple[str, str], list[float]] = defaultdict(lambda: [0.0, 0.0])
    rt_year: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    last = max((r[0] for r in rows), default="")
    cut = f"{int(last[:4]) - 1}{last[4:]}" if last else ""
    who_val: dict[str, list] = {}
    stock_n: dict[str, list] = {}
    for r in rows:
        d = _deal(r)
        y = r[0][:4]
        rt_year[y][0] += 1
        rt_year[y][1] += d["rt"]
        if d["rt"]:
            continue
        by_year_type[(y, d["type"])][0 if d["side"] == "BUY" else 1] += d["cr"] or 0
        if r[0] > cut:
            w = who_val.setdefault(d["who"], [d["who"], d["pid"], d["type"], 0.0, 0.0, 0])
            w[3 if d["side"] == "BUY" else 4] += d["cr"] or 0
            w[5] += 1
            st = stock_n.setdefault(d["sym"], [d["sym"], d["sid"], d["co"], 0, 0.0])
            st[3] += 1
            st[4] += d["cr"] or 0
    doc = {
        "asof": last, "window_from": cut,
        "value_by_year_type": _cols(["y", "type", "buy_cr", "sell_cr"],
                                    [[y, t, round(b, 1), round(sv, 1)] for (y, t), (b, sv) in sorted(by_year_type.items())]),
        "roundtrip_by_year": _cols(["y", "rows", "roundtrip_rows"], [[y, n, k] for y, (n, k) in sorted(rt_year.items())]),
        "largest_participants": _cols(["who", "pid", "type", "buy_cr", "sell_cr", "deals"],
                                      [[a, b, c, round(x, 1), round(z, 1), n] for a, b, c, x, z, n in
                                       sorted(who_val.values(), key=lambda w: -(w[3] + w[4]))[:40]]),
        "most_dealt_stocks": _cols(["sym", "sid", "co", "deals", "value_cr"],
                                   [[a, b, c, n, round(v, 1)] for a, b, c, n, v in
                                    sorted(stock_n.values(), key=lambda x: -x[3])[:40]]),
    }
    shp = COLLECTED / "shp" / "shp_holdings.parquet"
    if shp.exists():
        q = duckdb.connect()
        try:
            for key, cats in (("fpi", OWNERSHIP["fpi"]), ("mf", OWNERSHIP["mf"])):
                inlist = ", ".join(repr(c) for c in cats)
                shifts = q.execute(f"""
                    WITH latest AS (SELECT isin, quarter_end, max(broadcast_date) b FROM read_parquet('{shp}')
                                    WHERE is_calendar_quarter GROUP BY 1, 2),
                    v AS (SELECT h.isin, any_value(h.symbol) sym, any_value(h.company) co, h.quarter_end q,
                                 SUM(CASE WHEN category IN ({inlist}) THEN pct_shares ELSE 0 END) pct
                          FROM read_parquet('{shp}') h JOIN latest l ON l.isin = h.isin
                            AND l.quarter_end = h.quarter_end AND l.b = h.broadcast_date GROUP BY 1, 4),
                    -- The latest quarter MOST companies have filed: the newest one
                    -- holds only early filers for weeks (2026-09-30 had a handful).
                    lq AS (SELECT max(q) q FROM (SELECT q FROM v GROUP BY q HAVING count(*) >= 1000)),
                    pairs AS (SELECT a.sym, a.co, a.q, a.pct now_pct, b.pct prev_pct, a.pct - b.pct chg
                              FROM v a JOIN v b ON b.isin = a.isin AND b.q = (SELECT max(q) FROM v c WHERE c.isin = a.isin AND c.q < a.q)
                              WHERE a.q = (SELECT q FROM lq))
                    SELECT sym, co, q, round(prev_pct, 2), round(now_pct, 2), round(chg, 2) FROM pairs
                    WHERE chg IS NOT NULL ORDER BY chg""").fetchall()
                doc[f"{key}_shift"] = {
                    "quarter": shifts[0][2] if shifts else None,
                    "cols": ["sym", "sid", "co", "prev_pct", "now_pct", "change_pp"],
                    "up": [[a, sym_file(a), b, p, n, c] for a, b, _q, p, n, c in shifts[::-1][:25] if c > 0],
                    "down": [[a, sym_file(a), b, p, n, c] for a, b, _q, p, n, c in shifts[:25] if c < 0]}
        finally:
            q.close()
    (out / "insights.json").write_text(json.dumps(doc, separators=(",", ":")))


def _cols(cols: list[str], rows: list[list]) -> dict:
    return {"cols": cols, "rows": rows}


def export_stocks(out: Path, rows: list, env: str | None = None, holdings: tuple | None = None,
                  structure: dict | None = None, mf: dict | None = None,
                  sym_of: dict[str, tuple] | None = None) -> int:
    """data/stocks/<SYM>.json: identity, deals, quarterly ownership, insider
    trades and a WEEKLY close line (daily for ~2,300 names is ~150 MB).
    `sym_of`, when given, is filled with ISIN -> (symbol, file id, name) for
    the fund pages, which name holdings by ISIN."""
    (out / "stocks").mkdir(parents=True, exist_ok=True)
    deals: dict[str, list] = defaultdict(list)
    co: dict[str, str] = {}
    isin_of: dict[str, str] = {}
    for r in rows:
        d = _deal(r)
        deals[d["sym"]].append([r[0], d["who"], d["pid"], d["type"], d["side"], d["qty"], d["px"],
                                d["cr"], int(d["rt"]), d["kind"]])
        if d["co"]:
            co[d["sym"]] = d["co"]
        if d["isin"]:
            isin_of[d["sym"]] = d["isin"]
    con = duckdb.connect(str(research_db(env)), read_only=True)
    try:
        ident = {sym: dict(zip(("isin", "co", "listed", "delisted", "reason", "status"), rest, strict=True))
                 for sym, *rest in con.execute("""
                    SELECT canonical_symbol, isin, company_name, CAST(listing_date AS VARCHAR),
                           CAST(delisting_date AS VARCHAR), delisting_reason, status
                    FROM security_master""").fetchall()}
        history: dict[str, list] = defaultdict(list)
        for sym, hs, fr, to, ser in con.execute("""
                SELECT m.canonical_symbol, h.symbol, CAST(h.valid_from AS VARCHAR), CAST(h.valid_to AS VARCHAR), h.series
                FROM symbol_history h JOIN security_master m USING (security_id)
                ORDER BY 1, 3""").fetchall():
            history[sym].append([hs, fr, to, ser])
    finally:
        con.close()
    # The seed closed 1,668 symbol windows on its snapshot date (2019-12-02) with
    # nothing after them; for a company still ACTIVE the last window is open, not
    # ended ("INFY 2011-07-01 -> 2019-12-02" read as if Infosys stopped trading).
    # Display only: symbol_history itself is the identity layer's, unchanged.
    # (named `windows`, not `rows`: `rows` is this function's deal list, and
    # shadowing it crashed every site export from 2026-10-27 to 10-28.)
    for sym, windows in history.items():
        if windows and windows[-1][2] and (ident.get(sym) or {}).get("status") == "ACTIVE":
            windows[-1][2] = None
    for sym, i in ident.items():
        if i["isin"]:
            isin_of.setdefault(sym, i["isin"])
    # NSE's current lists, for a symbol the identity layer does not know: mostly
    # the SME platform, which bulk deals name and security_master does not hold.
    from src.archive import listing
    listed_now = listing.latest()
    for sym in deals:
        if sym not in isin_of and sym in listed_now:
            isin_of[sym] = listed_now[sym]["isin"]
    q = duckdb.connect()
    try:
        shp = str(COLLECTED / "shp" / "shp_holdings.parquet")
        cases = ", ".join(
            f"round(SUM(CASE WHEN category IN ({', '.join(repr(c) for c in cats)}) THEN pct_shares END), 3) AS {k}"
            for k, cats in OWNERSHIP.items())
        own: dict[str, list] = defaultdict(list)
        shp_co: dict[str, str] = {}
        if Path(shp).exists():
            # Some security_master rows carry the SYMBOL as company_name (TCS ->
            # "TCS"); the shareholding filing names the company properly.
            shp_co = dict(q.execute(f"SELECT isin, arg_max(company, broadcast_date) FROM read_parquet('{shp}')"
                                    " WHERE company IS NOT NULL GROUP BY 1").fetchall())
            for isin, qe, *vals in q.execute(f"""
                    WITH latest AS (SELECT isin, quarter_end, max(broadcast_date) b FROM read_parquet('{shp}')
                                    GROUP BY 1, 2)
                    SELECT h.isin, h.quarter_end, {cases}
                    FROM read_parquet('{shp}') h JOIN latest l
                      ON l.isin = h.isin AND l.quarter_end = h.quarter_end AND l.b = h.broadcast_date
                    GROUP BY 1, 2 ORDER BY 1, 2""").fetchall():
                own[isin].append([qe, *vals])
            # The ISINs the pages use, not the identity table's: it can still hold
            # the old ISIN for a symbol whose deals carry the new one (CANBK,
            # CLEDUCATE), which read as two live securities and merged nothing.
            filed_as = dict(q.execute(f"SELECT isin, any_value(symbol) FROM read_parquet('{shp}')"
                                      " WHERE symbol IS NOT NULL AND symbol <> '' GROUP BY 1").fetchall())
            # Live means on NSE's lists today. A dead symbol's page keeps its ISIN but
            # must not block the renamed company: PHILIPCARB's page held INE602A01023,
            # which read as a live security, so PCBL lost its 2018-2021 filings.
            live = {isin_of[s] for s in isin_of if s in listed_now} or set(isin_of.values())
            own = chain_isins(own, live, filed_as, isin_of)
        insider = insider_rows(q)
        delivery = delivery_series(q)
        adj_dir = warehouse_dir(env) / "price_spine_adj"
        adj = str(adj_dir / "**" / "*.parquet")
        weekly: dict[str, list] = defaultdict(list)
        for sym, d, c in [] if not any(adj_dir.glob("**/*.parquet")) else q.execute(f"""
                SELECT symbol, max(date) d, arg_max(close, date) c
                FROM read_parquet('{adj}', hive_partitioning=true)
                GROUP BY symbol, strftime(CAST(date AS DATE), '%G-%V') ORDER BY 1, 2""").fetchall():
            weekly[sym].append([d, round(c, 2)])
    finally:
        q.close()
    by_co = (holdings or ({}, {}, {}, {}))[1]
    fund = fundamentals()
    fund_ind = fund_industries()
    # The SME platform is outside the price spine by decision (0045): its closes
    # come from the bhavcopies, as traded, for a symbol with no spine price.
    sme_px = sme_prices.weekly()
    px_of = lambda s: weekly.get(s) or sme_px.get(s, [])  # noqa: E731
    ms_ = structure or {"industry": {}, "indices": {}, "actions": {}, "ann": {}, "meet": {}, "pledge": {}}
    syms = set(deals) | {s for s, i in ident.items() if i["isin"] in own}
    last_day = max((r[0] for r in rows), default="")
    cut12 = f"{int(last_day[:4]) - 1}{last_day[4:]}" if last_day else ""
    screen: list[list] = []
    for sym in syms:
        i = ident.get(sym, {})
        isin = isin_of.get(sym)
        name = co.get(sym) or i.get("co") or listed_now.get(sym, {}).get("co")
        if (not name or name.upper() == sym) and isin in shp_co:
            name = shp_co[isin]
        doc = {"sym": sym, "co": name, "isin": isin,
               **listing_state(i, px_of(sym), last_day),
               "listed": i.get("listed"), "history": history.get(sym, []),
               "deals": _cols(["d", "who", "pid", "type", "side", "qty", "px", "cr", "rt", "kind"], deals.get(sym, [])),
               "own": _cols(["q", *OWNERSHIP], own.get(isin, []) if isin else []),
               **insider_doc(insider.get(sym, []), px_of(sym), _newest_shares(fund.get(sym, []))),
               **delivery.get(sym, DELIVERY_NONE),
               "px": _cols(["d", "close"], px_of(sym)),
               "px_as_traded": not weekly.get(sym) and bool(sme_px.get(sym)),
               "holders": _holders_doc(by_co.get(isin) if isin else None),
               "industry": ms_["industry"].get(sym), "indices": ms_["indices"].get(sym, []),
               "industry_funds": None if ms_["industry"].get(sym) or not isin else fund_ind.get(isin),
               "actions": _cols(["ex", "subject", "record"], sorted(ms_["actions"].get(sym, set()), reverse=True)),
               "announcements": _cols(["t", "desc", "text", "file"],
                                      sorted(ms_["ann"].get(sym, {}).values(), key=lambda a: a[0], reverse=True)[:80]),
               "meetings": _cols(["d", "purpose", "desc"], sorted(ms_["meet"].get(sym, set()), reverse=True)[:40]),
               "results": _cols(RESULT_COLS, fund.get(sym, [])),
               "results_withheld": WITHHELD.get(sym, []),
               "valuation": valuation(fund.get(sym, []), px_of(sym)[-1][1] if px_of(sym) else None),
               "pledge": dict(zip(["shp_q", "promoter_pct", "pledged_pct_of_promoter", "pledged_pct_of_total",
                                   "depository_pledged_pct", "as_of"], ms_["pledge"][sym], strict=True))
                         if sym in ms_["pledge"] else None,
               "mf": mf_stock_doc(mf, isin, fund[sym][0][10] if fund.get(sym) else None)}
        if sym_of is not None and isin:
            sym_of[isin] = (sym, sym_file(sym), name)
        (out / "stocks" / f"{sym_file(sym)}.json").write_text(json.dumps(doc, separators=(",", ":")))
        screen.append(_screen_row(sym, doc, deals.get(sym, []), cut12))
    (out / "screener.json").write_text(json.dumps(_cols(SCREEN_COLS, screen), separators=(",", ":")))

    def _val(s):
        v = valuation(fund.get(s, []), weekly[s][-1][1] if weekly.get(s) else None) or {}
        return v.get("mcap_cr"), v.get("pe")
    index = sorted(([s, co.get(s) or ident.get(s, {}).get("co") or "", sym_file(s), len(deals.get(s, [])),
                     ms_["industry"].get(s), ms_["indices"].get(s, []), *_val(s)]
                    for s in syms), key=lambda x: -x[3])
    (out / "stocks.json").write_text(json.dumps(index, separators=(",", ":")))
    return len(syms)


#: A symbol priced within this many days of the newest session is still trading.
STILL_TRADING_DAYS = 30
#: Reasons a current price overrules. UNKNOWN: NESTLEIND and HNDFDS read "delisted"
#: with a price from this week. LEFT_UNIVERSE stands: nine symbols last traded on the
#: very date recorded, which is what leaving looks like.
STILL_TRADING_OVERRULES = {"ISIN_CHANGE", "UNKNOWN"}


def listing_state(i: dict, px: list, last_day: str) -> dict:
    """delisted, reason and status as the page shows them.

    A share split ends the old ISIN's security, and security_master records it
    as MERGED with a delisting date and reason ISIN_CHANGE. For a symbol that
    goes on trading that is a change of ISIN, not a delisting: 99 pages including
    HAVELLS, GRASIM and BEL said "delisted (ISIN_CHANGE)" until 2026-11-06.
    Only STILL_TRADING_OVERRULES give way to a current price. security_master is unchanged.
    """
    state = {"delisted": i.get("delisted"), "reason": i.get("reason"), "status": i.get("status")}
    if i.get("reason") in STILL_TRADING_OVERRULES and px and last_day:
        age = (date.fromisoformat(str(last_day)[:10]) - date.fromisoformat(str(px[-1][0])[:10])).days
        if age <= STILL_TRADING_DAYS:
            return {"delisted": None, "reason": None, "status": "ACTIVE"}
    return state


def fund_industries(path: Path | None = None) -> dict[str, str]:
    """ISIN -> the industry most fund houses file it under, from the monthly
    scheme portfolios: equity ISINs only (a bond's 'industry' is its rating),
    case folded, junk ('N.A.', bare numbers) dropped, and nothing where two
    labels tie. For companies outside every NSE index, which carry no NSE
    industry; shown under its own name, never mixed into NSE's for peers.
    """
    from src.ingest import mf_portfolios as mfi
    path = path or mfi.OUT
    if not path.exists():
        return {}
    q = duckdb.connect()
    try:
        rows = q.execute(f"""SELECT isin, trim(industry), count(DISTINCT amc) FROM read_parquet('{path}')
                             WHERE industry IS NOT NULL GROUP BY 1, 2""").fetchall()
    finally:
        q.close()
    votes: dict[str, Counter] = defaultdict(Counter)
    spelling: dict[str, Counter] = defaultdict(Counter)
    for isin, label, n in rows:
        if not is_equity_isin(isin or "") or not re.search(r"[A-Za-z]{3}", label or "") \
                or re.fullmatch(r"n\.?\s*a\.?|-+|others?", label.strip().lower()):
            continue
        key = re.sub(r"\s+", " ", label.lower())
        votes[isin][key] += n
        spelling[key][label] += n
    out = {}
    for isin, v in votes.items():
        top = v.most_common(2)
        if len(top) == 1 or top[0][1] > top[1][1]:
            out[isin] = spelling[top[0][0]].most_common(1)[0][0]
    return out


def _near(a: str, b: str) -> bool:
    """Same length, at most two characters apart: a mistyped ISIN."""
    return len(a) == len(b) and a != b and sum(x != y for x, y in zip(a, b, strict=True)) <= 2


def chain_isins(own: dict[str, list], current: set[str], symbol_of: dict[str, str] | None = None,
                isin_of: dict[str, str] | None = None) -> dict[str, list]:
    """Each current ISIN's quarters, with those filed under ISINs that are the same shares.

    A share split or consolidation gives the same shares a new ISIN: IEX went
    INE022Q01012 -> INE022Q01020. Filings under the old one were lost to a page
    keyed on today's. The first nine characters (country, issuer, security type)
    survive the change. The quarters interleave rather than meet end to end:
    2016-17 filings are stored under the ISIN the seed knows today, so 'the old
    one ends before the new one starts' rejected nearly every company. So an old
    ISIN fills any quarter the current one lacks, and the current one wins a
    quarter both report. No overlap test: a shareholding pattern is filed for the
    company, so a filing under the same issuer describes the same owners. Two
    such tests refused PCBL and DOLPHIN. Another current ISIN has its own page
    and is never absorbed.

    Filers also mistype: INE0LEZO1016, a letter O for a zero. Such an ISIN joins
    its company only if the filing's own symbol is that company's and the two
    differ by at most two characters (`symbol_of` filing ISIN -> symbol, `isin_of`
    symbol -> page ISIN): the characters alone could be another issuer.
    """
    groups: dict[str, list[str]] = defaultdict(list)
    for isin in own:
        if isin.startswith("INE") and len(isin) == 12:
            groups[isin[:9]].append(isin)
    for typo, sym in (symbol_of or {}).items():
        page = (isin_of or {}).get(sym)
        if typo in own and page and typo not in current and _near(typo, page):
            groups[page[:9]].append(typo)
    out = dict(own)
    for isin in current:
        if isin not in own:
            continue
        rows = {r[0]: r for r in own[isin]}
        for o in groups.get(isin[:9], []):
            if o != isin and o not in current:
                rows = {**{r[0]: r for r in own[o]}, **rows}
        out[isin] = [rows[q] for q in sorted(rows)]
    return out


INSIDER_COLS = ["d", "person", "cat", "txn", "qty", "cr", "mode"]
INSIDER_SUM_COLS = ["y", "group", "n", "buy_cr", "sell_cr", "pledge_cr", "revoke_cr", "invoke_cr"]
#: The rows a stock page carries. HDFCBANK alone has 33,721 filings, nearly all
#: employee option sales; the whole history is in the yearly summary instead.
INSIDER_KEEP = 300
#: The seed files one trade a few days away from where the collected XBRL dates
#: it (measured 2026-11-05: 2 to 4 days around May-July 2026).
INSIDER_SAME_TRADE_DAYS = 10
_INSIDER_GROUP = {"Promoters": "Promoter", "Promoter Group": "Promoter",
                  "Director": "Director or manager", "Key Managerial Personnel": "Director or manager",
                  "Employees/Designated Employees": "Employee", "Designated Person": "Employee"}
_INSIDER_TXN_COL = {"Buy": 3, "Sell": 4, "Pledge": 5, "Pledge Revoke": 6, "Pledge Invoke": 7}


def insider_rows(q, seed: Path | None = None, collected: Path | None = None) -> dict[str, list]:
    """Insider filings per symbol, seed plus collected, oldest first: [d, person,
    cat, txn, qty, cr, mode].

    The seed holds 2,83,281 filings from 2016 and the collector only what came
    after May 2026; this read the collector's file alone until 2026-11-05, so
    TCS showed none. A seed row the collector also holds is dropped. A quantity
    of 0 means "not stated" (0046: most seed sells carry value, not quantity),
    so it is None and never displayed as zero shares.
    """
    seed = seed or SEED / "insider_trading.parquet"
    collected = collected or COLLECTED / "insider" / "insider_trading.parquet"
    if not seed.exists() and not collected.exists():
        return {}
    none = ("SELECT NULL::VARCHAR AS symbol, NULL::VARCHAR AS d, NULL::VARCHAR AS person, NULL::VARCHAR AS cat, "
            "NULL::VARCHAR AS txn, NULL::DOUBLE AS qty, NULL::DOUBLE AS value, NULL::VARCHAR AS mode WHERE false")
    k_sql = (f"SELECT symbol, filing_date d, person, category cat, transaction_type txn, quantity qty, value, mode "
             f"FROM read_parquet('{collected}')") if collected.exists() else none
    s_sql = (f"SELECT DISTINCT symbol, filing_date d, name person, category cat, transaction_type txn, "
             f"quantity::DOUBLE qty, value, mode FROM read_parquet('{seed}')") if seed.exists() else none
    out: dict[str, list] = defaultdict(list)
    for sym, *v in q.execute(f"""
            WITH k AS ({k_sql}), s AS ({s_sql}),
            fresh AS (SELECT s.* FROM s WHERE NOT EXISTS (
                SELECT 1 FROM k WHERE k.symbol = s.symbol AND k.txn = s.txn
                  AND lower(trim(k.person)) = lower(trim(s.person))
                  AND round(coalesce(k.value, 0)) = round(coalesce(s.value, 0))
                  AND abs(date_diff('day', TRY_CAST(k.d AS DATE), TRY_CAST(s.d AS DATE)))
                      <= {INSIDER_SAME_TRADE_DAYS}))
            SELECT symbol, d, trim(person),
                   CASE WHEN cat IN ('-', '') OR cat IS NULL THEN 'Not stated'
                        WHEN cat = 'Employee' THEN 'Employees/Designated Employees' ELSE cat END,
                   CASE WHEN txn IN ('-', 'Unknown', '') OR txn IS NULL THEN 'Not stated' ELSE txn END,
                   NULLIF(qty, 0), round(NULLIF(value, 0) / {CR}, 2), mode
            FROM (SELECT * FROM k UNION ALL SELECT * FROM fresh)
            ORDER BY symbol, d""").fetchall():
        out[sym].append(v)
    return out


def _newest_shares(res: list) -> float | None:
    """Newest known share count in crore (index 10 of RESULT_COLS), for the check below."""
    return next((r[10] for r in res if r[10]), None)


def insider_doc(rows: list, px: list, shares_cr: float | None) -> dict:
    """The stock page's insider fields: the newest rows, a summary of all of them
    by year and group, and how many values were impossible.

    A FILING LARGER THAN THE COMPANY IS NOT A FILING WE CAN SHOW. The seed holds
    a Rs 54.98 lakh crore "sale" of SJS and a Rs 2.12 lakh crore sale of ZEEL.
    Value above the company's market value that week (split-adjusted close x
    newest share count) is blanked and counted, not corrected: what the real
    figure was cannot be known from here. Without a price or share count the
    check cannot run and the value stands.
    """
    days = [p[0] for p in px]
    doubt = 0
    kept: list[list] = []
    summary: dict[tuple, list] = {}
    for d, person, cat, txn, qty, cr, mode in rows:
        if cr is not None and shares_cr and days:
            i = min(bisect.bisect_left(days, d), len(days) - 1)
            if cr > px[i][1] * shares_cr:
                cr, doubt = None, doubt + 1
        kept.append([d, person, cat, txn, qty, cr, mode])
        key = (d[:4], _INSIDER_GROUP.get(cat, "Other"))
        e = summary.setdefault(key, [*key, 0, 0.0, 0.0, 0.0, 0.0, 0.0])
        e[2] += 1
        if cr is not None and txn in _INSIDER_TXN_COL:
            e[_INSIDER_TXN_COL[txn]] = round(e[_INSIDER_TXN_COL[txn]] + cr, 2)
    return {"insider": _cols(INSIDER_COLS, kept[-INSIDER_KEEP:]),
            "insider_n": len(kept), "insider_doubt": doubt,
            "insider_sum": _cols(INSIDER_SUM_COLS, [summary[k] for k in sorted(summary)])}


DELIVERY_NONE = {"dlv": _cols(["m", "pct"], []), "dlv_d": _cols(["d", "pct", "qty"], []), "dlv_s": None}
#: Debt series (GB, GS, N2...) share a symbol-like code; equity series only.
DELIVERY_SERIES = ("EQ", "BE", "BZ", "SM", "ST")


def delivery_series(q, path: Path | None = None) -> dict[str, dict]:
    """Share of traded quantity that ended in delivery, per symbol: by month for
    the whole history, by day for the last 60 sessions, and quantity-weighted
    over the last 20 and 250 sessions. Weighted, so a thin day cannot swing a
    month. A description of trading, not a judgement of it.
    """
    path = path or COLLECTED / "delivery" / "delivery.parquet"
    if not path.exists():
        return {}
    series = ", ".join(f"'{x}'" for x in DELIVERY_SERIES)
    src = f"""SELECT symbol, date, sum(traded_qty) t, sum(deliverable_qty) dq FROM read_parquet('{path}')
              WHERE series IN ({series}) AND traded_qty > 0 GROUP BY 1, 2"""
    out: dict[str, dict] = {}
    months: dict[str, list] = defaultdict(list)
    for sym, m, pct in q.execute(f"""
            SELECT symbol, substr(date, 1, 7) m, round(100 * sum(dq) / sum(t), 1)
            FROM ({src}) GROUP BY 1, 2 ORDER BY 1, 2""").fetchall():
        months[sym].append([m, pct])
    recent: dict[str, list] = defaultdict(list)
    for sym, d, t, dq in q.execute(f"""
            SELECT symbol, date, t, dq FROM ({src})
            WHERE date >= (SELECT strftime(max(date)::DATE - INTERVAL 400 DAY, '%Y-%m-%d') FROM read_parquet('{path}'))
            QUALIFY row_number() OVER (PARTITION BY symbol ORDER BY date DESC) <= 250
            ORDER BY 1, 2""").fetchall():
        recent[sym].append((d, t, dq))
    for sym, ms in months.items():
        r = recent.get(sym, [])
        weighted = lambda w: round(100 * sum(x[2] for x in w) / sum(x[1] for x in w), 1)  # noqa: E731
        out[sym] = {"dlv": _cols(["m", "pct"], ms),
                    "dlv_d": _cols(["d", "pct", "qty"], [[d, round(100 * dq / t, 1), t] for d, t, dq in r[-60:]]),
                    "dlv_s": {"as_of": r[-1][0], "s20": weighted(r[-20:]), "s250": weighted(r),
                              "n250": len(r)} if r else None}
    return out


SCREEN_COLS = ["sym", "sid", "co", "industry", "indices", "close", "mcap_cr", "pe", "rev_yoy", "pat_yoy",
               "net_margin", "promoter", "fpi", "mf", "fpi_chg", "mf_chg", "pledged", "deals_12m", "holders",
               "mf_schemes"]


def _screen_row(sym: str, doc: dict, deals: list, cut12: str) -> list:
    """One screener row from a finished stock document: levels and changes as
    filed or traded. Nothing here is a forward return or a score."""
    v = doc.get("valuation") or {}
    res = doc["results"]["rows"]
    own = doc["own"]["rows"]

    def yoy(i: int) -> float | None:
        if not res:
            return None
        a = res[0]
        b = next((r for r in res if r[0][5:] == a[0][5:] and int(r[0][:4]) == int(a[0][:4]) - 1), None)
        if not b or not b[i] or a[i] is None or b[i] <= 0:
            return None
        return round(100 * (a[i] / b[i] - 1), 1)

    last, prev = (own[-1] if own else None), (own[-2] if len(own) > 1 else None)
    def chg(k: int) -> float | None:
        if not last or not prev or last[k] is None or prev[k] is None:
            return None
        return round(last[k] - prev[k], 2)
    h = doc.get("holders")
    return [sym, sym_file(sym), doc.get("co"), doc.get("industry"), doc.get("indices"), v.get("close"),
            v.get("mcap_cr"), v.get("pe"), yoy(2), yoy(5),
            round(100 * res[0][5] / res[0][2], 1) if res and res[0][2] and res[0][5] is not None else None,
            last[1] if last else None, last[2] if last else None, last[4] if last else None, chg(2), chg(4),
            (doc.get("pledge") or {}).get("pledged_pct_of_promoter"),
            sum(1 for d in deals if d[0] > cut12 and not d[8]),
            len(h["now"]["rows"]) if h else 0,
            (doc.get("mf") or {}).get("schemes", 0)]


#: A filing's holder group -> this site's participant type, used only when the
#: holder is not already a typed participant (a ruling or the master wins).
GROUP_TYPE = {"MF": "MUTUAL_FUND", "FPI": "FOREIGN_INSTITUTION", "FOREIGN": "FOREIGN_INSTITUTION",
              "INSURANCE": "INSURANCE", "AIF": "AIF_PMS", "BANK_FI": "BANK", "GOVERNMENT": "GOVERNMENT",
              "CORPORATE": "CORPORATE", "INDIVIDUAL": "INDIVIDUAL", "OTHER": "UNKNOWN"}


def named_holdings() -> tuple[dict[str, list], dict[str, dict], dict[str, str], dict[str, str]]:
    """From the named >1% public holders in every shareholding filing
    (src/ingest/shp_holders.py): per INVESTOR, every company it is named in at
    that company's latest filing, with the previous filing's figure; per
    COMPANY (isin), the named holders now and those named last quarter but not
    now. Names are cleaned with entity_names.normalize — the participant
    rule — so an investor's holdings and its deals meet on one page.

    Returns (by_investor, by_company, display_name, group)."""
    from src.ingest.shp_holders import OUT as HOLDERS
    from src.research.entity_names import normalize
    if not HOLDERS.exists():
        return {}, {}, {}, {}
    q = duckdb.connect()
    try:
        raw = q.execute(f"SELECT DISTINCT name FROM read_parquet('{HOLDERS}') WHERE tbl = 'PUBLIC' AND NOT is_label").fetchall()
        q.execute("CREATE TEMP TABLE nm (name VARCHAR, ent VARCHAR)")
        q.executemany("INSERT INTO nm VALUES (?, ?)", [(n, normalize(n)) for (n,) in raw])
        rows = q.execute(f"""
            WITH h AS (
                SELECT h.isin, any_value(h.symbol) sym, any_value(h.company) co, h.quarter_end q, nm.ent,
                       sum(h.pct) pct, any_value(h.grp) grp, any_value(h.name) raw,
                       h.source_file
                FROM read_parquet('{HOLDERS}') h JOIN nm USING (name)
                WHERE h.tbl = 'PUBLIC' AND NOT h.is_label AND h.quarter_end <> ''
                GROUP BY h.isin, h.quarter_end, nm.ent, h.source_file),
            -- one filing per (company, quarter): the latest-named file wins a revision
            f AS (SELECT isin, q, max(source_file) sf FROM h GROUP BY 1, 2),
            hh AS (SELECT h.* FROM h JOIN f ON f.isin = h.isin AND f.q = h.q AND f.sf = h.source_file),
            qs AS (SELECT isin, q, row_number() OVER (PARTITION BY isin ORDER BY q DESC) rk FROM f),
            cur AS (SELECT isin, q FROM qs WHERE rk = 1),
            prv AS (SELECT isin, q FROM qs WHERE rk = 2),
            a AS (SELECT hh.* FROM hh JOIN cur USING (isin, q)),
            b AS (SELECT hh.* FROM hh JOIN prv USING (isin, q)),
            first_seen AS (SELECT isin, ent, min(q) fq FROM hh GROUP BY 1, 2)
            SELECT coalesce(a.isin, b.isin), coalesce(a.sym, b.sym), coalesce(a.co, b.co), coalesce(a.ent, b.ent),
                   coalesce(a.grp, b.grp), coalesce(a.raw, b.raw), cur.q, a.pct, b.pct, fs.fq
            FROM a FULL JOIN b ON a.isin = b.isin AND a.ent = b.ent
            JOIN cur ON cur.isin = coalesce(a.isin, b.isin)
            JOIN first_seen fs ON fs.isin = coalesce(a.isin, b.isin) AND fs.ent = coalesce(a.ent, b.ent)
            ORDER BY 1, 8 DESC NULLS LAST""").fetchall()
        spell = dict(q.execute("SELECT ent, coalesce(mode(name) FILTER (WHERE name <> lower(name)), mode(name)) FROM nm GROUP BY 1").fetchall())
    finally:
        q.close()
    by_inv: dict[str, list] = defaultdict(list)
    by_co: dict[str, dict] = defaultdict(lambda: {"now": [], "exited": []})
    group: dict[str, str] = {}
    for isin, sym, co, ent, grp, _raw, qcur, pct, prev, fq in rows:
        status = ("exited" if pct is None else "new" if prev is None else
                  "up" if pct > prev + 0.005 else "down" if pct < prev - 0.005 else "same")
        rec = [round(pct, 2) if pct is not None else None, round(prev, 2) if prev is not None else None, status, fq]
        group.setdefault(ent, grp)
        if pct is not None or prev is not None:
            by_inv[ent].append([sym, sym_file(sym), co, qcur, *rec])
        entry = [spell.get(ent, ent), slug(ent), grp, *rec]
        by_co[isin]["quarter"] = qcur
        if pct is not None and pct < 0.01:          # a 0.00% line is a filing artefact, not a holder
            continue
        by_co[isin]["exited" if pct is None else "now"].append(entry)
    return by_inv, by_co, spell, group


def _add_widest_holders(out: Path, held: tuple) -> None:
    """insights.json gains the investors named (>1%) in the most companies at
    their latest filings — a count of where they are, not how they did."""
    by_inv, _co, spell, group = held
    rows = []
    for ent, hs in by_inv.items():
        now = [h for h in hs if h[4] is not None]
        if not now:
            continue
        rows.append([spell.get(ent, ent), slug(ent), GROUP_TYPE.get(group.get(ent, ""), "UNKNOWN"), len(now),
                     sum(h[6] == "new" for h in now), sum(h[6] == "exited" for h in hs)])
    rows.sort(key=lambda r: -r[3])
    path = out / "insights.json"
    doc = json.loads(path.read_text()) if path.exists() else {}
    doc["widest_holders"] = _cols(["who", "pid", "type", "companies", "new", "exited"], rows[:40])
    path.write_text(json.dumps(doc, separators=(",", ":")))


def _add_fund_counts(out: Path, mf: dict | None, sym_of: dict[str, tuple]) -> None:
    """insights.json gains, for the latest month of scheme portfolios, the
    companies held by the most schemes, and those the most schemes newly
    bought or fully sold — counts of schemes, not a view on the stock."""
    if not mf:
        return
    rows = []
    for isin, h in mf["by_isin"].items():
        if isin not in sym_of:
            continue
        sym, sid, co = sym_of[isin]
        rows.append([sym, sid, co, len(h["rows"]), len({r[0] for r in h["rows"]}),
                     round(sum(r[4] or 0 for r in h["rows"]), 1), sum(1 for r in h["rows"] if r[7] == "NEW"),
                     len(h["exits"])])
    cols = ["sym", "sid", "co", "schemes", "houses", "cr", "new", "exited"]
    path = out / "insights.json"
    doc = json.loads(path.read_text()) if path.exists() else {}
    doc["funds"] = {"as_of": mf["latest"],
                    "most_held": _cols(cols, sorted(rows, key=lambda r: -r[3])[:30]),
                    "most_new": _cols(cols, sorted((r for r in rows if r[6]), key=lambda r: -r[6])[:30]),
                    "most_exited": _cols(cols, sorted((r for r in rows if r[7]), key=lambda r: -r[7])[:30])}
    path.write_text(json.dumps(doc, separators=(",", ":")))


def _archive_rows(report: str) -> list[dict]:
    """Every row of every archived NSE file of one report type, newest file last."""
    out: list[dict] = []
    for f in sorted((ARCHIVE / report / "NSE").glob("**/*.json.gz")):
        try:
            d = json.loads(gzip.decompress(f.read_bytes()))
        except (OSError, ValueError):
            continue
        out.extend(d if isinstance(d, list) else d.get("data", []) if isinstance(d, dict) else [])
    return out


def _nse_date(s: str | None) -> str | None:
    for fmt in ("%d-%b-%Y", "%d-%b-%Y %H:%M:%S", "%d-%m-%Y"):
        try:
            return datetime.strptime((s or "").strip(), fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _num(r: dict, k: str) -> float:
    try:
        return float((r.get(k) or "0").strip() or 0)
    except ValueError:
        return 0.0


def market_structure(env: str | None = None) -> dict:
    """Part C of the site plan, per symbol: official industry and current index
    membership (NSE constituent files), every corporate action and dividend
    since 2005 (the archived corporate-action feed, all subjects), recent
    announcements and board meetings, and the latest promoter-pledge row."""
    from src.research.entity_names import normalize
    q = duckdb.connect()
    industry: dict[str, str] = {}
    indices: dict[str, list[str]] = defaultdict(list)
    try:
        cons = COLLECTED / "constituents" / "constituents.parquet"
        if cons.exists():
            for sym, ind, key in q.execute(f"""
                    WITH l AS (SELECT index_key, max(snapshot_date) d FROM read_parquet('{cons}') GROUP BY 1)
                    SELECT c.symbol, c.industry, c.index_key FROM read_parquet('{cons}') c
                    JOIN l ON l.index_key = c.index_key AND l.d = c.snapshot_date ORDER BY 3""").fetchall():
                if ind:
                    industry.setdefault(sym, ind)
                indices[sym].append(key)
        shp_names = {}
        shp = COLLECTED / "shp" / "shp_holdings.parquet"
        if shp.exists():
            shp_names = {normalize(co): sym for sym, co in q.execute(
                f"SELECT any_value(symbol), company FROM read_parquet('{shp}') WHERE company IS NOT NULL GROUP BY 2").fetchall()}
    finally:
        q.close()
    actions: dict[str, set] = defaultdict(set)
    for r in _archive_rows("CORPACT"):
        sym, ex = (r.get("symbol") or "").upper(), _nse_date(r.get("exDate"))
        if sym and ex and r.get("subject"):
            actions[sym].add((ex, r["subject"].strip(), _nse_date(r.get("recDate")) or ""))
    ann: dict[str, dict] = defaultdict(dict)
    feed = []
    #: name -> symbol as NSE's own filings pair them (announcements, board
    #: meetings). The pledge feed names a company and nothing else; matching it
    #: on the shareholding filings' names alone left 211 of 1,548 companies
    #: unmatched (2026-10-16); these and the security master bring that to 24.
    filed_names: dict[str, str] = {}
    for r in _archive_rows("ANNOUNCE"):
        sym, d = (r.get("symbol") or "").upper(), r.get("sort_date") or ""
        if not sym or not d:
            continue
        key = r.get("seq_id") or (d, r.get("desc"))
        row = [d[:16], r.get("desc"), (r.get("attchmntText") or "")[:400], r.get("attchmntFile")]
        ann[sym][key] = row
        feed.append([sym, sym_file(sym), r.get("sm_name"), *row, key])
        if r.get("sm_name"):
            filed_names.setdefault(normalize(r["sm_name"]), sym)
        ind = (r.get("smIndustry") or "").strip()
        if ind and ind != "-":
            industry.setdefault(sym, ind)
    meet: dict[str, set] = defaultdict(set)
    for r in _archive_rows("BOARDMTG"):
        sym, d = (r.get("bm_symbol") or "").upper(), _nse_date(r.get("bm_date"))
        if sym and d:
            meet[sym].add((d, (r.get("bm_purpose") or "").strip(), (r.get("bm_desc") or "")[:300]))
            if r.get("sm_name"):
                filed_names.setdefault(normalize(r["sm_name"]), sym)
            ind = (r.get("sm_indusrty") or "").strip()
            if ind and ind != "-":
                industry.setdefault(sym, ind)
    pledge: dict[str, list] = {}
    pl_rows = _archive_rows("PLEDGE")
    unmatched = 0
    master_names: dict[str, str] = {}
    try:
        mc = duckdb.connect(str(research_db(env)), read_only=True)
        try:
            master_names = {normalize(n): sym for sym, n in mc.execute(
                "SELECT canonical_symbol, company_name FROM security_master WHERE company_name IS NOT NULL").fetchall()}
        finally:
            mc.close()
    except duckdb.Error:
        pass
    for r in pl_rows:
        n = normalize(r.get("comName") or "")
        sym = shp_names.get(n) or filed_names.get(n) or master_names.get(n)
        if not sym:
            unmatched += 1
            continue
        pledge[sym] = [r.get("shp"), *(_num(r, k) for k in ("percPromoterHolding", "percPromoterShares",
                                                            "percTotShares", "percSharesPledged")),
                       _nse_date(r.get("broadcastDt"))]
    seen = set()
    feed_u = []
    for f in sorted(feed, key=lambda x: x[3], reverse=True):
        if f[-1] in seen:
            continue
        seen.add(f[-1])
        feed_u.append(f[:-1])
    return {"industry": industry, "indices": indices, "actions": actions, "ann": ann, "meet": meet,
            "pledge": pledge, "feed": feed_u, "pledge_unmatched": unmatched, "pledge_rows": len(pl_rows)}


def export_filings(out: Path, ms: dict) -> None:
    """data/filings.json: the newest announcements, the board meetings ahead
    (a results calendar), and promoter pledging — as filed."""
    today = datetime.now(UTC).date().isoformat()
    upcoming = sorted(((d, sym, sym_file(sym), p, desc) for sym, ms_ in ms["meet"].items()
                       for d, p, desc in ms_ if d >= today), key=lambda x: (x[0], x[1]))
    pl = sorted(([sym, sym_file(sym), *v] for sym, v in ms["pledge"].items() if v[2] > 0), key=lambda x: -x[4])
    doc = {"announcements": _cols(["sym", "sid", "co", "t", "desc", "text", "file"], ms["feed"][:600]),
           "meetings": _cols(["d", "sym", "sid", "purpose", "desc"], [list(x) for x in upcoming[:400]]),
           "pledges": _cols(["sym", "sid", "shp_q", "promoter_pct", "pledged_pct_of_promoter", "pledged_pct_of_total",
                             "depository_pledged_pct", "as_of"], pl),
           "industries": len(set(ms["industry"].values())), "industry_coverage": len(ms["industry"])}
    (out / "filings.json").write_text(json.dumps(doc, separators=(",", ":")))


def fundamentals() -> dict[str, list]:
    """symbol -> quarterly results, newest first: consolidated where the
    company files it, standalone otherwise (src/ingest/results.py)."""
    path = COLLECTED / "results" / "results_quarterly.parquet"
    if not path.exists():
        return {}
    q = duckdb.connect()
    try:
        rows = q.execute(f"""
            SELECT symbol, qe, consolidated, revenue, other_income, pbt, pat, coalesce(pat_owners, pat), eps,
                   finance_costs, depreciation, paid_up, face_value, bank, filed
            FROM (SELECT *, row_number() OVER (PARTITION BY symbol, qe ORDER BY consolidated DESC, filed DESC) rk
                  FROM read_parquet('{path}')) WHERE rk = 1 ORDER BY symbol, qe DESC""").fetchall()
    finally:
        q.close()
    out: dict[str, list] = defaultdict(list)
    r2 = lambda v: None if v is None else round(v, 2)  # noqa: E731
    for sym, qe, cons, rev, oi, pbt, pat, pat_o, eps, fin, dep, paid, fv, bank, filed in rows:
        shares = (paid / fv) if paid and fv else None          # crore shares (paid-up Rs cr / face Rs)
        out[sym].append([qe, bool(cons), r2(rev), r2(oi), r2(pbt), r2(pat), r2(pat_o), r2(eps), r2(fin), r2(dep),
                         shares, bool(bank), filed])
    for res in out.values():
        for r, sh in zip(res, share_counts([(r[10], r[6], r[7]) for r in res]), strict=True):
            r[10] = None if sh is None else round(sh, 4)
    for sym, res in out.items():
        if gone := withhold_mis_scaled(res):
            WITHHELD[sym] = gone
    return out


#: Symbol -> quarters withhold_mis_scaled blanked, for the page to say so.
WITHHELD: dict[str, list[str]] = {}
#: Rupee fields of a results row (RESULT_COLS): withheld together, as a filing that
#: mis-scales its revenue mis-scales its statement.
_RUPEE_AT = (2, 3, 4, 5, 6, 8, 9)


def withhold_mis_scaled(res: list[list]) -> list[str]:
    """Blank a quarter whose revenue is an exact power of ten off both neighbours
    that agree with each other, and return those quarters.

    The filing itself is wrong: COROMANDEL's 2026-03-31 states Rs 60 crore against
    about Rs 6,000 crore either side, and PFC, SRF and LICHSGFIN do the same; 128 of
    73,798 quarters (2026-11-06). Blanked, never rescaled: a guess at the true figure
    would read as a filed one. The EPS is kept: it is not stated in rupee scale.
    """
    out = []
    for i in range(1, len(res) - 1):
        a, x, b = res[i - 1][2], res[i][2], res[i + 1][2]
        if not (a and x and b and a > 0 and x > 0 and b > 0) or abs(math.log10(a / b)) > 0.3:
            continue
        off = math.log10(x / math.sqrt(a * b))
        # Tighter at ten times, which a lumpy business can truly do in a quarter;
        # a hundred times cannot be real, and COROMANDEL's sits 0.15 from it.
        if round(off) != 0 and abs(off - round(off)) < (0.12 if abs(round(off)) == 1 else 0.25):
            out.append(i)
    for i in out:
        for k in _RUPEE_AT:
            res[i][k] = None
    return [res[i][0] for i in out]


#: Powers of ten a filing's paid-up capital has been seen in, other than crore:
#: rupees (10^7), lakh (10^5), thousand (10^4) and odd ones in between.
#: Measured 2026-10-31: 1,226 of 48,537 quarters disagree with profit / EPS by
#: one of these; FIVESTAR's showed a market cap of Rs 1,17,14,20,989 crore.
_SCALES = range(2, 8)


def share_counts(rows: list[tuple]) -> list[float | None]:
    """Shares in crore for each quarter of one company, newest first, from
    (paid-up / face value, profit to owners, EPS) per quarter.

    Filings give paid-up capital in crore, but some in rupees, thousands or
    lakh. Where profit / EPS gives an independent count (crore profit / rupee
    EPS = crore shares) and paid-up / face value is a power of ten (100 or
    more) above it, the power is divided out. A quarter without a usable EPS
    is checked the same way against the company's median corrected count.
    Counts BELOW profit / EPS are left alone: there it is the profit or the EPS
    that is misreported, and neither is used for the share count."""
    def snap(sh: float, ref: float) -> float:
        lg = math.log10(sh / ref)
        k = round(lg)
        return sh / 10 ** k if k in _SCALES and abs(lg - k) < 0.35 else sh

    out: list[float | None] = []
    for sh, pat, eps in rows:
        if sh and sh > 0 and pat and eps and abs(eps) > 0.05 and pat / eps > 0:
            sh = snap(sh, pat / eps)
        out.append(sh if sh and sh > 0 else None)
    good = sorted(v for v, (_, pat, eps) in zip(out, rows, strict=True)
                  if v and pat and eps and abs(eps) > 0.05 and pat / eps > 0)
    if good:
        med = good[len(good) // 2]
        out = [None if v is None else snap(v, med) for v in out]
    # A single quarter ten times off both its neighbours, which agree with each
    # other, is a unit slip too (KIOCL, RELIABLE). A real split moves every
    # later quarter, never one alone, so this cannot undo one.
    for i in range(1, len(out) - 1):
        a, v, b = out[i - 1], out[i], out[i + 1]
        if a and v and b and abs(math.log10(a / b)) < 0.05:
            k = round(math.log10(v / a))
            if k != 0 and abs(math.log10(v / a) - k) < 0.05:
                out[i] = v / 10 ** k
    # The newest quarter has no newer neighbour, and some filings give a count
    # that is no power of ten off (BHARTIARTL 0.002 crore against 609; FIVESTAR
    # was the other kind). More than ~16 times off the two quarters before it,
    # which agree, it takes theirs: no split or bonus on record moves a count
    # that far in one quarter (BAJAJFINSV's 2022 split plus bonus was 10 times).
    if len(out) >= 3 and all(out[:3]):
        v, a, b = out[:3]
        if abs(math.log10(a / b)) < 0.05 and abs(math.log10(v / a)) > 1.2:
            out[0] = a
    return out


RESULT_COLS = ["qe", "consolidated", "revenue", "other_income", "pbt", "pat", "pat_owners", "eps",
               "finance_costs", "depreciation", "shares_cr", "bank", "filed"]


def valuation(res: list, last_close: float | None) -> dict | None:
    """Market cap and trailing P/E from the latest close: market cap = close x
    shares outstanding; P/E = market cap / the last four quarters' profit to
    owners — profit, not summed EPS, so a bonus inside the window cannot
    distort it. Needs four consecutive quarters; None otherwise."""
    if not res or not last_close:
        return None
    shares = res[0][10]
    pat, eps = res[0][6], res[0][7]
    # Still more than 30 times off profit / EPS after share_counts: one of the
    # three is misreported and nothing says which (14 companies on 2026-10-31).
    # No market cap beats a wrong one.
    if shares and pat and eps and abs(eps) > 0.05 and pat / eps > 0 and abs(math.log10(shares * eps / pat)) > 1.5:
        shares = None
    mcap = last_close * shares if shares else None          # Rs crore: price x crore shares
    ttm = None
    if len(res) >= 4:
        qs = [date.fromisoformat(r[0]) for r in res[:4]]
        if (qs[0] - qs[3]).days <= 290 and all(r[6] is not None for r in res[:4]):
            ttm = sum(r[6] for r in res[:4])
    rev_ttm = sum(r[2] for r in res[:4]) if len(res) >= 4 and all(r[2] is not None for r in res[:4]) else None
    return {"close": last_close, "mcap_cr": None if mcap is None else round(mcap, 0),
            "ttm_profit_cr": None if ttm is None else round(ttm, 1),
            "ttm_revenue_cr": None if rev_ttm is None else round(rev_ttm, 1),
            "pe": round(mcap / ttm, 1) if mcap and ttm and ttm > 0 else None,
            "as_of_quarter": res[0][0]}


def _holders_doc(h: dict | None) -> dict | None:
    if not h:
        return None
    cols = ["name", "slug", "group", "pct", "prev_pct", "status", "first_q"]
    return {"quarter": h.get("quarter"), "now": _cols(cols, h["now"]), "exited": _cols(cols, h["exited"])}


def is_equity_isin(isin: str) -> bool:
    """An Indian company's equity share: INE + issuer + security type 01.
    Debentures (07/08), CPs (14), CDs (16), fund units (INF) and government
    paper (IN0..) are not equity."""
    return len(isin) == 12 and isin.startswith("INE") and isin[7:9] == "01"


def latest_full_month(as_ofs: list[str]) -> str:
    """The newest month most schemes have reached.

    Not simply the newest. On 2026-11-05 one scheme's 5 rows dated 31 October
    made October "latest" over 1,300 schemes at September, and the fund holdings
    went blank on all 4,417 stock pages. Houses file through the month, so a new
    month counts once it holds at least half as many schemes as the fullest one.
    """
    counts = Counter(as_ofs)
    full = max(counts.values())
    return max(m for m, n in counts.items() if n >= full / 2)


def mf_holdings() -> dict | None:
    """The monthly scheme portfolios (src/ingest/mf_portfolios.py), shaped for
    the site: per scheme its latest month and the one before; per ISIN the
    schemes holding it in the latest month. Levels and changes as filed."""
    from src.ingest import mf_portfolios as mfi
    if not mfi.OUT.exists():
        return None
    q = duckdb.connect()
    try:
        # One file per (house, scheme, month): a house that serves the same
        # month twice (a corrected file) must not count it twice.
        rows = q.execute(f"""
            WITH t AS (SELECT * FROM read_parquet('{mfi.OUT}') WHERE as_of IS NOT NULL),
            n AS (SELECT amc, scheme, as_of, source_file, count(*) k FROM t GROUP BY ALL),
            pick AS (SELECT amc, scheme, as_of, arg_max(source_file, k) f FROM n GROUP BY ALL)
            SELECT t.amc, t.scheme, t.as_of, t.isin, any_value(t.name), any_value(t.industry),
                   sum(t.qty), sum(t.value_cr), sum(t.pct)
            FROM t JOIN pick p ON p.amc = t.amc AND p.scheme = t.scheme AND p.as_of = t.as_of AND p.f = t.source_file
            GROUP BY ALL ORDER BY 1, 2, 3""").fetchall()
    finally:
        q.close()
    if not rows:
        return None
    try:
        import yaml
        names = {s["amc"]: s.get("name", s["amc"]) for s in yaml.safe_load(
            (ROOT / "configs" / "mf_sources.yml").read_text())["sources"]}
    except (OSError, KeyError, TypeError):
        names = {}
    month: dict[tuple, dict[str, dict[str, list]]] = defaultdict(lambda: defaultdict(dict))
    for amc, scheme, as_of, isin, name, ind, qty, cr, pct in rows:
        month[(amc, scheme)][as_of][isin] = [name, ind, qty, cr, pct]
    schemes = {}
    for (amc, scheme), by in month.items():
        ms = sorted(by)
        last = ms[-1]
        prev = ms[-2] if len(ms) > 1 and (date.fromisoformat(last) - date.fromisoformat(ms[-2])).days <= 45 else None
        schemes[(amc, scheme)] = {"amc": amc, "house": names.get(amc, amc), "scheme": scheme,
                                  "sid": slug(f"{amc} {scheme}"), "as_of": last, "prev_as_of": prev,
                                  "now": by[last], "prev": by[prev] if prev else {}}
    latest = latest_full_month([s["as_of"] for s in schemes.values()])
    by_isin: dict[str, dict] = defaultdict(lambda: {"rows": [], "exits": []})
    for s in schemes.values():
        if s["as_of"] != latest:
            continue
        for isin, (_n, _i, qty, cr, pct) in s["now"].items():
            if not is_equity_isin(isin):
                continue
            p = s["prev"].get(isin) if s["prev_as_of"] else None
            status = None if not s["prev_as_of"] else "NEW" if p is None else None
            chg = None if not s["prev_as_of"] or qty is None else qty - ((p[2] or 0) if p else 0)
            by_isin[isin]["rows"].append([s["house"], s["scheme"], s["sid"], qty, _r(cr, 2), _r(pct, 2),
                                          chg, status])
        for isin, (_n, _i, qty, _cr, _p) in s["prev"].items():
            if is_equity_isin(isin) and isin not in s["now"]:
                by_isin[isin]["exits"].append([s["house"], s["scheme"], s["sid"], qty])
    houses = sorted({(s["amc"], s["house"]) for s in schemes.values()})
    cover = [[a, h, max(s["as_of"] for s in schemes.values() if s["amc"] == a),
              sum(1 for s in schemes.values() if s["amc"] == a and s["as_of"] == latest)] for a, h in houses]
    return {"latest": latest, "schemes": schemes, "by_isin": dict(by_isin), "coverage": cover}


def _r(v, n):
    return None if v is None else round(v, n)


MF_COLS = ["house", "scheme", "fid", "qty", "cr", "pct_of_scheme", "qty_chg", "status"]


def mf_stock_doc(mf: dict | None, isin: str | None, shares_cr: float | None) -> dict | None:
    """The schemes holding one company in the latest month, largest first."""
    if not mf or not isin or isin not in mf["by_isin"]:
        return None
    h = mf["by_isin"][isin]
    rows = sorted(h["rows"], key=lambda r: -(r[4] or 0))
    qty = sum(r[3] or 0 for r in rows)
    return {"as_of": mf["latest"], "schemes": len(rows), "houses": len({r[0] for r in rows}),
            "qty": qty, "cr": _r(sum(r[4] or 0 for r in rows), 1),
            "pct_of_company": round(100 * qty / (shares_cr * 1e7), 2) if shares_cr and qty else None,
            "new": sum(1 for r in rows if r[7] == "NEW"), "held": _cols(MF_COLS, rows),
            "exited": _cols(["house", "scheme", "fid", "prev_qty"], h["exits"])}


def export_funds(out: Path, mf: dict | None, sym_of: dict[str, tuple]) -> int:
    """funds.json (every scheme, every house's latest month) and
    funds/<sid>.json (a scheme's holdings with last month's change)."""
    if not mf:
        return 0
    (out / "funds").mkdir(parents=True, exist_ok=True)
    index = []
    for s in mf["schemes"].values():
        eq, other = [], []
        for isin, (name, ind, qty, cr, pct) in s["now"].items():
            sym, sid, co = sym_of.get(isin, (None, None, None))
            if is_equity_isin(isin):
                p = s["prev"].get(isin) if s["prev_as_of"] else None
                eq.append([isin, sym, sid, co or name, ind, qty, _r(cr, 2), _r(pct, 2),
                           None if not s["prev_as_of"] or qty is None else qty - ((p[2] or 0) if p else 0),
                           None if not s["prev_as_of"] else "NEW" if p is None else None])
            else:
                other.append([isin, name, ind, _r(cr, 2), _r(pct, 2)])
        exits = []
        for isin, p in s["prev"].items():
            if is_equity_isin(isin) and isin not in s["now"]:
                sym, sid, co = sym_of.get(isin, (None, None, None))
                exits.append([isin, sym, sid, co or p[0], p[2]])
        eq.sort(key=lambda r: -(r[6] or 0))
        other.sort(key=lambda r: -(r[3] or 0))
        total = sum(v[3] or 0 for v in s["now"].values())
        doc = {k: s[k] for k in ("amc", "house", "scheme", "sid", "as_of", "prev_as_of")}
        doc.update({"total_cr": _r(total, 1), "equity_cr": _r(sum(r[6] or 0 for r in eq), 1),
                    "equity_pct": _r(sum(r[7] or 0 for r in eq), 1),
                    "equity": _cols(["isin", "sym", "sid", "co", "industry", "qty", "cr", "pct", "qty_chg", "status"], eq),
                    "exited": _cols(["isin", "sym", "sid", "co", "prev_qty"], exits),
                    "other": _cols(["isin", "name", "rating", "cr", "pct"], other[:60]), "other_n": len(other)})
        (out / "funds" / f"{s['sid']}.json").write_text(json.dumps(doc, separators=(",", ":")))
        index.append([s["sid"], s["amc"], s["house"], s["scheme"], s["as_of"], len(eq), doc["total_cr"],
                      doc["equity_pct"], sum(1 for r in eq if r[9] == "NEW"), len(exits)])
    index.sort(key=lambda r: (r[2], -(r[6] or 0)))
    (out / "funds.json").write_text(json.dumps(
        {"latest": mf["latest"], "coverage": _cols(["amc", "house", "latest", "schemes_latest"], mf["coverage"]),
         **_cols(["fid", "amc", "house", "scheme", "as_of", "stocks", "total_cr", "equity_pct", "new", "exits"], index)},
        separators=(",", ":")))
    return len(index)


def export_participants(out: Path, rows: list, env: str | None = None,
                        holdings: tuple | None = None) -> int:
    """data/participants/<slug>.json: identity, every spelling filed, how the
    type was set, behaviour (descriptive only), deals. No returns, no rank."""
    (out / "participants").mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(research_db(env)), read_only=True)
    try:
        master = {name: dict(zip(("type", "how", "conf", "status", "notes", "house"), rest, strict=True))
                  for name, *rest in con.execute("""
                    SELECT pm.canonical_name, pm.participant_type, pm.classification_method,
                           pm.confidence_level, pm.review_status, pm.review_notes, fh.canonical_name
                    FROM participant_master pm
                    LEFT JOIN participant_master fh ON fh.participant_id = pm.parent_group_id""").fetchall()}
        for name, fixed in site_labels().items():
            if name in master:
                master[name].update(type=fixed, how=labels.METHOD)
        spellings: dict[str, list] = defaultdict(list)
        for name, raw in con.execute("""
                SELECT pm.canonical_name, pa.raw_name FROM participant_aliases pa
                JOIN participant_master pm USING (participant_id) ORDER BY 1, 2""").fetchall():
            spellings[name].append(raw)
    finally:
        con.close()
    by: dict[str, list] = defaultdict(list)
    for r in rows:
        d = _deal(r)
        by[d["who"]].append([r[0], d["sym"], d["sid"], d["side"], d["qty"], d["px"], d["cr"],
                             int(d["rt"]), d["kind"], d["client"]])
    by_inv, _by_co, spell, hgroup = holdings or ({}, {}, {}, {})
    index = []
    for who in set(by) | set(by_inv):
        ds = by.get(who, [])
        m = master.get(who, {})
        t = m.get("type") or GROUP_TYPE.get(hgroup.get(who, ""), "UNKNOWN")
        held = sorted(by_inv.get(who, []), key=lambda h: -(h[4] or 0))
        years: dict[str, list[int]] = defaultdict(lambda: [0, 0])
        for x in ds:
            years[x[0][:4]][0 if x[3] == "BUY" else 1] += 1
        stocks: dict[str, int] = defaultdict(int)
        for x in ds:
            stocks[x[1]] += 1
        stock_days = {(x[0], x[1]) for x in ds}
        rt_days = {(x[0], x[1]) for x in ds if x[7]}
        holding_now = [h for h in held if h[4] is not None]
        # Shown as most often FILED ("LIC of India"); matched on the cleaned
        # form, which strips words like CORPORATION ("LIFE INSURANCE OF INDIA").
        doc = {"name": spell.get(who) or who, "slug": slug(who), "type": t, "cleaned": who,
               "label": TYPE_LABEL.get(t, t),
               "how": m.get("how") or ("FILING_CATEGORY" if who in hgroup else None),
               "confidence": m.get("conf"), "review": m.get("status"),
               "notes": m.get("notes"), "house": house_name(m.get("house")), "spellings": spellings.get(who, []),
               "stats": {"deals": len(ds), "buys": sum(x[3] == "BUY" for x in ds),
                         "sells": sum(x[3] != "BUY" for x in ds),
                         "stock_days": len(stock_days),
                         "roundtrip_share": round(len(rt_days) / len(stock_days), 4) if stock_days else 0.0,
                         "first": ds[0][0] if ds else None, "last": ds[-1][0] if ds else None,
                         "years": sorted([y, b, s] for y, (b, s) in years.items()),
                         "top_stocks": sorted(stocks.items(), key=lambda kv: -kv[1])[:15],
                         "companies_held": len(holding_now)},
               "holdings": _cols(["sym", "sid", "co", "q", "pct", "prev_pct", "status", "first_q"], held),
               "deals": _cols(["d", "sym", "sid", "side", "qty", "px", "cr", "rt", "kind", "client"], ds)}
        (out / "participants" / f"{slug(who)}.json").write_text(json.dumps(doc, separators=(",", ":")))
        index.append([doc["name"], TYPE_LABEL.get(t, t), slug(who), len(ds), t, len(holding_now)])
    index.sort(key=lambda x: -x[3])
    (out / "participants.json").write_text(json.dumps(index, separators=(",", ":")))
    # The header search: every stock, participant and fund scheme, as [label, kind, key, hint].
    stocks = json.loads((out / "stocks.json").read_text()) if (out / "stocks.json").exists() else []
    funds = json.loads((out / "funds.json").read_text())["rows"] if (out / "funds.json").exists() else []
    search = ([[r[0], "s", r[2], r[1]] for r in stocks] + [[r[0], "p", r[2], r[1]] for r in index]
              + [[r[3], "f", r[0], r[2]] for r in funds])
    (out / "search.json").write_text(json.dumps(search, separators=(",", ":")))
    return len(index)


#: What runs when (launchd plists, measured 2026-10-26). Shown on the System page.
SCHEDULE = [
    {"time": "18:30", "job": "Daily collector", "what": "deals, prices, indices, flows, filings, F&O, identity, warehouse, backup, health, site"},
    {"time": "18:45", "job": "Shareholding sweep", "what": "NSE shareholding filings and their parse"},
    {"time": "21:00", "job": "Collector, second pass", "what": "the same stages again, for anything published late"},
    {"time": "21:20", "job": "Night backfill", "what": "quarterly results, BSE history, delivery, mutual-fund portfolios"},
]
_RUN_END = re.compile(r"(✅ ALL CLEAN|❌ FAILED — (\d+) stage\(s\))\s+(\d+) stages in (?:(\d+)m )?(\d+)s")


def _runs_from_log(text: str, keep: int = 14) -> list[dict]:
    """Recent collector runs from the log: start, verdict, stage count, minutes,
    and which alert channels answered. No address or chat id is kept."""
    runs: list[dict] = []
    cur: dict | None = None
    for line in text.splitlines():
        if line.startswith("--- "):
            cur = {"started": line[4:].split(" pid=")[0].strip(), "ok": None, "failed": 0,
                   "stages": None, "minutes": None, "email": None, "telegram": None}
            runs.append(cur)
        elif cur is not None and (m := _RUN_END.search(line)):
            cur["ok"] = m.group(1).startswith("✅")
            cur["failed"] = int(m.group(2) or 0)
            cur["stages"] = int(m.group(3))
            cur["minutes"] = round(int(m.group(4) or 0) + int(m.group(5)) / 60)
        elif cur is not None:
            # One stage-alert line reports every channel ("email=email sent ...;
            # telegram=telegram FAILED ..."): each channel is read on its own.
            if "email sent" in line or "email=" in line:
                cur["email"] = "sent" if "email sent" in line else "failed"
            if "telegram sent" in line or "telegram FAILED" in line:
                cur["telegram"] = "failed" if "telegram FAILED" in line else "sent"
    return [r for r in runs if r["ok"] is not None][-keep:][::-1]


def _archive_inventory() -> list[dict]:
    """Files and bytes per raw-archive source: the layer that is never changed."""
    from src.common.paths import ARCHIVE
    out = []
    for d in sorted(p for p in Path(ARCHIVE).iterdir() if p.is_dir()):
        n = b = 0
        for f in d.rglob("*"):
            if f.is_file():
                n += 1
                b += f.stat().st_size
        out.append({"source": d.name, "files": n, "mb": round(b / 1e6)})
    return out


#: (label, files under ROOT/data, date column, what one row is). Parquet only:
#: read in memory, never through the research database.
COVERAGE = [
    ("Daily prices", "prod/warehouse/price_spine_adj/**/*.parquet", "date", "stock-day"),
    ("F&O contracts", "prod/warehouse/fno_spine/**/*.parquet", "date", "contract-day"),
    ("Delivery position", "raw/collected/delivery/delivery.parquet", "date", "stock-day"),
    ("Index total return", "raw/collected/index_tri/index_tri.parquet", "date", "index-day"),
    ("Foreign investor flows", "raw/collected/fpi_nsdl/fpi_investment.parquet", "reporting_date", "day"),
    ("Insider trades", "raw/collected/insider/insider_trading.parquet", "filing_date", "filing"),
    ("Corporate actions", "raw/collected/corporate_actions/corporate_actions.parquet", "date", "action"),
    ("Quarterly results", "raw/collected/results/results_quarterly.parquet", "qe", "company-quarter"),
    ("Shareholding patterns", "raw/collected/shp/shp_holdings.parquet", "quarter_end", "holding row"),
    ("Named shareholders", "raw/collected/shp/shp_named_holders.parquet", "quarter_end", "holder row"),
    ("Mutual-fund portfolios", "raw/collected/mf/mf_portfolios.parquet", "as_of", "holding"),
]


def _coverage() -> list[dict]:
    """Rows and date range per collected dataset, for the Overview."""
    out = []
    con = duckdb.connect()
    try:
        for label, rel, col, unit in COVERAGE:
            f = ROOT / "data" / rel
            try:
                n, lo, hi = con.execute(
                    f"SELECT count(*), min(CAST({col} AS VARCHAR)), max(CAST({col} AS VARCHAR)) "
                    f"FROM read_parquet('{f}', hive_partitioning=true)").fetchone()
                out.append({"dataset": label, "rows": int(n), "from": (lo or "")[:10], "to": (hi or "")[:10], "unit": unit})
            except Exception as exc:  # noqa: BLE001 - one missing file is not the page failing
                out.append({"dataset": label, "error": type(exc).__name__})
    finally:
        con.close()
    return out


def export_system(out: Path, logs: Path | None = None) -> dict:
    """system.json for the System page: schedule, recent runs, the last run's
    stages, alert channels, backup and the raw archive. Files only — no
    database is opened, so it can be rebuilt at any hour."""
    logs = logs or ROOT / "logs"
    doc: dict = {"built_at": datetime.now(UTC).isoformat(timespec="seconds"), "schedule": SCHEDULE}
    try:
        cl = sorted(logs.glob("collect_*.log"))
        doc["runs"] = _runs_from_log("\n".join(p.read_text(errors="ignore") for p in cl[-2:]))
    except Exception as exc:  # noqa: BLE001 - the site must still build
        doc["runs"] = [{"error": type(exc).__name__}]
    try:
        lines = (logs / "last_run.tsv").read_text().splitlines()
        doc["last_run"] = {"started": lines[0].replace("# started ", "").strip() if lines else None,
                           "stages": [{"stage": s, "exit": int(e), "seconds": int(t)}
                                      for s, e, t in (ln.split("\t") for ln in lines[1:] if ln.count("\t") == 2)]}
    except Exception as exc:  # noqa: BLE001
        doc["last_run"] = {"error": type(exc).__name__}
    try:
        from src.monitor import backup_state
        b = backup_state.read()
        doc["backup"] = {"taken_at": b.taken_at.isoformat(timespec="minutes") if b.taken_at else None,
                         "generations": b.generations, "sessions_at_risk": b.sessions_at_risk,
                         "commits_behind": b.commits_behind,
                         "static_verified": b.static_verified[0][1].date().isoformat() if b.static_verified else None}
    except Exception as exc:  # noqa: BLE001
        doc["backup"] = {"error": type(exc).__name__}
    try:
        doc["archive"] = _archive_inventory()
    except Exception as exc:  # noqa: BLE001
        doc["archive"] = [{"error": type(exc).__name__}]
    doc["coverage"] = _coverage()
    doc["health"] = _health()
    (out / "system.json").write_text(json.dumps(doc, indent=1))
    return doc


def _health() -> list[dict]:
    """The collector's own staleness check, so the site says when it is stale."""
    try:
        from src.monitor import health
        return [{"source": r.source_id, "last": r.last_session.isoformat() if r.last_session else None,
                 "stale": r.sessions_stale, "alerting": r.alerting} for r in health.read()]
    except Exception as exc:  # noqa: BLE001 - the site must still build
        return [{"error": type(exc).__name__}]


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=SITE_DATA)
    ap.add_argument("--since", default="2005-01-01")
    ap.add_argument("--system", action="store_true",
                    help="refresh only system.json (files, no database): safe at any hour, e.g. during a demo")
    a = ap.parse_args()
    if a.system:
        d = export_system(a.out)
        # The running site serves its built copy: refresh that too, so a page
        # reload shows the new run without a rebuild (the demo's live step).
        built = a.out.parent.parent / "dist" / "data"
        if built.is_dir():
            (built / "system.json").write_text((a.out / "system.json").read_text())
        print(f"  SYSTEM: {len(d.get('runs', []))} runs, last {d.get('runs', [{}])[0].get('started')} -> {a.out}/system.json")
        return 0
    t0 = datetime.now(UTC)
    m = export(a.out, since=a.since)
    print(f"  SITE EXPORT: {m['sessions']:,} sessions, {m['deals']:,} deals, latest {m['latest_session']} "
          f"-> {a.out} ({(datetime.now(UTC) - t0).seconds} s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
