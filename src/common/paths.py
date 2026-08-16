"""paths.py — every filesystem and database location, resolved from the repo root.

WHY THIS MODULE EXISTS. Its predecessor stored absolute paths — 166 DuckDB views
containing `read_parquet('/Users/satya_03/Workspace/MICCV2/...')` — which broke on
any move and inside any container, and needed a repair script that took a write
lock to fix. Nothing here ever emits an absolute path into stored SQL. Views are
created with paths relative to ROOT, resolved at query time.

THE ENVIRONMENT IS EXPLICIT. Its predecessor's `verify_v3.py` defaulted to `dev`,
reported two critical failures there, and was GREEN only under `MICC_V3_ENV=prod`
— so the documented invocation was the failing one. Worse, running it in `dev`
shelled out and rebuilt the *prod* warehouse. Here an unset RESEARCH_ENV raises.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Final, Literal

Env = Literal["dev", "prod"]
VALID_ENVS: Final[frozenset[str]] = frozenset({"dev", "prod"})
ENV_VAR: Final[str] = "RESEARCH_ENV"

ROOT: Final[Path] = Path(__file__).resolve().parents[2]


class EnvironmentNotSet(RuntimeError):
    """Raised when RESEARCH_ENV is unset or invalid.

    Deliberately fatal. A silent default is how a dev-environment command ends up
    rebuilding a production warehouse.
    """


def env() -> Env:
    """The active environment. Raises rather than guessing."""
    raw = os.environ.get(ENV_VAR)
    if raw is None:
        raise EnvironmentNotSet(
            f"{ENV_VAR} is not set. Set it to one of {sorted(VALID_ENVS)}.\n"
            f"  RESEARCH_ENV=dev  python -m ...   # scratch\n"
            f"  RESEARCH_ENV=prod python -m ...   # the real warehouse\n"
            "There is no default: a silent one lets a dev command write to prod."
        )
    if raw not in VALID_ENVS:
        raise EnvironmentNotSet(f"{ENV_VAR}={raw!r} is not one of {sorted(VALID_ENVS)}.")
    return raw  # type: ignore[return-value]


# --- static locations, environment-independent -------------------------------

CONFIGS: Final[Path] = ROOT / "configs"
MIGRATIONS: Final[Path] = ROOT / "migrations"
DOCS: Final[Path] = ROOT / "docs"
LOGS: Final[Path] = ROOT / "logs"

#: The immutable seed carried from MICCV2. 1.2 GB, 126 parquet files, 2005-2026.
#: Irreplaceable — NSE does not serve this history. Never written to.
SEED: Final[Path] = ROOT / "data" / "raw" / "v1_export"

#: Permanent raw archive. Plan 1 §5. Append-only; files are never rewritten.
ARCHIVE: Final[Path] = ROOT / "data" / "raw" / "archive"


# --- environment-scoped locations --------------------------------------------


def data_dir(e: Env | None = None) -> Path:
    return ROOT / "data" / (e or env())


def warehouse_dir(e: Env | None = None) -> Path:
    """Parquet marts. Derived and regenerable — safe to delete and rebuild."""
    return data_dir(e) / "warehouse"


def snapshot_dir(e: Env | None = None) -> Path:
    """Read-only database copies that readers use.

    Its predecessor served 12 dashboard pages straight off the live DuckDB file;
    7 of them returned HTTP 500 whenever any writer held the lock, because DuckDB
    refuses even read_only connections against a locked file. Readers point here.
    """
    return data_dir(e) / "snapshots"


def research_db(e: Env | None = None) -> Path:
    """DuckDB: analytics, marts, and the relational deal tables."""
    return ROOT / "db" / f"research_{e or env()}.duckdb"


def governance_db(e: Env | None = None) -> Path:
    """SQLite: append-only ledgers. SQLite because it has real triggers."""
    return ROOT / "db" / f"governance_{e or env()}.sqlite"


def review_db(e: Env | None = None) -> Path:
    """SQLite: the participant review queue. Mutable by design."""
    return ROOT / "db" / f"review_{e or env()}.sqlite"


def ensure_dirs(e: Env | None = None) -> None:
    """Create every directory the active environment needs. Idempotent."""
    resolved = e or env()
    for d in (
        CONFIGS,
        LOGS,
        ARCHIVE,
        data_dir(resolved),
        warehouse_dir(resolved),
        snapshot_dir(resolved),
        ROOT / "db",
    ):
        d.mkdir(parents=True, exist_ok=True)


def relative_to_root(p: Path | str) -> str:
    """POSIX path relative to ROOT, for embedding in stored SQL.

    Raises if the path is outside the repo — an absolute path in a stored view is
    the defect this function exists to prevent.
    """
    resolved = Path(p).resolve()
    try:
        return resolved.relative_to(ROOT).as_posix()
    except ValueError as exc:
        raise ValueError(
            f"{resolved} is outside the repo root {ROOT}; it cannot be stored in a view."
        ) from exc
