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
