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


def monthly_labels(rows: list[tuple[str, date, str]]) -> dict[tuple[str, date], tuple[str, str]]:
    """(isin, month_end, industry) rows -> {(isin, month_end): (label, confidence)}. Pure."""
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
    import duckdb

    from src.ingest import mf_portfolios as mfi
    src = duckdb.connect()
    try:
        rows = src.execute(f"""
            SELECT isin, last_day(CAST(as_of AS DATE)), industry FROM read_parquet('{mfi.OUT}')
            WHERE as_of IS NOT NULL AND isin LIKE 'INE%' AND substr(isin, 8, 2) = '01'
              AND industry IS NOT NULL AND trim(industry) <> ''""").fetchall()
    finally:
        src.close()
    ivs = intervals(monthly_labels(rows))
    con = duckdb.connect(str(research_db(env)))
    try:
        sid = dict(con.execute("SELECT isin, security_id FROM security_master WHERE isin IS NOT NULL").fetchall())
        keep = [(sid[i], lab, lab, CLASSIFICATION, vf, vt, conf) for i, lab, vf, vt, conf in ivs if i in sid]
        missing = len({i for i, *_ in ivs if i not in sid})
        con.execute("BEGIN")
        con.execute("DELETE FROM sector_history WHERE classification = ?", [CLASSIFICATION])
        con.executemany("INSERT INTO sector_history (security_id, sector, industry, classification, valid_from,"
                        " valid_to, confidence) VALUES (?,?,?,?,?,?,?)", keep)
        con.execute("COMMIT")
    finally:
        con.close()
    return Result(len({k[0] for k in keep}), len(keep), missing,
                  min((k[4] for k in keep), default=None), max((k[4] for k in keep), default=None))


def main() -> int:
    print(" ", build().render())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
