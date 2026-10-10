"""export.py — the public website's data, written nightly as static JSON.

docs/plan/WEBSITE_PLAN.md. The site (a separate repository, deal-lens) is a
static Astro build; everything it shows comes from these files, written by
this module from the warehouse after the collector finishes.

WHAT IT WRITES under <out>/ (default: ../deal-lens/public/data):
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

import gzip
import hashlib
import json
import re
import sys
from collections import defaultdict
from datetime import UTC, date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import duckdb  # noqa: E402

from src.common.paths import ARCHIVE, COLLECTED, ROOT, research_db, warehouse_dir  # noqa: E402

SITE_DATA = ROOT.parent / "deal-lens" / "public" / "data"
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


def _deal(row) -> dict:
    (_d, sym, isin, company, client, pname, ptype, method, house, side, qty, px, val,
     exch, kind, rt, elig) = row
    t = ptype or "UNKNOWN"
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
            "source": "NSE and BSE public disclosures; participant labels by this project",
            "health": _health()}
    export_markets(out, env)
    export_insights(out, rows)
    held = named_holdings()
    ms = market_structure(env)
    export_filings(out, ms)
    meta["pledge_rows"], meta["pledge_unmatched"] = ms["pledge_rows"], ms["pledge_unmatched"]
    meta["industry_coverage"] = len(ms["industry"])
    meta["stocks"] = export_stocks(out, rows, env, held, ms)
    meta["participants"] = export_participants(out, rows, env, held)
    meta["named_holders"] = len(held[0])
    _add_widest_holders(out, held)
    (out / "meta.json").write_text(json.dumps(meta, indent=1))
    return meta


def export_markets(out: Path, env: str | None = None) -> None:
    """data/markets.json: foreign-investor flows (NSDL, 1999+), FII/DII cash,
    F&O index-futures positioning by category (2014+), the NIFTY 500 total
    return (1995+) and NIFTY 50 valuation (2021+). Levels and flows only."""
    q = duckdb.connect()
    doc: dict = {}
    try:
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
            doc["nifty50_valuation"] = _cols(["d", "close", "pe", "pb", "dy"], [[str(d), c, pe, pb, dy] for d, c, pe, pb, dy in q.execute(
                f"SELECT date, close, pe, pb, div_yield FROM read_parquet('{ic}') WHERE index_key = 'NIFTY50'"
                " AND pe IS NOT NULL ORDER BY date").fetchall()])
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
                  structure: dict | None = None) -> int:
    """data/stocks/<SYM>.json: identity, deals, quarterly ownership, insider
    trades and a WEEKLY close line (daily for ~2,300 names is ~150 MB)."""
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
    for sym, i in ident.items():
        if i["isin"]:
            isin_of.setdefault(sym, i["isin"])
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
        ins_path = COLLECTED / "insider" / "insider_trading.parquet"
        insider: dict[str, list] = defaultdict(list)
        if ins_path.exists():
            for sym, *v in q.execute(f"""
                    SELECT symbol, filing_date, person, category, transaction_type, quantity,
                           round(value / {CR}, 2), mode
                    FROM read_parquet('{ins_path}') ORDER BY symbol, filing_date""").fetchall():
                insider[sym].append(v)
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
    ms_ = structure or {"industry": {}, "indices": {}, "actions": {}, "ann": {}, "meet": {}, "pledge": {}}
    syms = set(deals) | {s for s, i in ident.items() if i["isin"] in own}
    last_day = max((r[0] for r in rows), default="")
    cut12 = f"{int(last_day[:4]) - 1}{last_day[4:]}" if last_day else ""
    screen: list[list] = []
    for sym in syms:
        i = ident.get(sym, {})
        isin = isin_of.get(sym)
        name = co.get(sym) or i.get("co")
        if (not name or name.upper() == sym) and isin in shp_co:
            name = shp_co[isin]
        doc = {"sym": sym, "co": name, "isin": isin,
               "listed": i.get("listed"), "delisted": i.get("delisted"), "reason": i.get("reason"),
               "status": i.get("status"), "history": history.get(sym, []),
               "deals": _cols(["d", "who", "pid", "type", "side", "qty", "px", "cr", "rt", "kind"], deals.get(sym, [])),
               "own": _cols(["q", *OWNERSHIP], own.get(isin, []) if isin else []),
               "insider": _cols(["d", "person", "cat", "txn", "qty", "cr", "mode"], insider.get(sym, [])),
               "px": _cols(["d", "close"], weekly.get(sym, [])),
               "holders": _holders_doc(by_co.get(isin) if isin else None),
               "industry": ms_["industry"].get(sym), "indices": ms_["indices"].get(sym, []),
               "actions": _cols(["ex", "subject", "record"], sorted(ms_["actions"].get(sym, set()), reverse=True)),
               "announcements": _cols(["t", "desc", "text", "file"],
                                      sorted(ms_["ann"].get(sym, {}).values(), key=lambda a: a[0], reverse=True)[:80]),
               "meetings": _cols(["d", "purpose", "desc"], sorted(ms_["meet"].get(sym, set()), reverse=True)[:40]),
               "results": _cols(RESULT_COLS, fund.get(sym, [])),
               "valuation": valuation(fund.get(sym, []), weekly[sym][-1][1] if weekly.get(sym) else None),
               "pledge": dict(zip(["shp_q", "promoter_pct", "pledged_pct_of_promoter", "pledged_pct_of_total",
                                   "depository_pledged_pct", "as_of"], ms_["pledge"][sym], strict=True))
                         if sym in ms_["pledge"] else None}
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


SCREEN_COLS = ["sym", "sid", "co", "industry", "indices", "close", "mcap_cr", "pe", "rev_yoy", "pat_yoy",
               "net_margin", "promoter", "fpi", "mf", "fpi_chg", "mf_chg", "pledged", "deals_12m", "holders"]


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
    chg = (lambda k: None if not last or not prev or last[k] is None or prev[k] is None
           else round(last[k] - prev[k], 2))
    h = doc.get("holders")
    return [sym, sym_file(sym), doc.get("co"), doc.get("industry"), doc.get("indices"), v.get("close"),
            v.get("mcap_cr"), v.get("pe"), yoy(2), yoy(5),
            round(100 * res[0][5] / res[0][2], 1) if res and res[0][2] and res[0][5] is not None else None,
            last[1] if last else None, last[2] if last else None, last[4] if last else None, chg(2), chg(4),
            (doc.get("pledge") or {}).get("pledged_pct_of_promoter"),
            sum(1 for d in deals if d[0] > cut12 and not d[8]),
            len(h["now"]["rows"]) if h else 0]


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
    for r in _archive_rows("ANNOUNCE"):
        sym, d = (r.get("symbol") or "").upper(), r.get("sort_date") or ""
        if not sym or not d:
            continue
        key = r.get("seq_id") or (d, r.get("desc"))
        row = [d[:16], r.get("desc"), (r.get("attchmntText") or "")[:400], r.get("attchmntFile")]
        ann[sym][key] = row
        feed.append([sym, sym_file(sym), r.get("sm_name"), *row, key])
        ind = (r.get("smIndustry") or "").strip()
        if ind and ind != "-":
            industry.setdefault(sym, ind)
    meet: dict[str, set] = defaultdict(set)
    for r in _archive_rows("BOARDMTG"):
        sym, d = (r.get("bm_symbol") or "").upper(), _nse_date(r.get("bm_date"))
        if sym and d:
            meet[sym].add((d, (r.get("bm_purpose") or "").strip(), (r.get("bm_desc") or "")[:300]))
            ind = (r.get("sm_indusrty") or "").strip()
            if ind and ind != "-":
                industry.setdefault(sym, ind)
    pledge: dict[str, list] = {}
    pl_rows = _archive_rows("PLEDGE")
    unmatched = 0
    for r in pl_rows:
        sym = shp_names.get(normalize(r.get("comName") or ""))
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
                         None if shares is None else round(shares, 4), bool(bank), filed])
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
    # The header search: every stock and every participant, as [label, kind, key, hint].
    stocks = json.loads((out / "stocks.json").read_text()) if (out / "stocks.json").exists() else []
    search = [[r[0], "s", r[2], r[1]] for r in stocks] + [[r[0], "p", r[2], r[1]] for r in index]
    (out / "search.json").write_text(json.dumps(search, separators=(",", ":")))
    return len(index)


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
    a = ap.parse_args()
    t0 = datetime.now(UTC)
    m = export(a.out, since=a.since)
    print(f"  SITE EXPORT: {m['sessions']:,} sessions, {m['deals']:,} deals, latest {m['latest_session']} "
          f"-> {a.out} ({(datetime.now(UTC) - t0).seconds} s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
