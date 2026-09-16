"""fno.py — land the archived F&O bhavcopy and participant-wise OI. Decision 0065.

WHERE THIS SITS. 0058 archived the bytes. 0062 wrote the parsers and refused
to land. This is the land step, and it is deliberately the same shape as
`src/ingest/bhavcopy.py` for prices: archive -> parse -> one parquet per
session under `data/raw/collected/fno/` -> registered as ONE source artefact
(`collected:fno`) -> unioned into the spine by `spine.build(FNO)`, which
does the unique-key check and the provenance edge. Nothing here writes the
spine directly; the spine's own machinery is the only thing that does.

THE CUTOVERS ARE CONSTANTS, NOT DISCOVERED. `fno_spine` ends at 2026-08-14
(the last MICCV2 increment) and `participant_oi` at 2026-06-25 (the seed).
Only archived sessions strictly after those are landed. The stretch
2026-06-17..07-07 that a V1 increment loaded with raw UDiFF codes is
already in the spine and is NOT touched — re-landing it from the archive
would give the spine two versions of ten sessions, and `_collected_part`
would refuse the build. Cleaning that stretch is a separate decision.

PARTICIPANT OI ROWS CARRY THEIR OWN `source`. `participant_oi.load` rewrites
the table `WHERE source = 'v1_export'`; rows landed here are
`source = 'nse_participant_oi'` and survive a seed reload. `TOTAL` is kept,
verbatim, as the fifth category (migration 0004).
"""

from __future__ import annotations

import gzip
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.common.paths import ARCHIVE, COLLECTED, research_db  # noqa: E402
from src.governance import provenance as prov  # noqa: E402
from src.ingest import fo_bhavcopy as fo  # noqa: E402

PRODUCED_BY = "src/ingest/fno.py"
OUT_DIR = COLLECTED / "fno"

#: Last session the MICCV2 increment supplies to fno_spine. Archived sessions
#: on or before this are never landed (see module docstring).
FNO_CUTOVER = date(2026, 8, 14)
#: Last session the seed supplies to participant_oi.
POI_CUTOVER = date(2026, 6, 25)
POI_SOURCE = "nse_participant_oi"


@dataclass(frozen=True, slots=True)
class Landed:
    session: date
    rows: int
    path: Path | None


def _session_of(path: Path, prefix: str) -> date:
    stem = path.name[len(prefix):]
    return date(int(stem[0:4]), int(stem[4:6]), int(stem[6:8]))


def archived_fo() -> list[tuple[date, Path]]:
    """(session, path) for every STORED F&O bhavcopy in the archive."""
    out = []
    for p in (ARCHIVE / "FO" / "NSE").glob("**/FO_NSE_*.csv.zip.gz"):
        out.append((_session_of(p, "FO_NSE_"), p))
    return sorted(out)


def archived_participant_oi() -> list[tuple[date, Path]]:
    out = []
    for p in (ARCHIVE / "PARTICIPANT_OI" / "NSE").glob("**/PARTICIPANT_OI_NSE_*.csv.gz"):
        out.append((_session_of(p, "PARTICIPANT_OI_NSE_"), p))
    return sorted(out)


def landed_fo_sessions() -> set[date]:
    return {date.fromisoformat(p.name[len("date="):-len(".parquet")])
            for p in OUT_DIR.glob("date=*.parquet")}


def land_fo(dry_run: bool = False) -> list[Landed]:
    """Parse every archived session after FNO_CUTOVER that is not yet in
    OUT_DIR and write it as one parquet in the legacy spine shape."""
    done = landed_fo_sessions()
    out: list[Landed] = []
    for session, path in archived_fo():
        if session <= FNO_CUTOVER or session in done:
            continue
        leg = fo.to_legacy_spine(fo.parse_udiff_bytes(gzip.open(path, "rb").read()))
        got = {date.fromisoformat(d) for d in leg["date"].unique()}
        if got != {session}:
            raise fo.FoParseError(f"{path.name}: file says {sorted(got)}, archive says {session}")
        dest = OUT_DIR / f"date={session.isoformat()}.parquet"
        if not dry_run:
            OUT_DIR.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_suffix(".parquet.partial")
            leg.to_parquet(tmp, index=False)
            tmp.replace(dest)
        out.append(Landed(session, len(leg), dest if not dry_run else None))
    return out


def register_fo(env: str | None = None) -> str:
    sessions = sorted(landed_fo_sessions())
    return prov.register_dataset(
        OUT_DIR, artefact_type="SOURCE", logical_name="collected:fno",
        produced_by=PRODUCED_BY, pattern="**/*.parquet",
        params={"source": "NSE F&O bhavcopy (UDiFF), archived by src/archive/derivatives.py",
                "parser": "src/ingest/fo_bhavcopy.py", "decision": "0065",
                "sessions": len(sessions),
                "first_session": sessions[0].isoformat() if sessions else None,
                "last_session": sessions[-1].isoformat() if sessions else None,
                "cutover": FNO_CUTOVER.isoformat()},
        env=env,
    )


def land_participant_oi(env: str | None = None, dry_run: bool = False) -> list[Landed]:
    """Insert every archived session after POI_CUTOVER not already in the
    table, with source = POI_SOURCE. The 14 table columns only; the four
    sidecar source columns stay in the archive."""
    import duckdb

    db = research_db(env)
    con = duckdb.connect(str(db), read_only=dry_run)
    try:
        have = {r[0] for r in con.execute(
            "SELECT DISTINCT session_date FROM participant_oi").fetchall()}
        out: list[Landed] = []
        for session, path in archived_participant_oi():
            if session <= POI_CUTOVER or session in have:
                continue
            df = fo.parse_participant_oi_bytes(gzip.open(path, "rb").read(), session_date=session)
            rows = fo.to_participant_oi_rows(df)
            if not dry_run:
                con.register("_poi", rows)
                cols = ", ".join(rows.columns)
                con.execute(
                    f"INSERT INTO participant_oi ({cols}, source)"
                    f" SELECT {cols}, '{POI_SOURCE}' FROM _poi"
                )
                con.unregister("_poi")
            out.append(Landed(session, len(rows), None))
        if not dry_run:
            con.commit()
    finally:
        con.close()
    return out


def register_participant_oi(env: str | None = None) -> str:
    src = ARCHIVE / "PARTICIPANT_OI" / "NSE"
    sessions = [s for s, _ in archived_participant_oi() if s > POI_CUTOVER]
    return prov.register_dataset(
        src, artefact_type="SOURCE", logical_name="collected:participant_oi",
        produced_by=PRODUCED_BY, pattern="**/*.csv.gz",
        params={"source": "NSE participant-wise OI, archived by src/archive/derivatives.py",
                "parser": "src/ingest/fo_bhavcopy.py", "decision": "0065",
                "table_source": POI_SOURCE, "sessions": len(sessions),
                "first_session": sessions[0].isoformat() if sessions else None,
                "last_session": sessions[-1].isoformat() if sessions else None,
                "cutover": POI_CUTOVER.isoformat()},
        env=env,
    )


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true", help="parse and count; write nothing")
    ap.add_argument("--build-spine", action="store_true",
                    help="after landing, rebuild fno_spine (minutes; 174M rows)")
    a = ap.parse_args(argv)

    print("F&O LAND (decision 0065)" + ("  [DRY RUN]" if a.dry_run else ""))
    fo_rows = land_fo(dry_run=a.dry_run)
    for r in fo_rows:
        print(f"  fno   {r.session}  {r.rows:>8,} rows")
    print(f"  fno: {len(fo_rows)} session(s), {sum(r.rows for r in fo_rows):,} rows"
          f"  (cutover {FNO_CUTOVER}, already landed {len(landed_fo_sessions())})")
    poi_rows = land_participant_oi(dry_run=a.dry_run)
    for r in poi_rows:
        print(f"  poi   {r.session}  {r.rows:>8} rows")
    print(f"  participant_oi: {len(poi_rows)} session(s), {sum(r.rows for r in poi_rows)} rows"
          f"  (cutover {POI_CUTOVER})")
    if a.dry_run:
        return 0
    if fo_rows:
        print(f"  registered collected:fno as {register_fo()[:16]}")
    if poi_rows:
        print(f"  registered collected:participant_oi as {register_participant_oi()[:16]}")
    if a.build_spine:
        from src.warehouse import spine
        print("  rebuilding fno_spine ...")
        print(" ", spine.build(spine.FNO).render())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
