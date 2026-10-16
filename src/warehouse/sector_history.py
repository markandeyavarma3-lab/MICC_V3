"""sector_history.py — point-in-time industries, extracted from the monthly
mutual-fund portfolios. Plan 1 step 3.5.

WHY (2026-10-16). `sector_history` has existed empty since the schema landed;
benchmarks.yml's CHAR_MATCHED specifies size x momentum x volatility x
INDUSTRY, and charmatch.py drops industry because nothing supplied it. NSE's
index lists give a third of the universe, and only today's labels.

THE SOURCE. Every scheme's month-end portfolio (src/ingest/mf_portfolios.py)
labels each equity holding with its industry, in AMFI's classification, and
the files go back to 2015-12. So each stock any covered scheme held has a
dated industry label every month — written by the fund house that month, not
reconstructed today.

THE RULE.
  label        per (ISIN, month): the label the most rows carry that month,
               compared case- and space-insensitively; its commonest spelling
  known from   the 10th of the following month (SEBI's publication deadline),
               not the month-end: a label is usable only once it was public
  intervals    consecutive months with the same label merge; a month a stock
               was not held changes nothing; valid_to is the day before the
               next different label is known
  confidence   HIGH when >= 75% of that month's rows agree and >= 3 rows,
               MEDIUM when >= 50%, else LOW

AMFI revised its industry names in 2023 ('Software' became 'IT - Software'),
so a label change at that date is a renaming, not the company changing
business. Both are kept as filed; `classification` says which source.

WHAT THIS DOES NOT DO: wire industry into CHAR_MATCHED. That changes how the
benchmark every quoted figure uses is built, and is the owner's decision.

    RESEARCH_ENV=prod .venv/bin/python -m src.warehouse.sector_history
"""

from __future__ import annotations

import sys
from collections import Counter
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.common.paths import research_db  # noqa: E402

CLASSIFICATION = "AMFI_MF_PORTFOLIO"
PUBLICATION_DAY = 10


def known_from(month_end: date) -> date:
    """The 10th of the month after `month_end`."""
    y, m = (month_end.year + 1, 1) if month_end.month == 12 else (month_end.year, month_end.month + 1)
    return date(y, m, PUBLICATION_DAY)


def norm(label: str) -> str:
    return " ".join(label.split()).casefold()


def monthly_labels(rows: list[tuple]) -> dict[tuple, tuple[str, str]]:
    """(key, month_end, industry) rows -> {(key, month_end): (label, confidence)}.
    The key is the security_id in production (an ISIN in some tests). Pure."""
    by: dict[tuple[str, date], Counter] = {}
    spell: dict[tuple[str, date, str], Counter] = {}
    for isin, m, ind in rows:
        if not ind or not ind.strip():
            continue
        k = (isin, m)
        n = norm(ind)
        by.setdefault(k, Counter())[n] += 1
        spell.setdefault((isin, m, n), Counter())[" ".join(ind.split())] += 1
    out = {}
    for k, c in by.items():
        (top, cnt), total = c.most_common(1)[0], sum(c.values())
        share = cnt / total
        conf = "HIGH" if share >= 0.75 and total >= 3 else "MEDIUM" if share >= 0.5 else "LOW"
        out[k] = (spell[(k[0], k[1], top)].most_common(1)[0][0], conf)
    return out


def intervals(labels: dict[tuple[str, date], tuple[str, str]]) -> list[tuple[str, str, date, date | None, str]]:
    """Merge each ISIN's months into (isin, label, valid_from, valid_to, confidence)
    intervals. Confidence of an interval is its weakest month. Pure."""
    per: dict[str, list] = {}
    for (isin, m), (lab, conf) in labels.items():
        per.setdefault(isin, []).append((m, lab, conf))
    rank = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
    out = []
    for isin, ms in per.items():
        ms.sort()
        cur: list | None = None            # [valid_from, label, weakest confidence]
        for m, lab, conf in ms:
            if cur is not None and norm(cur[1]) == norm(lab):
                if rank[conf] < rank[cur[2]]:
                    cur[2] = conf
                continue
            if cur is not None:
                out.append((isin, cur[1], cur[0], known_from(m) - timedelta(days=1), cur[2]))
            cur = [known_from(m), lab, conf]
        if cur is not None:
            out.append((isin, cur[1], cur[0], None, cur[2]))
    return out


@dataclass
class Result:
    securities: int
    intervals: int
    unmatched_isins: int
    first: date | None
    last: date | None

    def render(self) -> str:
        return (f"SECTOR HISTORY: {self.intervals:,} intervals for {self.securities:,} securities "
                f"({self.first} .. {self.last}); {self.unmatched_isins} ISINs not in security_master")


def build(env: str | None = None) -> Result:
    """Labels are voted per SECURITY, not per ISIN: a company whose ISIN
    changed (HDFC Bank, 2019 split: INE040A01026 -> INE040A01034) is one
    company, and keying on the ISIN gave it two overlapping open intervals
    (found 2026-10-16)."""
    import duckdb

    from src.ingest import mf_portfolios as mfi
    con = duckdb.connect(str(research_db(env)))
    try:
        sid = dict(con.execute("SELECT isin, security_id FROM security_master WHERE isin IS NOT NULL").fetchall())
        rows = con.execute(f"""
            SELECT isin, last_day(CAST(as_of AS DATE)), industry FROM read_parquet('{mfi.OUT}')
            WHERE as_of IS NOT NULL AND isin LIKE 'INE%' AND substr(isin, 8, 2) = '01'
              AND industry IS NOT NULL AND trim(industry) <> ''""").fetchall()
        missing = len({i for i, _, _ in rows if i not in sid})
        ivs = intervals(monthly_labels([(sid[i], m, ind) for i, m, ind in rows if i in sid]))
        keep = [(s_, lab, lab, CLASSIFICATION, vf, vt, conf) for s_, lab, vf, vt, conf in ivs]
        con.execute("BEGIN")
        con.execute("DELETE FROM sector_history WHERE classification = ?", [CLASSIFICATION])
        con.executemany("INSERT INTO sector_history (security_id, sector, industry, classification, valid_from,"
                        " valid_to, confidence) VALUES (?,?,?,?,?,?,?)", keep)
        con.execute("COMMIT")
    finally:
        con.close()
    return Result(len({k[0] for k in keep}), len(keep), missing,
                  min((k[4] for k in keep), default=None), max((k[4] for k in keep), default=None))


SECTOR_MAP = Path(__file__).resolve().parents[2] / "configs" / "industry_sectors.yml"


def sector_map() -> dict[str, str | None]:
    """AMFI label (lower-cased, spaces collapsed) -> NSE sector, frozen in
    configs/industry_sectors.yml."""
    import yaml
    return {norm(k): v for k, v in yaml.safe_load(SECTOR_MAP.read_text())["labels"].items()}


def build_sector_panel(env: str | None = None) -> int:
    """warehouse/sector_panel: (rebalance_date, symbol, sector, size_t) for every
    char_panel row whose company has a sector at that date — the cells of
    CHAR_MATCHED_IND (src/research/charmatch.py). Kept OUT of char_panel so
    CHAR_MATCHED, and every figure quoted on it, cannot change.

    size_t: size tercile by the panel's own adv20, among ALL names that month
    (not only those with a sector), so a cell compares like-sized companies.
    Identity: the char_panel symbol resolves to a security by the identity
    layer's rule — the symbol_history window covering the date, else the
    nearest one, ties to the lowest id (src/identity/master.py RESOLVE_SQL)."""
    import duckdb

    from src.common.partitioned import replace_partitioned
    from src.common.paths import warehouse_dir
    cp = str(warehouse_dir(env) / "char_panel" / "**" / "*.parquet")
    out = warehouse_dir(env) / "sector_panel"
    con = duckdb.connect(str(research_db(env)), read_only=True)
    try:
        con.execute("CREATE TEMP TABLE smap (lab VARCHAR, sector VARCHAR)")
        con.executemany("INSERT INTO smap VALUES (?, ?)", [(k, v) for k, v in sector_map().items() if v])
        sql = f"""
            WITH p AS (
                SELECT CAST(rebalance_date AS DATE) AS d, symbol, adv20,
                       NTILE(3) OVER (PARTITION BY rebalance_date ORDER BY adv20) AS size_t
                FROM read_parquet('{cp}', hive_partitioning=true)),
            ident AS (
                SELECT p.*, h.security_id FROM p JOIN symbol_history h ON UPPER(h.symbol) = UPPER(p.symbol)
                QUALIFY ROW_NUMBER() OVER (PARTITION BY p.d, p.symbol ORDER BY
                    CASE WHEN p.d >= h.valid_from AND (h.valid_to IS NULL OR p.d <= h.valid_to) THEN 0
                         WHEN p.d < h.valid_from THEN date_diff('day', p.d, h.valid_from)
                         ELSE date_diff('day', h.valid_to, p.d) END, h.security_id) = 1)
            SELECT i.d AS rebalance_date, i.symbol, m.sector, i.size_t
            FROM ident i
            JOIN sector_history s ON s.security_id = i.security_id
             AND i.d BETWEEN s.valid_from AND coalesce(s.valid_to, DATE '2100-01-01')
            JOIN smap m ON m.lab = lower(regexp_replace(trim(s.industry), '\\s+', ' ', 'g'))"""
        replace_partitioned(con, sql, out, "rebalance_date")
        n = con.execute(f"SELECT count(*) FROM read_parquet('{out}/**/*.parquet')").fetchone()[0]
    finally:
        con.close()
    return n


def main() -> int:
    print(" ", build().render())
    print(f"  SECTOR PANEL: {build_sector_panel():,} (month-end, stock) rows with an NSE sector")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
