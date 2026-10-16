"""event_power.py — which NEW event series could a study power? Dispersion only.

WHY (2026-10-16). Every registered question has a verdict (0086). Since
2026-10-10 the project collects event series it never had: who appears and
disappears among the named >1% holders in every shareholding filing, every
company announcement by NSE's own category, and every quarterly results filing.
Before anyone designs a study on any of them, this asks the cheap question
first: at the project's bound (0.5% a month, 0028) could a study on that
population tell an effect from noise at all?

POWER ONLY, NO EFFECT (0035). Exactly insider_power.py's method — the shared
`measure._returns_sql` forward return entered at the next session's open,
market-relative against the same-session cross-sectional mean, collapsed to
monthly cohorts, MDE serial-corrected with the lag covering the label overlap
(0033). Only WHEN an event happened is read: no holding size, no direction of
a change, no announcement text. tests/test_event_power.py pins that the SQL
names none of the value columns.

RETURNS STOP AT measure.REPRODUCIBILITY_HORIZON (2026-08-31), as every other
power figure does, so these are comparable with the published ones.

    RESEARCH_ENV=prod .venv/bin/python -m src.research.event_power
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import duckdb

from src.common.paths import COLLECTED, DOCS, warehouse_dir
from src.research import measure, power

REPORT = DOCS / "reports" / "EVENT_POWER_PRELIMINARY.md"
NAMED = COLLECTED / "shp" / "shp_named_holders.parquet"
HOLDINGS = COLLECTED / "shp" / "shp_holdings.parquet"
RESULTS = COLLECTED / "results" / "results_quarterly.parquet"
#: Holder groups as src/ingest/shp_holders.py assigns them.
GROUPS = ("FPI", "MF", "INSURANCE", "AIF", "CORPORATE", "INDIVIDUAL")
#: NSE announcement categories with a plausible economic story and enough
#: rows; boilerplate (newspaper copies, share-certificate losses, trading
#: windows, depository certificates) is left out by choice, stated here.
ANNOUNCE_CATEGORIES = ("Acquisition", "Credit Rating", "Resignation", "Change in Management",
                       "Allotment of Securities", "Disclosure under SEBI Takeover Regulations",
                       "Spurt in Volume", "Press Release", "Investor Presentation", "Change in Director(s)")
MIN_EVENTS = 30


@dataclass(frozen=True, slots=True)
class Row:
    population: str
    horizon: str
    months: float
    n_events: int
    n_cohorts: int
    first: str
    cohort_sd: float
    mde: float

    @property
    def bound(self) -> float:
        return measure.BOUND_PER_MONTH * self.months

    @property
    def ratio(self) -> float:
        return self.mde / self.bound


def _filing_dates() -> str:
    """(isin, quarter_end) -> the date the filing became public."""
    return f"""SELECT isin, quarter_end, min(CAST(broadcast_date AS DATE)) AS pub
               FROM read_parquet('{HOLDINGS}') WHERE broadcast_date <> '' GROUP BY 1, 2"""


def holder_events(group: str, kind: str) -> str:
    """A named holder of `group` that is NEW in a filing (kind 'enter') or GONE
    from it (kind 'exit') relative to the same company's previous filing.
    Dated at the later filing's publication. Only names and dates are read."""
    if kind == "enter":
        here, there = "a", "b"
    else:
        here, there = "b", "a"
    return f"""
    WITH h AS (
        SELECT DISTINCT isin, quarter_end, lower(trim(name)) AS nm FROM read_parquet('{NAMED}')
        WHERE grp = '{group}' AND NOT is_label AND tbl = 'PUBLIC'),
    q AS (SELECT DISTINCT isin, quarter_end FROM read_parquet('{NAMED}')),
    seq AS (SELECT isin, quarter_end AS cur,
                   lag(quarter_end) OVER (PARTITION BY isin ORDER BY quarter_end) AS prev FROM q),
    ev AS (
        SELECT s.isin, s.cur FROM seq s
        JOIN h {here} ON {here}.isin = s.isin AND {here}.quarter_end = {'s.cur' if kind == 'enter' else 's.prev'}
        WHERE s.prev IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM h {there} WHERE {there}.isin = s.isin
              AND {there}.quarter_end = {'s.prev' if kind == 'enter' else 's.cur'} AND {there}.nm = {here}.nm)
        GROUP BY 1, 2),
    f AS ({_filing_dates()})
    SELECT DISTINCT CAST(f.pub AS VARCHAR) AS tdate, m.security_id
    FROM ev JOIN f ON f.isin = ev.isin AND f.quarter_end = ev.cur
    JOIN security_master m ON m.isin = ev.isin"""


def announce_events(category: str, archive_rows: list[dict]) -> list[tuple[str, str]]:
    """(date, isin) for one NSE announcement category; one per company-day."""
    return sorted({((r.get("sort_date") or "")[:10], r.get("sm_isin"))
                   for r in archive_rows
                   if (r.get("desc") or "").strip() == category and r.get("sm_isin") and r.get("sort_date")})


def results_events() -> str:
    return f"""
    WITH f AS (SELECT DISTINCT UPPER(TRIM(symbol)) AS symbol, CAST(filed AS DATE) AS d
               FROM read_parquet('{RESULTS}') WHERE filed IS NOT NULL AND filed <> '')
    SELECT CAST(f.d AS VARCHAR) AS tdate, h.security_id FROM f JOIN symbol_history h ON h.symbol = f.symbol
    QUALIFY ROW_NUMBER() OVER (PARTITION BY f.symbol, f.d ORDER BY
        CASE WHEN f.d >= h.valid_from AND (h.valid_to IS NULL OR f.d <= h.valid_to) THEN 0 ELSE 1 END,
        h.security_id) = 1"""


def populations(con) -> list[tuple[str, str]]:
    """(label, SQL yielding tdate VARCHAR, security_id)."""
    from src.site.export import _archive_rows
    out = [(f"holder enters: {g}", holder_events(g, "enter")) for g in GROUPS]
    out += [(f"holder exits: {g}", holder_events(g, "exit")) for g in GROUPS]
    rows = _archive_rows("ANNOUNCE")
    for i, cat in enumerate(ANNOUNCE_CATEGORIES):
        ev = announce_events(cat, rows)
        con.execute(f"CREATE OR REPLACE TEMP TABLE ann_{i} (tdate VARCHAR, isin VARCHAR)")
        con.executemany(f"INSERT INTO ann_{i} VALUES (?, ?)", ev)
        out.append((f"announcement: {cat}", f"SELECT DISTINCT a.tdate, m.security_id FROM ann_{i} a "
                                             f"JOIN security_master m ON m.isin = a.isin"))
    out.append(("quarterly results filed", results_events()))
    return out


def grid(env: str | None = None) -> list[Row]:
    spine = str(warehouse_dir(env) / "price_spine_adj" / "**" / "*.parquet")
    con = duckdb.connect(str(measure.research_db(env)), read_only=True)
    con.execute("SET memory_limit='8GB'; SET preserve_insertion_order=false; SET threads=4;")
    out: list[Row] = []
    try:
        pops = populations(con)
        for hlabel, sessions, months in measure.HORIZONS:
            if months > 3:                    # the new series are short; 12 months has too few cohorts
                continue
            con.execute(f"CREATE OR REPLACE TEMP TABLE rets AS "
                        f"{measure._returns_sql(spine, sessions, measure.REPRODUCIBILITY_HORIZON)}")
            con.execute("CREATE OR REPLACE TEMP TABLE mkt AS SELECT date, avg(ret) m FROM rets GROUP BY 1")
            for label, ev_sql in pops:
                df = con.execute(
                    f"WITH ev AS ({ev_sql}) SELECT ev.tdate, r.ret - m.m AS ab FROM ev "
                    "JOIN rets r ON r.security_id = ev.security_id AND CAST(r.date AS VARCHAR) = ev.tdate "
                    "JOIN mkt m ON m.date = r.date").df().dropna(subset=["ab"])
                if len(df) < MIN_EVENTS:
                    continue
                cohorts = power.cohort_collapse(df["tdate"], df["ab"], freq="M")
                if len(cohorts) < 6:
                    continue
                lp = max(1, round(months))
                out.append(Row(label, hlabel, months, len(df), len(cohorts), str(df["tdate"].min())[:7],
                               power.cohort_sd(cohorts), power.mde_serial_corrected(cohorts, label_periods=lp)))
    finally:
        con.close()
    return out


def render(rows: list[Row]) -> str:
    out = ["# New event series — power, PRELIMINARY", "",
           f"Generated by `src/research/event_power.py`, {date.today()}. Dispersion only (0035): only WHEN each "
           "event happened was read, never its size, direction or text. Nothing frozen, hashed or charged. "
           f"Returns end at {measure.REPRODUCIBILITY_HORIZON}, as every published power figure does.", "",
           "Sorted by how close each population is to its bound (MDE / bound; 1.00x or below is POWERED).", "",
           "| population | horizon | events | monthly cohorts | from | cohort SD | MDE | bound | MDE / bound |",
           "|---|---|---:|---:|---|---:|---:|---:|---:|"]
    for r in sorted(rows, key=lambda r: r.ratio):
        flag = "**POWERED**" if r.ratio <= 1 else f"{r.ratio:.2f}x"
        out.append(f"| {r.population} | {r.horizon} | {r.n_events:,} | {r.n_cohorts} | {r.first} | "
                   f"{r.cohort_sd:.2%} | {r.mde:.2%} | {r.bound:.2%} | {flag} |")
    out += ["", "## Read this with", "",
            "- **POWERED is not a finding.** It means a registered study could see 0.5% a month if it were "
            "there; it says nothing about whether it is.",
            "- **A powered population on a short series is still short.** Announcements start in 2023 and "
            "results filings in 2024 in this archive: few monthly cohorts, so the serial correction is "
            "estimated on little data and one bad year moves it.",
            "- **Holder entries and exits are filing-to-filing changes in who is NAMED above 1%.** Crossing "
            "the 1% line is not the same as buying or selling, and a filing published late is dated late.",
            "- **Next step for any powered row:** a written design and the owner's registration, before any "
            "mean is computed."]
    return "\n".join(out) + "\n"


def main() -> int:
    rows = grid()
    REPORT.write_text(render(rows))
    for r in sorted(rows, key=lambda r: r.ratio)[:15]:
        print(f"  {r.population:<46} {r.horizon:>10} n={r.n_events:>7,} cohorts={r.n_cohorts:>3} "
              f"MDE {r.mde:6.2%} vs {r.bound:5.2%}  {'POWERED' if r.ratio <= 1 else f'{r.ratio:.2f}x'}")
    print(f"  -> {REPORT.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
