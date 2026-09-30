"""promoters.py — who was a promoter of which company, as the public knew it.
Plan 1 §6.6, step 3.11.

WHAT THIS IS FOR. A bulk or block deal by a company's own promoter is not
institutional activity: it is the owner selling down, pledging out, or moving
shares between family members and holding companies. Plan 1 §7.1 carries two
flags for it — `promoter_related_flag` and `internal_transfer_flag` — and both
were FALSE on every row because no promoter list existed. Measured before this
was written (2026-09-30, name match at any date, so an upper bound): 1,435 of
30,713 otherwise-eligible SELLS and 668 of 12,850 block deals are a promoter
of that same company trading.

THE SOURCE. Table II of every shareholding-pattern filing names each
promoter-group holder. `src/ingest/shp.py` writes them to
`shp_promoters.parquet`, one row per (filing, holder), with the filing's
broadcast date.

POINT IN TIME, AND ON THE BROADCAST DATE — NOT THE QUARTER-END. Plan 1 §6.6
fixes `valid_from` as "the quarter's filing date", and it is the right choice
for a flag that removes events from a study: a rule that excludes a deal
because of a filing published weeks LATER is a look-ahead, however true the
filing is. So an entity is a promoter of a security from the broadcast date
of the first filing that names it, until the broadcast date of the first
later filing that does not. The cost is a lag — a promoter who first appears
mid-quarter is not flagged until the filing says so — and it is paid
deliberately.

A FILING THAT NAMES NOBODY SAYS NOTHING. A filing whose promoter total is
above zero but whose Table II parsed to no names is a parse or disclosure gap,
not the promoters leaving; letting it close every open run would silently
un-flag a company for a quarter. Such a filing is skipped, and counted. So is
one with no broadcast date — it cannot be placed in time at all.

NAME MATCHING IS EXACT, AFTER `entity_names.normalize`. The same conservative
rule the counterparty counts use: case, punctuation and decorative corporate
suffixes are ignored; nothing fuzzy. A promoter written `ASHISH R PATEL` in a
deal and `Ashish Rajanibhai Patel` in the filing is missed, which UNDER-flags
— the recoverable direction. Flagging a stranger as a promoter is not.

COVERAGE IS PARTIAL AND SAYS SO. SHP filings reach bulk coverage only from
2021, and the sweep (decision 0074) is still filling in companies. A deal on a
security with no promoter list in force on its trade date is flagged FALSE for
want of evidence, not because it was checked; `src/mart/clean.py` reports how
many deals had a list to check against.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

import duckdb

from src.common.paths import governance_db, research_db
from src.governance import provenance as prov
from src.ingest.shp import OUT as HOLDINGS, PROMOTERS_OUT
from src.research.entity_names import normalize

PRODUCED_BY = "src.identity.promoters:build"

#: Below this promoter percentage a filing naming nobody is consistent with
#: having no promoters at all (professionally managed companies file 0).
NO_PROMOTER_PCT = 0.01


@dataclass(frozen=True, slots=True)
class Filing:
    quarter_end: str
    broadcast_date: str
    #: normalized name -> (name as filed, percentage held)
    names: dict[str, tuple[str, float | None]]
    promoter_pct: float | None


@dataclass(frozen=True, slots=True)
class Run:
    normalized_name: str
    entity_name: str
    valid_from: str
    valid_to: str | None
    holding_pct: float | None


@dataclass
class Report:
    filings: int = 0
    skipped_no_date: int = 0
    skipped_no_names: int = 0
    securities: int = 0
    isins_unmatched: int = 0
    entities: int = 0
    runs: int = 0
    open_runs: int = 0
    degenerate: int = 0
    unmatched_examples: list[str] = field(default_factory=list)

    def render(self) -> str:
        return "\n".join([
            f"  filings read              {self.filings:>8,}",
            f"    skipped, no broadcast date  {self.skipped_no_date:>6,}  (cannot be placed in time)",
            f"    skipped, names nobody       {self.skipped_no_names:>6,}  (promoter total > 0, Table II empty)",
            f"  securities with a list    {self.securities:>8,}",
            f"  ISINs not in security_master {self.isins_unmatched:>5,}"
            + (f"  e.g. {', '.join(self.unmatched_examples)}" if self.unmatched_examples else ""),
            f"  promoter entities         {self.entities:>8,}",
            f"  validity runs             {self.runs:>8,}  ({self.open_runs:,} still open)",
            f"  omissions ignored, published on or before the listing {self.degenerate:,}",
        ])


def runs(filings: list[Filing]) -> tuple[list[Run], int, int, int]:
    """Validity runs for ONE security's filings.

    Returns (runs, skipped_no_date, skipped_no_names, degenerate). Filings are
    taken in quarter order; a run opens at the broadcast date of the first
    filing naming the entity and closes at the broadcast date of the first
    later filing that does not.
    """
    open_: dict[str, tuple[str, str, float | None]] = {}
    out: list[Run] = []
    no_date = no_names = degenerate = 0
    for f in sorted(filings, key=lambda f: (f.quarter_end, f.broadcast_date)):
        if not f.broadcast_date:
            no_date += 1
            continue
        if not f.names and not (f.promoter_pct is not None and f.promoter_pct < NO_PROMOTER_PCT):
            no_names += 1
            continue
        for norm in [n for n in open_ if n not in f.names]:
            raw, vf, pct = open_[norm]
            # Filings are walked in quarter order, but a filing can be
            # PUBLISHED on or before the one that opened this run. Then the
            # omission is older news than the listing, and as of the run's
            # start the latest published word is "promoter" — so the run stays
            # open. Dropping it instead (the first build) lost 1,142 runs.
            if f.broadcast_date > vf:
                del open_[norm]
                out.append(Run(norm, raw, vf, f.broadcast_date, pct))
            else:
                degenerate += 1
        for norm, (raw, pct) in f.names.items():
            if norm not in open_:
                open_[norm] = (raw, f.broadcast_date, pct)
    out.extend(Run(norm, raw, vf, None, pct) for norm, (raw, vf, pct) in open_.items())
    return _merge(out), no_date, no_names, degenerate


def _merge(rs: list[Run]) -> list[Run]:
    """Union overlapping runs of one entity.

    Filings are walked in QUARTER order, but broadcast dates need not follow
    it — a late filing for a later quarter can be published before an earlier
    one. An entity can then reopen on a date inside, or equal to, a run it
    already had (MOKSHITH REDDY CHENNA REDDY, 2024-08-27, broke the primary
    key on the first real build). It was a promoter throughout both, so the
    runs are one interval, not two rows.
    """
    by: dict[str, list[Run]] = {}
    for r in rs:
        by.setdefault(r.normalized_name, []).append(r)
    out: list[Run] = []
    for group in by.values():
        group.sort(key=lambda r: r.valid_from)
        cur = group[0]
        for r in group[1:]:
            if cur.valid_to is None or r.valid_from <= cur.valid_to:
                end = None if cur.valid_to is None or r.valid_to is None else max(cur.valid_to, r.valid_to)
                cur = Run(cur.normalized_name, cur.entity_name, cur.valid_from, end, cur.holding_pct)
            else:
                out.append(cur)
                cur = r
        out.append(cur)
    return out


def _filings(con: duckdb.DuckDBPyConnection) -> dict[str, list[Filing]]:
    """isin -> its filings. Several files for one (isin, quarter) — an original
    and its revision — are one filing: names are unioned and the EARLIEST
    broadcast date kept, since the master holds one date per quarter."""
    heads = con.execute(f"""
        SELECT isin, quarter_end,
               MIN(NULLIF(broadcast_date, '')) AS bd,
               MAX(CASE WHEN category = 'Promoter' THEN pct_shares END) AS promoter_pct
        FROM read_parquet('{HOLDINGS}')
        WHERE isin <> '' AND quarter_end <> ''
        GROUP BY 1, 2
    """).fetchall()
    named: dict[tuple[str, str], dict[str, tuple[str, float | None]]] = {}
    if PROMOTERS_OUT.exists():
        for isin, q, name, pct in con.execute(
                f"SELECT isin, quarter_end, name, pct_shares FROM read_parquet('{PROMOTERS_OUT}')"
                " ORDER BY source_file").fetchall():
            norm = normalize(name)
            if not norm:
                continue
            d = named.setdefault((isin, q), {})
            prev = d.get(norm)
            # One holder listed under two axes, or two spellings that normalise
            # alike, is one entity holding the sum.
            if prev and prev[1] is not None and pct is not None:
                d[norm] = (prev[0], prev[1] + pct)
            elif not prev:
                d[norm] = (name, pct)
    out: dict[str, list[Filing]] = {}
    for isin, q, bd, ppct in heads:
        out.setdefault(isin, []).append(Filing(q, bd or "", named.get((isin, q), {}), ppct))
    return out


def build(env: str | None = None) -> Report:
    rep = Report()
    if not HOLDINGS.exists():
        return rep
    con = duckdb.connect(str(research_db(env)))
    try:
        by_isin = _filings(con)
        ids = dict(con.execute("SELECT isin, security_id FROM security_master WHERE isin IS NOT NULL").fetchall())
        rows = []
        for isin, filings in sorted(by_isin.items()):
            rep.filings += len(filings)
            sid = ids.get(isin)
            rs, nd, nn, dg = runs(filings)
            rep.skipped_no_date += nd
            rep.skipped_no_names += nn
            rep.degenerate += dg
            if not rs:
                continue
            if sid is None:
                rep.isins_unmatched += 1
                if len(rep.unmatched_examples) < 3:
                    rep.unmatched_examples.append(isin)
                continue
            rep.securities += 1
            rows += [(sid, r.entity_name, r.normalized_name, r.valid_from, r.valid_to, r.holding_pct)
                     for r in rs]
        rep.runs = len(rows)
        rep.open_runs = sum(1 for r in rows if r[4] is None)
        rep.entities = len({(r[0], r[2]) for r in rows})

        # Rebuilt whole each run, like every other derived table here: the
        # sweep adds filings to the past as well as the present, and a run's
        # end can move when a missing quarter arrives.
        con.execute("BEGIN")
        con.execute("DELETE FROM promoter_entities")
        con.executemany(
            "INSERT INTO promoter_entities (security_id, entity_name, normalized_name,"
            " valid_from, valid_to, holding_pct, source_file_id)"
            " VALUES (?, ?, ?, CAST(? AS DATE), CAST(? AS DATE), ?, NULL)", rows)
        con.execute("COMMIT")
    finally:
        con.close()

    g = sqlite3.connect(governance_db(env))
    try:
        # The NEWEST version of each input — the one this build actually read.
        parents = [(r[0], "input") for r in g.execute(
            "SELECT artefact_hash FROM ("
            "  SELECT artefact_hash, ROW_NUMBER() OVER ("
            "    PARTITION BY logical_name ORDER BY produced_at DESC) AS rn"
            "  FROM artefact WHERE logical_name IN"
            "  ('collected:shp','warehouse:security_master')) WHERE rn = 1").fetchall()]
    finally:
        g.close()
    prov.register(
        prov.Artefact(
            prov.hash_params({"runs": rep.runs, "entities": rep.entities,
                              "securities": rep.securities}),
            "TABLE", "warehouse:promoter_entities", PRODUCED_BY, row_count=rep.runs,
            params={"securities": rep.securities, "entities": rep.entities}),
        parents=parents, env=env)
    return rep


def main() -> int:
    print("PROMOTER ENTITIES (Plan 1 §6.6) — point-in-time, from SHP Table II")
    print(build().render())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
