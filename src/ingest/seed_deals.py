"""seed_deals.py — land the twenty-year corpus, honestly labelled.

WHY THIS IS SEPARATE FROM land.py.

`land.py` lands files the collector fetched: it saw the bytes arrive, it knows
when, and `publication.py` can bracket when they became observable. The V1 export
is different in a way that matters and must not be blurred:

  - it arrived as a parquet TABLE, not as the exchange's original bytes, so the
    raw row is a reconstruction and its `file_hash` is the parquet file's, not a
    hash of anything NSE published
  - **nobody recorded when any of it became public.** The 2006-2026 sessions have
    no observation of publication time and none can be obtained, so
    `available_from` for every one of these rows is the conservative bound at
    LOW confidence — never the measured value the collector now produces

Landing both through one path would let 235,880 rows of unknown provenance
inherit the credibility of 611 rows of known provenance. They are kept
distinguishable by `parser_version`, which carries `v1seed`, and by a
`source_url` that says where they actually came from.

WHY LAND THEM AT ALL. Because until now the corpus had never passed through the
pipeline. `eligibility.py` read the seed parquet directly, so every number built
on it — including the twelve-month result decision 0034 rests on — bypassed the
archive, the identity layer and the provenance DAG entirely. A result that skips
its own governance is exactly what this project exists not to produce.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

import duckdb

from src.common.hashing import hash_file
from src.common.migrate import migrate_duckdb
from src.common.paths import SEED, research_db
from src.governance import provenance as prov

#: Deliberately NOT the live parser's version. These rows were reconstructed from
#: a V1 parquet export, not parsed from exchange bytes, and the difference must
#: survive into the table rather than living in a commit message.
SEED_PARSER_VERSION = "v1seed-1.0.0"

PRODUCED_BY = "src.ingest.seed_deals:land_seed"

SOURCES = (("bulk_deals.parquet", "BULK"), ("block_deals.parquet", "BLOCK"))


@dataclass
class SeedReport:
    files: int = 0
    rows: int = 0
    skipped: int = 0
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems

    def render(self) -> str:
        return (f"  source files  {self.files:>8}\n"
                f"  rows landed   {self.rows:>8,}\n"
                f"  skipped       {self.skipped:>8}  (already held)"
                + "".join(f"\n  PROBLEM       {p}" for p in self.problems))


def land_seed(env: str | None = None) -> SeedReport:
    """Land bulk and block deals from the V1 export into institutional_deals_raw.

    Idempotent on the parquet file's hash, like every other landing. One
    `deal_source_files` row per source table, because that is what the artefact
    actually was — one file — rather than pretending there were 5,000 daily
    files nobody ever saw.
    """
    db = research_db(env)
    migrate_duckdb(db)
    con = duckdb.connect(str(db))
    rep = SeedReport()
    now = datetime.now(UTC).replace(tzinfo=None)

    try:
        for filename, deal_type in SOURCES:
            path = SEED / filename
            if not path.is_file():
                rep.problems.append(f"missing seed table: {path}")
                continue

            digest = hash_file(path)
            if con.execute(
                "SELECT 1 FROM deal_source_files WHERE file_hash = ?", (digest,)
            ).fetchone():
                rep.skipped += 1
                continue

            n = con.execute(
                f"SELECT COUNT(*) FROM read_parquet('{path}')"
            ).fetchone()[0]
            span = con.execute(
                f"SELECT MIN(date), MAX(date) FROM read_parquet('{path}')"
            ).fetchone()

            file_id = int(con.execute(
                "SELECT COALESCE(MAX(source_file_id),0)+1 FROM deal_source_files"
            ).fetchone()[0])
            con.execute(
                "INSERT INTO deal_source_files (source_file_id, exchange, report_type,"
                " source_url, report_date, downloaded_at, file_name, file_hash,"
                " file_bytes, parser_version, row_count, ingestion_status, revision_number)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (file_id, "NSE", deal_type,
                 f"v1seed://{filename}",
                 # The report_date of a 20-year table is its LAST session. There
                 # is no single date this file describes, and inventing one would
                 # be worse than recording the boundary.
                 span[1], now, filename, digest, path.stat().st_size,
                 SEED_PARSER_VERSION, n, "OK", 0),
            )

            base = int(con.execute(
                "SELECT COALESCE(MAX(raw_deal_id),0)+1 FROM institutional_deals_raw"
            ).fetchone()[0])
            # Done as one INSERT..SELECT rather than a Python loop: 223,450 rows
            # through executemany is minutes, through DuckDB it is seconds, and
            # the row-by-row version has no advantage in clarity.
            con.execute(f"""
                INSERT INTO institutional_deals_raw (
                    raw_deal_id, source_file_id, exchange, deal_type, trade_date,
                    symbol_raw, security_name_raw, client_name_raw, side_raw,
                    quantity_raw, deal_price_raw, remarks_raw, raw_row_json,
                    row_index, ingested_at)
                SELECT
                    {base} + (ROW_NUMBER() OVER () - 1),
                    {file_id}, 'NSE', '{deal_type}', CAST(date AS DATE),
                    symbol, name, client, buy_sell,
                    -- TEXT, per Plan 1 §5.3, exactly as the live parser keeps them.
                    CAST(qty AS VARCHAR), CAST(price AS VARCHAR),
                    {"remarks" if deal_type == "BULK" else "NULL"},
                    to_json({{'date': date, 'symbol': symbol, 'name': name,
                              'client': client, 'buy_sell': buy_sell,
                              'qty': qty, 'price': price}}),
                    ROW_NUMBER() OVER () - 1,
                    '{now}'
                FROM read_parquet('{path}')
            """)
            rep.files += 1
            rep.rows += n

            prov.register(
                prov.Artefact(digest, "SOURCE", f"v1seed:{deal_type.lower()}_deals",
                              PRODUCED_BY, row_count=n,
                              byte_size=path.stat().st_size,
                              params={"span": f"{span[0]}..{span[1]}",
                                      "parser_version": SEED_PARSER_VERSION,
                                      "available_from": "UNKNOWN - no publication "
                                                        "time was ever recorded"}),
                env=env,
            )
    finally:
        con.close()
    return rep


def main() -> int:
    print("LAND V1 SEED DEALS -> institutional_deals_raw")
    print(f"  parser_version {SEED_PARSER_VERSION} — reconstructed from a parquet")
    print("  export, NOT parsed from exchange bytes. available_from is UNKNOWN for")
    print("  every row and can never be recovered.")
    r = land_seed()
    print(r.render())
    return 0 if r.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
