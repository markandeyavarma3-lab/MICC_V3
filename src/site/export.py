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
from datetime import UTC, datetime
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
            "type": t, "label": TYPE_LABEL.get(t, t), "how": method, "house": house,
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
    meta["stocks"] = export_stocks(out, rows, env)
    meta["participants"] = export_participants(out, rows, env)
    (out / "meta.json").write_text(json.dumps(meta, indent=1))
    return meta


def _cols(cols: list[str], rows: list[list]) -> dict:
    return {"cols": cols, "rows": rows}


def export_stocks(out: Path, rows: list, env: str | None = None) -> int:
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
        if Path(shp).exists():
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
    syms = set(deals) | {s for s, i in ident.items() if i["isin"] in own}
    for sym in syms:
        i = ident.get(sym, {})
        isin = isin_of.get(sym)
        doc = {"sym": sym, "co": co.get(sym) or i.get("co"), "isin": isin,
               "listed": i.get("listed"), "delisted": i.get("delisted"), "reason": i.get("reason"),
               "status": i.get("status"), "history": history.get(sym, []),
               "deals": _cols(["d", "who", "pid", "type", "side", "qty", "px", "cr", "rt", "kind"], deals.get(sym, [])),
               "own": _cols(["q", *OWNERSHIP], own.get(isin, []) if isin else []),
               "insider": _cols(["d", "person", "cat", "txn", "qty", "cr", "mode"], insider.get(sym, [])),
               "px": _cols(["d", "close"], weekly.get(sym, []))}
        (out / "stocks" / f"{sym_file(sym)}.json").write_text(json.dumps(doc, separators=(",", ":")))
    index = sorted(([s, co.get(s) or ident.get(s, {}).get("co") or "", sym_file(s), len(deals.get(s, []))]
                    for s in syms), key=lambda x: -x[3])
    (out / "stocks.json").write_text(json.dumps(index, separators=(",", ":")))
    return len(syms)


def export_participants(out: Path, rows: list, env: str | None = None) -> int:
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
    index = []
    for who, ds in by.items():
        m = master.get(who, {})
        t = m.get("type") or "UNKNOWN"
        years: dict[str, list[int]] = defaultdict(lambda: [0, 0])
        for x in ds:
            years[x[0][:4]][0 if x[3] == "BUY" else 1] += 1
        stocks: dict[str, int] = defaultdict(int)
        for x in ds:
            stocks[x[1]] += 1
        stock_days = {(x[0], x[1]) for x in ds}
        rt_days = {(x[0], x[1]) for x in ds if x[7]}
        doc = {"name": who, "slug": slug(who), "type": t, "label": TYPE_LABEL.get(t, t),
               "how": m.get("how"), "confidence": m.get("conf"), "review": m.get("status"),
               "notes": m.get("notes"), "house": m.get("house"), "spellings": spellings.get(who, []),
               "stats": {"deals": len(ds), "buys": sum(x[3] == "BUY" for x in ds),
                         "sells": sum(x[3] != "BUY" for x in ds),
                         "stock_days": len(stock_days),
                         "roundtrip_share": round(len(rt_days) / len(stock_days), 4) if stock_days else 0.0,
                         "first": ds[0][0], "last": ds[-1][0],
                         "years": sorted([y, b, s] for y, (b, s) in years.items()),
                         "top_stocks": sorted(stocks.items(), key=lambda kv: -kv[1])[:15]},
               "deals": _cols(["d", "sym", "sid", "side", "qty", "px", "cr", "rt", "kind", "client"], ds)}
        (out / "participants" / f"{slug(who)}.json").write_text(json.dumps(doc, separators=(",", ":")))
        index.append([who, TYPE_LABEL.get(t, t), slug(who), len(ds), t])
    index.sort(key=lambda x: -x[3])
    (out / "participants.json").write_text(json.dumps(index, separators=(",", ":")))
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
