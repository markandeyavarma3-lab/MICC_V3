"""bhavcopy.py — archived NSE bhavcopy becomes a price-spine increment.

WHY IT WRITES AN INCREMENT RATHER THAN TOUCHING THE SPINE.

`spine.py` builds `price_spine` by unioning a seed glob with an increment glob,
declaring the unique key rather than guessing it, and failing on duplicates. It
already does everything this data needs. So the correct integration is to land
parquet in the shape the increments already have and let the existing builder
pick it up — no new writer, no second definition of what a price row is, and the
duplicate guard applies to these rows exactly as it does to the seed's.

THE SERIES FILTER IS MEASURED, NOT CHOSEN. Reconciled 2026-09-01 against the one
session held by both sources, 2026-08-14:

    series          bhav rows   covers spine   new    OHLCV mismatches
    EQ                  2,463    2,410/2,683    53                   0
    EQ+BE               2,713    2,655/2,683    58                   0
    EQ+BE+BZ            2,741    2,683/2,683    58                   0

`EQ+BE+BZ` reproduces the seed's universe EXACTLY — every one of the 28 symbols
that EQ+BE missed is in the BZ surveillance series, which the MICCV2 pipeline
evidently kept. And on the 2,683 shared symbols, open, high, low, close and
volume are identical to the last paisa and the last share. That agreement is the
evidence that this parser reproduces a pipeline nobody here wrote, rather than
merely producing plausible numbers.

The 58 rows bhavcopy has and the seed does not are new listings, present in the
spine on no date at all. They join the universe, which is the correct behaviour:
a universe that cannot grow silently drops every company listed after the seed
was cut.

WHAT THIS DOES NOT DO. It does not adjust for corporate actions. `price_spine`
is the RAW series and this extends the raw series only; `build_adjusted()` owns
the splice and has its own guard that refuses to run if a SPLIT, BONUS or RIGHTS
falls after the adjusted seed ends. That guard is the thing standing between an
extended raw series and a silently corrupted adjusted one, so it is left to do
its job rather than second-guessed here.
"""

from __future__ import annotations

import csv
import gzip
import io
import sys
import zipfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.common.paths import ARCHIVE, COLLECTED, SEED_INCREMENTS  # noqa: E402
from src.governance import provenance as prov  # noqa: E402

#: Measured above. Changing this changes the universe, so it is a declared
#: constant rather than an argument with a default.
#
#: EQ ONLY, AND THAT IS A CORRECTION MADE 2026-09-01. This read
#: ("EQ", "BE", "BZ") until an external validation against MICC's raw bhavcopy
#: archive established what the seed actually contains: on 2018-04-23 the spine
#: holds 1,503 of 1,503 EQ symbols and 0 of 134 BE, 0 of 83 SM, 0 of 21 BZ.
#: Twenty-one years of seed are EQ-only and nothing said so anywhere.
#:
#: Collecting BE and BZ would have made the universe change character at
#: 2026-08-17 — the same class of boundary inconsistency decision 0040 created
#: for fund units, and a worse one, because BE is the trade-to-trade surveillance
#: segment that stocks enter precisely when their price is behaving unusually.
#:
#: The seed cannot be extended backwards; it is the only copy. So the collector
#: matches the seed rather than the reverse. See decision 0045.
SERIES = ("EQ",)

#: Indian ISINs encode the instrument class in the first three characters: INE
#: is an equity share, INF is a mutual-fund or ETF unit. That is a registry
#: rule, not a naming convention, so it holds where a symbol-suffix heuristic
#: would not — nothing about "PSUBANK" or "NV20" says fund.
#:
#: ETF UNITS LEAVE THE UNIVERSE (decision 0040). Seven of the unexplained price
#: discontinuities in the tail were clean 1:10 ETF splits with NO record in the
#: corporate-actions API, because its `index=equities` does not cover fund
#: units. So they are exactly the rows that cannot be adjusted and cannot be
#: verified — and they buy nothing: of 237,340 deals, 174 are in INF instruments
#: and ZERO of those are eligible for research.
#:
#: Collecting prices for instruments the universe excludes and the adjustment
#: cannot fix is what put the discontinuities there in the first place.
EQUITY_ISIN_PREFIX = "INE"

PRICE_ARCHIVE = ARCHIVE / "PRICE" / "NSE"
OUT_DIR = COLLECTED / "prices"

#: The increment schema, in order, exactly as the 27 existing files have it.
COLUMNS = ("symbol", "date", "open", "high", "low", "close", "volume")


class BhavcopyError(RuntimeError):
    """The file cannot be parsed into the increment schema. Deliberately fatal."""


@dataclass(frozen=True, slots=True)
class ParseResult:
    session: date
    rows: int
    skipped_series: int
    path: Path


def archived_files() -> list[Path]:
    return sorted(PRICE_ARCHIVE.glob("**/*.csv.zip.gz"))


def read_rows(path: Path) -> list[dict[str, str]]:
    """The CSV inside the gzipped zip. Raw bytes are never modified in place."""
    try:
        with zipfile.ZipFile(io.BytesIO(gzip.open(path, "rb").read())) as z:
            names = [n for n in z.namelist() if n.lower().endswith(".csv")]
            if len(names) != 1:
                raise BhavcopyError(f"{path.name}: expected one csv, found {len(names)}")
            with z.open(names[0]) as fh:
                return list(csv.DictReader(io.TextIOWrapper(fh, "utf-8")))
    except (zipfile.BadZipFile, OSError, gzip.BadGzipFile) as exc:
        raise BhavcopyError(f"{path.name}: unreadable ({exc})") from exc


def to_increment(rows: list[dict[str, str]]) -> tuple[list[tuple], date, int]:
    """Bhavcopy rows -> increment tuples. Every drop is counted, none is silent."""
    if not rows:
        raise BhavcopyError("empty file")
    sessions = {r["TradDt"].strip() for r in rows if r.get("TradDt")}
    if len(sessions) != 1:
        raise BhavcopyError(f"expected one TradDt, found {sorted(sessions)[:5]}")
    session = date.fromisoformat(sessions.pop())

    out, skipped = [], 0
    for r in rows:
        if r.get("SctySrs") not in SERIES:
            skipped += 1
            continue
        if not (r.get("ISIN") or "").startswith(EQUITY_ISIN_PREFIX):
            skipped += 1
            continue
        try:
            out.append((
                r["TckrSymb"].strip(),
                session.isoformat(),
                float(r["OpnPric"]), float(r["HghPric"]),
                float(r["LwPric"]), float(r["ClsPric"]),
                int(float(r["TtlTradgVol"])),
            ))
        except (KeyError, ValueError) as exc:
            # A row that cannot be read is a defect, not a filter. Plan 1's rule
            # is zero silent drops; only the series filter may remove a row.
            raise BhavcopyError(f"{session}: unparseable row {r.get('TckrSymb')!r}: {exc}") from exc

    if not out:
        raise BhavcopyError(f"{session}: no rows survived the {SERIES} filter")
    dupes = len(out) - len({(r[0], r[1]) for r in out})
    if dupes:
        raise BhavcopyError(f"{session}: {dupes} duplicate (symbol, date) rows")
    return out, session, skipped


def write_increment(path: Path) -> ParseResult:
    import duckdb

    rows, session, skipped = to_increment(read_rows(path))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    dest = OUT_DIR / f"date={session.isoformat()}.parquet"

    con = duckdb.connect()
    try:
        con.execute(
            "CREATE TABLE inc (symbol VARCHAR, date VARCHAR, open DOUBLE,"
            " high DOUBLE, low DOUBLE, close DOUBLE, volume BIGINT)"
        )
        con.executemany("INSERT INTO inc VALUES (?,?,?,?,?,?,?)", rows)
        # Written to a temp name and renamed: an interrupted run must not leave a
        # truncated parquet that the spine builder would read as a short session.
        tmp = dest.with_suffix(".parquet.partial")
        con.execute(f"COPY (SELECT {', '.join(COLUMNS)} FROM inc ORDER BY symbol)"
                    f" TO '{tmp}' (FORMAT PARQUET)")
        tmp.replace(dest)
    finally:
        con.close()
    return ParseResult(session, len(rows), skipped, dest)


def already_in_increments() -> set[str]:
    """Sessions the MICCV2 increments already own.

    The archive deliberately holds 2026-08-14 — it is the session both sources
    cover, and the evidence that this parser reproduces the seed exactly. But
    writing it here as well would put one date in two sources, which
    `spine._collected_part` refuses outright. The reconciliation is a reason to
    KEEP the bytes, not a reason to land the row twice.
    """
    return {p.name[len("date="):-len(".parquet")]
            for p in (SEED_INCREMENTS / "prices").glob("date=*.parquet")}


def run(overwrite: bool = False) -> list[ParseResult]:
    owned = already_in_increments()
    out = []
    for f in archived_files():
        rows = read_rows(f)
        session = date.fromisoformat(rows[0]["TradDt"].strip())
        if session.isoformat() in owned:
            continue
        dest = OUT_DIR / f"date={session.isoformat()}.parquet"
        if dest.exists() and not overwrite:
            continue
        out.append(write_increment(f))
    return out


PRODUCED_BY = "src/ingest/bhavcopy.py"


def register(env: str | None = None) -> str:
    """Register the collected prices as ONE source artefact in the DAG.

    A SOURCE with no parents, exactly like `seed:v1_export`. Its provenance does
    not live in the graph — it lives in the archive manifest, where every session
    carries the URL it came from, the sha256 of the bytes served, and the TradDt
    the file declared against the date requested. The graph's job is to let a
    later restatement of THIS artefact flag everything derived from it, and for
    that the content address is what matters.

    Registered separately from `seed:prices` so a restatement of one does not
    implicate the other. That separation is the entire reason these files live in
    `data/raw/collected` rather than beside the MICCV2 increments.
    """
    sessions = sorted(p.name[len("date="):-len(".parquet")] for p in OUT_DIR.glob("date=*.parquet"))
    return prov.register_dataset(
        OUT_DIR,
        artefact_type="SOURCE",
        logical_name="collected:prices",
        produced_by=PRODUCED_BY,
        pattern="**/*.parquet",
        params={
            "source": "NSE bhavcopy (UDiFF), archived by src/archive/prices.py",
            "series": list(SERIES),
            "isin_prefix": EQUITY_ISIN_PREFIX,
            "sessions": len(sessions),
            "first_session": sessions[0] if sessions else None,
            "last_session": sessions[-1] if sessions else None,
            "reconciled_against_seed_on": "2026-08-14",
            "reconciliation": "2683/2683 symbols, 0 OHLCV mismatches",
        },
        env=env,
    )


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Parse archived bhavcopy into price increments.")
    ap.add_argument("--overwrite", action="store_true",
                    help="rewrite increments that already exist")
    args = ap.parse_args()

    results = run(overwrite=args.overwrite)
    if not results:
        print("BHAVCOPY: every archived session already has an increment")
        return 0
    for r in sorted(results, key=lambda r: r.session):
        print(f"  {r.session}  {r.rows:>5,} rows  ({r.skipped_series:,} other series)")
    digest = register()
    print(f"\nBHAVCOPY: {len(results)} session(s) written to {OUT_DIR}")
    print(f"  registered collected:prices as {digest[:16]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
