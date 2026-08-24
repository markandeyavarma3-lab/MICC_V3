"""land.py — put the parsed rows somewhere they survive the process. Phase 2.1, 2.11.

THE BREAK THIS CLOSES. An audit on 2026-08-23 traced the pipeline end to end and
found it severed in the middle:

    archive bytes  OK  ->  parse  OK  ->  X  nothing wrote anything
                                          14 tables, 0 rows, and `research_db`
                                          referenced by no module at all

`parse.py` returned rows in memory and dropped them. `publication.py` measured
`available_from` and reported it to stdout. Everything downstream — the whole
eligibility and MDE work — read seed parquet directly and bypassed the archive,
the identity layer and the provenance DAG entirely. That is a pile of parts, not
a pipeline, and no number produced through it carried provenance.

IDEMPOTENT ON THE HASH, which is what makes re-running safe. `deal_source_files`
has UNIQUE(file_hash), so a file already landed is skipped rather than
duplicated. The whole archive can be re-landed at any time and the second run
confirms rather than repeats.

REVISION DETECTION COMES FREE HERE (Plan 1 §5.4). A revision is a new file_hash
for an (exchange, report_type, report_date) already held — which is precisely
what this loop already has to look up in order to be idempotent. Detecting it
separately would mean querying the same thing twice and letting the two answers
drift.

FII/DII LANDS AS A SOURCE FILE ONLY. `institutional_deals_raw` is constrained to
BULK|BLOCK by CHECK, because an FII/DII record is a market-wide aggregate with no
symbol, client or side — it does not belong in a table whose grain is one
disclosed deal. Its bytes and row count are recorded; its rows await their own
table, which no study needs yet.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

import duckdb

from src.common.migrate import migrate_duckdb
from src.common.paths import research_db
from src.governance import provenance as prov
from src.ingest.parse import ParsedFile, parse_all

#: Bumped when the parser's OUTPUT changes, never for a refactor. It is part of
#: deal_source_files' uniqueness key, so a bump re-lands every file under the new
#: version rather than silently mixing two parsers' output in one table.
PARSER_VERSION = "1.0.0"

PRODUCED_BY = "src.ingest.land:land"


@dataclass
class LandReport:
    files_landed: int = 0
    files_skipped: int = 0
    rows_landed: int = 0
    revisions: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems

    def render(self) -> str:
        lines = [
            f"  files landed  {self.files_landed:>6}",
            f"  files skipped {self.files_skipped:>6}  (hash already held)",
            f"  rows landed   {self.rows_landed:>6}",
        ]
        lines += [f"  REVISION      {r}" for r in self.revisions]
        lines += [f"  PROBLEM       {p}" for p in self.problems]
        return "\n".join(lines)


def _next_id(con: duckdb.DuckDBPyConnection, table: str, col: str) -> int:
    """DuckDB has no AUTOINCREMENT. max+1 is adequate at this volume and, unlike
    a sequence, survives the table being rebuilt by a migration."""
    return int(con.execute(f"SELECT COALESCE(MAX({col}), 0) + 1 FROM {table}").fetchone()[0])


def land_file(con: duckdb.DuckDBPyConnection, pf: ParsedFile, report: LandReport) -> None:
    """Land one parsed file. Skips silently if its hash is already held."""
    if pf.session_date is None and pf.status != "EMPTY":
        report.problems.append(f"{pf.path.name}: no session date, refusing to land undated rows")
        return

    held = con.execute(
        "SELECT source_file_id FROM deal_source_files WHERE file_hash = ?", (pf.sha256,)
    ).fetchone()
    if held:
        report.files_skipped += 1
        return

    session = pf.session_date
    # A revision: same session already held under a different hash. Detected from
    # the lookup this function already needs, so the two cannot disagree.
    prior = con.execute(
        "SELECT source_file_id, revision_number FROM deal_source_files"
        " WHERE exchange = ? AND report_type = ? AND report_date = ?"
        " ORDER BY revision_number DESC LIMIT 1",
        (pf.exchange, pf.report_type, session),
    ).fetchone() if session else None

    revision_number = 0
    if prior:
        revision_number = int(prior[1]) + 1
        report.revisions.append(
            f"{pf.report_type} {session} -> revision {revision_number} "
            f"(prior file {prior[0]}, new hash {pf.sha256[:8]})"
        )

    file_id = _next_id(con, "deal_source_files", "source_file_id")
    now = datetime.now(UTC).replace(tzinfo=None)
    con.execute(
        "INSERT INTO deal_source_files (source_file_id, exchange, report_type,"
        " source_url, report_date, downloaded_at, file_name, file_hash, file_bytes,"
        " parser_version, row_count, ingestion_status, error_message, revision_number)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (file_id, pf.exchange, pf.report_type,
         f"archive://{pf.path.name}", session, now, pf.path.name, pf.sha256,
         pf.path.stat().st_size, PARSER_VERSION, len(pf.rows),
         pf.status, pf.error, revision_number),
    )

    if prior:
        con.execute(
            "INSERT INTO source_revisions (revision_id, exchange, report_type,"
            " report_date, prior_file_id, new_file_id, detected_at, review_status)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (_next_id(con, "source_revisions", "revision_id"), pf.exchange,
             pf.report_type, session, prior[0], file_id, now, "PENDING"),
        )

    # FII/DII is a market-wide aggregate with no symbol or client. Its file is
    # recorded; its rows have no home in a table whose grain is one deal.
    if pf.report_type in ("BULK", "BLOCK") and pf.rows:
        base = _next_id(con, "institutional_deals_raw", "raw_deal_id")
        con.executemany(
            "INSERT INTO institutional_deals_raw (raw_deal_id, source_file_id,"
            " exchange, deal_type, trade_date, symbol_raw, security_name_raw,"
            " client_name_raw, side_raw, quantity_raw, deal_price_raw, remarks_raw,"
            " raw_row_json, row_index, ingested_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                (base + i, file_id, pf.exchange, pf.report_type, r["session_date"],
                 r.get("symbol"), r.get("name"), r.get("client"), r.get("buy_sell"),
                 r.get("qty"), r.get("price"), r.get("remarks"),
                 r["raw_row_json"], r["row_index"], now)
                for i, r in enumerate(pf.rows)
            ],
        )
        report.rows_landed += len(pf.rows)

    report.files_landed += 1


def land(env: str | None = None) -> LandReport:
    """Land every archived file. Read-only on the archive; append-only on the DB."""
    db = research_db(env)
    migrate_duckdb(db)
    con = duckdb.connect(str(db))
    report = LandReport()
    try:
        for pf in parse_all():
            land_file(con, pf, report)
    finally:
        con.close()

    # The landed tables are artefacts like any other. Their identity is their
    # DATA (decision 0030), not the bytes of a DuckDB file, which changes on any
    # write anywhere in the database.
    if report.files_landed:
        con = duckdb.connect(str(db))
        try:
            for table, key in (
                ("deal_source_files", ("file_hash", "report_date", "revision_number")),
                ("institutional_deals_raw", ("raw_row_json", "row_index")),
            ):
                n = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                if not n:
                    continue
                cols = ", ".join(key)
                digest = prov.hash_params({
                    "table": table, "rows": n, "parser_version": PARSER_VERSION,
                    "xor": str(con.execute(
                        f"SELECT CAST(bit_xor(hash({cols})) AS VARCHAR) FROM {table}"
                    ).fetchone()[0]),
                })
                prov.register(
                    prov.Artefact(digest, "TABLE", f"warehouse:{table}", PRODUCED_BY,
                                  row_count=n,
                                  params={"parser_version": PARSER_VERSION}),
                    env=env,
                )
        finally:
            con.close()
    return report


def main() -> int:
    print(f"LAND ARCHIVE -> research_db  (parser {PARSER_VERSION})")
    r = land()
    print(r.render())
    if not r.ok:
        print("\nLAND: FAILED")
        return 1
    print("\nLAND: GREEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
