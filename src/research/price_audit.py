"""price_audit.py — our price spine against an independent vendor (Kite Connect).

WHY (2026-10-09). Every verdict this project has rests on `price_spine_adj`:
NSE's own files plus this project's split/bonus adjustment. It has never been
checked against a second source. Kite's daily candles, held for one month
(src/archive/kite.py), are that source for every company still trading.

WHAT IT MEASURES, per company, over the days both sides hold:
  agreement   share of days whose close agrees within TOL with our RAW close,
              and with our ADJUSTED close. Which one Kite matches says which
              convention it follows; the audit does not assume one.
  steps       dates where log(ours_adj / kite) jumps by more than STEP and
              stays there for PERSIST sessions: the signature of a corporate
              action one side adjusted for and the other did not. A step is a
              question about that date, not yet an error in either source.

WHAT IT CANNOT SEE. Delisted companies (Kite has none) and the history of a
renamed symbol before its rename (Kite files the whole history under today's
symbol; the spine under the symbol of the day). Both are counted, not hidden.

Prints and writes counts, dates and step sizes only — never a price series:
Kite's data is for personal use and the repository is public.

    RESEARCH_ENV=prod .venv/bin/python -m src.research.price_audit
"""

from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import duckdb  # noqa: E402

from src.archive import kite  # noqa: E402
from src.common.paths import COLLECTED, DOCS, warehouse_dir  # noqa: E402

TOL = 0.005            # 0.5%: a close that differs by less is the same close
STEP = 0.02            # a 2% jump in the log ratio ...
PERSIST = 5            # ... that holds for 5 sessions is a step, not a bad print
OUT = COLLECTED / "kite" / "kite_daily_eq.parquet"
REPORT = DOCS / "reports" / "PRICE_AUDIT.md"


def latest_files(manifest: Path | None = None) -> dict[int, dict]:
    """The newest STORED pull per instrument, EQ series only."""
    manifest = manifest or kite.MANIFEST
    best: dict[int, dict] = {}
    if not manifest.exists():
        return best
    for ln in manifest.read_text().splitlines():
        r = json.loads(ln)
        if r.get("kind") != "candles" or r.get("status") != "STORED" or r.get("series") != "EQ":
            continue
        t = int(r["instrument_token"])
        if t not in best or r["end"] > best[t]["end"]:
            best[t] = r
    return best


def build_parquet(files: dict[int, dict], out: Path = OUT) -> int:
    rows = []
    for r in files.values():
        d = json.loads(gzip.decompress(Path(r["path"]).read_bytes()))
        for ts, _o, _h, _l, c, _v in d["candles"]:
            rows.append((r["symbol"], ts[:10], float(c)))
    out.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    try:
        con.execute("CREATE TABLE k (symbol VARCHAR, date VARCHAR, close DOUBLE)")
        con.executemany("INSERT INTO k VALUES (?, ?, ?)", rows)
        con.execute(f"COPY (SELECT * FROM k ORDER BY symbol, date) TO '{out}' (FORMAT PARQUET)")
    finally:
        con.close()
    return len(rows)


def audit_sql(kite_parquet: str, raw_glob: str, adj_glob: str) -> str:
    return f"""
    WITH k AS (SELECT symbol, date, close AS kc FROM read_parquet('{kite_parquet}') WHERE close > 0),
    r AS (SELECT symbol, date, close AS rc FROM read_parquet('{raw_glob}', hive_partitioning=true)),
    a AS (SELECT symbol, date, close AS ac FROM read_parquet('{adj_glob}', hive_partitioning=true)),
    j AS (
        SELECT k.symbol, k.date, kc, rc, ac
        FROM k JOIN r USING (symbol, date) JOIN a USING (symbol, date)
        WHERE rc > 0 AND ac > 0),
    lr AS (
        SELECT *, ln(ac / kc) AS l,
               ln(ac / kc) - lag(ln(ac / kc)) OVER (PARTITION BY symbol ORDER BY date) AS jump,
               lead(ln(ac / kc), {PERSIST}) OVER (PARTITION BY symbol ORDER BY date)
                 - lag(ln(ac / kc)) OVER (PARTITION BY symbol ORDER BY date) AS held
        FROM j)
    SELECT symbol, date, kc, rc, ac, jump, held,
           abs(rc / kc - 1) < {TOL} AS raw_ok,
           abs(ac / kc - 1) < {TOL} AS adj_ok,
           abs(jump) > {STEP} AND abs(held) > {STEP} AND sign(jump) = sign(held) AS step
    FROM lr"""


def run(kite_parquet: Path = OUT, env: str | None = None) -> dict:
    raw = str(warehouse_dir(env) / "price_spine" / "**" / "*.parquet")
    adj = str(warehouse_dir(env) / "price_spine_adj" / "**" / "*.parquet")
    con = duckdb.connect()
    try:
        con.execute(f"CREATE TEMP TABLE t AS {audit_sql(str(kite_parquet), raw, adj)}")
        per = con.execute("""
            SELECT symbol, count(*) n, avg(raw_ok::INT) raw_share, avg(adj_ok::INT) adj_share,
                   sum(step::INT) steps, min(date) first_day, max(date) last_day
            FROM t GROUP BY symbol ORDER BY symbol""").fetchall()
        steps = con.execute("""
            SELECT symbol, date, round(100 * (exp(jump) - 1), 1) pct
            FROM t WHERE step ORDER BY abs(jump) DESC""").fetchall()
        kite_syms = con.execute(f"SELECT count(DISTINCT symbol) FROM read_parquet('{kite_parquet}')").fetchone()[0]
    finally:
        con.close()
    return {"per": per, "steps": steps, "kite_symbols": kite_syms}


def classify(raw_share: float, adj_share: float, cut: float = 0.99) -> str:
    if raw_share >= cut and adj_share >= cut:
        return "both"          # no corporate action in the overlap
    if adj_share >= cut:
        return "adjusted"
    if raw_share >= cut:
        return "raw"
    return "neither"


def render(res: dict) -> str:
    per, steps = res["per"], res["steps"]
    kinds: dict[str, int] = {}
    for _s, _n, rs, as_, *_ in per:
        k = classify(rs, as_)
        kinds[k] = kinds.get(k, 0) + 1
    days = sum(p[1] for p in per)
    lines = [
        "# PRICE_AUDIT.md — price_spine_adj against Kite Connect daily candles",
        "",
        "**Generated by `python -m src.research.price_audit`. Counts, dates and step sizes only; no "
        "price series (Kite data is personal-use; this repository is public).**",
        "",
        f"- Kite EQ symbols held: {res['kite_symbols']:,}; matched to the spine on (symbol, date): "
        f"{len(per):,} companies, {days:,} company-days.",
        f"- Unmatched Kite symbols: {res['kite_symbols'] - len(per):,} (renamed since their history "
        "began, new listings, or symbols the spine never carried).",
        f"- Agreement within {TOL:.1%} on at least 99% of days — with BOTH raw and adjusted (no action "
        f"in the overlap): {kinds.get('both', 0):,}; with ADJUSTED only: {kinds.get('adjusted', 0):,}; "
        f"with RAW only: {kinds.get('raw', 0):,}; with NEITHER: {kinds.get('neither', 0):,}.",
        f"- Steps (log ratio jumps > {STEP:.0%}, held {PERSIST} sessions): {len(steps):,} across "
        f"{len({s[0] for s in steps}):,} companies.",
        "",
        "## Largest steps (each is a date to check, not yet an error)",
        "",
        "| symbol | date | step |",
        "|---|---|---:|",
        *[f"| {s} | {d} | {p:+.1f}% |" for s, d, p in steps[:40]],
        "",
        "## Companies agreeing with neither on 99% of days",
        "",
        "| symbol | days | raw agree | adjusted agree | steps | first | last |",
        "|---|---:|---:|---:|---:|---|---|",
        *[f"| {s} | {n:,} | {rs:.1%} | {as_:.1%} | {st} | {f} | {la} |"
          for s, n, rs, as_, st, f, la in per if classify(rs, as_) == "neither"][:60],
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    files = latest_files()
    if not files:
        print("  no Kite candles held; run src.archive.kite first")
        return 1
    n = build_parquet(files)
    print(f"  {len(files):,} EQ instruments, {n:,} candles -> {OUT}")
    text = render(run())
    REPORT.write_text(text)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
