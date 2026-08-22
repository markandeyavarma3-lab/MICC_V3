"""migrate.py — forward-only, checksummed schema migrations.

WHY. Its predecessor had two governance stores and no migration runner for one of
them; the dev store drifted to 1 table while prod held 15, and the drift was only
discovered when an orchestrator crashed on `no such table: v3_resource_log`.

RULES.
  1. Forward only. There is no down-migration; a mistake is corrected by a new file.
  2. Applied files are checksummed. Editing one after it has run is an error, not
     a silent divergence.
  3. The runner is idempotent — running it twice applies nothing the second time.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from src.common.hashing import hash_bytes
from src.common.paths import MIGRATIONS

FILENAME = re.compile(r"^(\d{4})_([a-z0-9_]+)\.(sqlite|duckdb)\.sql$")


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    name: str
    target: str
    path: Path
    sql: str
    checksum: str


class MigrationError(RuntimeError):
    pass


def discover(target: str, directory: Path = MIGRATIONS) -> list[Migration]:
    """All migrations for a target, ordered by version.

    Filenames are `NNNN_name.<target>.sql`. A gap or duplicate in the version
    sequence is an error — both mean a file was lost or branched.
    """
    found: list[Migration] = []
    for path in sorted(directory.glob(f"*.{target}.sql")):
        m = FILENAME.match(path.name)
        if not m:
            raise MigrationError(f"{path.name} does not match NNNN_name.{target}.sql")
        sql = path.read_text()
        found.append(
            Migration(
                version=int(m.group(1)),
                name=m.group(2),
                target=m.group(3),
                path=path,
                sql=sql,
                checksum=hash_bytes(sql.encode()),
            )
        )
    versions = [f.version for f in found]
    if len(set(versions)) != len(versions):
        raise MigrationError(f"duplicate migration versions for {target}: {versions}")
    for i, v in enumerate(versions, start=1):
        if v != i:
            raise MigrationError(f"migration versions must be contiguous from 1; got {versions}")
    return found


_TRACKING = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    checksum    TEXT NOT NULL,
    applied_at  TEXT NOT NULL
)
"""


def _applied(con: sqlite3.Connection) -> dict[int, tuple[str, str]]:
    con.execute(_TRACKING)
    return {
        row[0]: (row[1], row[2])
        for row in con.execute("SELECT version, name, checksum FROM schema_migrations")
    }


def migrate_sqlite(db_path: Path, directory: Path = MIGRATIONS, dry_run: bool = False) -> list[int]:
    """Apply outstanding SQLite migrations. Returns the versions applied."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    pending = discover("sqlite", directory)
    con = sqlite3.connect(db_path)
    try:
        done = _applied(con)
        for mig in pending:
            if mig.version in done:
                _, checksum = done[mig.version]
                if checksum != mig.checksum:
                    raise MigrationError(
                        f"{mig.path.name} changed after it was applied "
                        f"(recorded {checksum[:12]}, now {mig.checksum[:12]}). "
                        "Migrations are immutable once run — add a new one instead."
                    )
        outstanding = [m for m in pending if m.version not in done]
        if dry_run:
            return [m.version for m in outstanding]

        applied: list[int] = []
        for mig in outstanding:
            try:
                con.executescript(mig.sql)
                con.execute(
                    "INSERT INTO schema_migrations (version, name, checksum, applied_at) "
                    "VALUES (?, ?, ?, ?)",
                    (mig.version, mig.name, mig.checksum, datetime.now(UTC).isoformat()),
                )
                con.commit()
            except Exception as exc:
                con.rollback()
                raise MigrationError(f"{mig.path.name} failed: {exc}") from exc
            applied.append(mig.version)
        return applied
    finally:
        con.close()


def split_statements(sql: str) -> list[str]:
    """Split a migration into statements, respecting comments and string literals.

    DuckDB's Python API executes one statement per call, and SQLite's
    `executescript` has no DuckDB equivalent — so the file has to be split here.

    NAIVE `sql.split(";")` DOES NOT WORK, and failed on the first real migration.
    A `--` comment may contain a semicolon: this schema carries the line
    *"Treating that as a delisting-to-zero is a large downward bias; ignoring it
    is an upward one"*, which a naive split cut in half and then tried to
    execute as SQL. Comments are stripped first, and quoted literals are tracked
    so a semicolon inside a string is not a terminator either.
    """
    out: list[str] = []
    buf: list[str] = []
    in_string = False
    i = 0
    while i < len(sql):
        ch = sql[i]
        if not in_string and ch == "-" and sql[i : i + 2] == "--":
            # Line comment: skip to the newline, keeping the newline itself so
            # tokens either side do not run together.
            nl = sql.find("\n", i)
            i = len(sql) if nl == -1 else nl
            continue
        if ch == "'":
            # Doubled '' inside a literal is an escaped quote, not a terminator.
            if in_string and sql[i : i + 2] == "''":
                buf.append("''")
                i += 2
                continue
            in_string = not in_string
        if ch == ";" and not in_string:
            stmt = "".join(buf).strip()
            if stmt:
                out.append(stmt)
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    tail = "".join(buf).strip()
    if tail:
        out.append(tail)
    return out


def migrate_duckdb(db_path: Path, directory: Path = MIGRATIONS, dry_run: bool = False) -> list[int]:
    """Apply outstanding DuckDB migrations. Returns the versions applied.

    WHY THIS EXISTS SEPARATELY, AND WHY IT WAS MISSING. `discover()` has always
    accepted a `duckdb` target — the filename regex names it — and no runner was
    ever written. So Plan 1 §5–§7's fourteen tables had nowhere to be created,
    which is why the archive parser could produce rows and never land them.

    ONE DIFFERENCE THAT MATTERS. DuckDB has no triggers. The write-once
    enforcement that makes the governance store trustworthy — refusing UPDATE and
    DELETE on `artefact`, `study_result` and the trial ledger — **cannot be
    reproduced here**, and nothing in this runner pretends otherwise. That is the
    right split rather than a limitation: the DuckDB side holds derived marts
    that are meant to be dropped and rebuilt, and the SQLite side holds the
    ledgers that must never change. A mart protected by triggers would be a mart
    you cannot rebuild.

    Versions are tracked per target, so DuckDB migrations number from 0001
    independently of the SQLite ones.
    """
    import duckdb

    db_path.parent.mkdir(parents=True, exist_ok=True)
    pending = discover("duckdb", directory)
    con = duckdb.connect(str(db_path))
    try:
        con.execute(_TRACKING)
        done = {
            row[0]: (row[1], row[2])
            for row in con.execute(
                "SELECT version, name, checksum FROM schema_migrations"
            ).fetchall()
        }
        for mig in pending:
            if mig.version in done and done[mig.version][1] != mig.checksum:
                raise MigrationError(
                    f"{mig.path.name} changed after it was applied "
                    f"(recorded {done[mig.version][1][:12]}, now {mig.checksum[:12]}). "
                    "Migrations are immutable once run — add a new one instead."
                )
        outstanding = [m for m in pending if m.version not in done]
        if dry_run:
            return [m.version for m in outstanding]

        applied: list[int] = []
        for mig in outstanding:
            try:
                con.execute("BEGIN TRANSACTION")
                for stmt in split_statements(mig.sql):
                    con.execute(stmt)
                con.execute(
                    "INSERT INTO schema_migrations (version, name, checksum, applied_at)"
                    " VALUES (?, ?, ?, ?)",
                    (mig.version, mig.name, mig.checksum, datetime.now(UTC).isoformat()),
                )
                con.execute("COMMIT")
            except Exception as exc:
                con.execute("ROLLBACK")
                raise MigrationError(f"{mig.path.name} failed: {exc}") from exc
            applied.append(mig.version)
        return applied
    finally:
        con.close()


def status(db_path: Path, directory: Path = MIGRATIONS) -> str:
    if not db_path.exists():
        return f"{db_path.name}: not created; {len(discover('sqlite', directory))} pending"
    con = sqlite3.connect(db_path)
    try:
        done = _applied(con)
    finally:
        con.close()
    pending = [m for m in discover("sqlite", directory) if m.version not in done]
    return f"{db_path.name}: {len(done)} applied, {len(pending)} pending"
