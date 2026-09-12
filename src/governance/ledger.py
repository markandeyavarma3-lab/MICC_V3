"""ledger.py — preconditions every governance write must satisfy.

TWO FAILURES, BOTH MEASURED 2026-09-12, BOTH SILENT.

1. WRITING INTO A LEDGER THAT DOES NOT EXIST YET. `provenance._con()` calls
   `migrate_sqlite()`, which CREATES the database if it is absent. On a machine
   without the production governance file, a registration script therefore
   created an empty ledger, wrote its row as the only content, printed a hash and
   exited 0. Nothing errored and nothing was registered: no prior artefacts, no
   trial counters, an empty `merkle_log`, no chain for the row to belong to.

   A fresh ledger is indistinguishable from the real one at the moment of insert,
   so the check has to be on CONTENT — does this database carry the history the
   project has already recorded?

2. RE-REGISTERING AN EXPERIMENT THAT IS ALREADY FROZEN. `register_exp002.py`
   wrote with `INSERT OR REPLACE`, which SQLite implements as delete-then-insert.
   It is not an UPDATE, so `experiment_spec_frozen` never fired, and REPLACE
   fires DELETE triggers only under `PRAGMA recursive_triggers` (off by default),
   so `experiment_no_delete` never fired either. Re-running the script silently
   rewrote spec_hash, test_count, created_at and trials_before.

   migrations/0003 closes that at the schema level for every writer. This module
   closes it in the caller too, and more strictly: even an IDENTICAL
   re-registration is refused here rather than silently resetting `created_at`
   to the day of the re-run. A registration's date is part of its claim.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from src.common.paths import governance_db


class LedgerRefused(RuntimeError):
    """A governance precondition failed. Deliberately fatal."""


def require_populated_ledger(env: str | None = None) -> Path:
    """Return the governance database, or raise if it is not the real ledger.

    Refuses a missing file, a file with no governance schema, and a schema with
    no artefacts or no merkle rows. Never creates anything.
    """
    db = Path(governance_db(env))
    if not db.exists():
        raise LedgerRefused(
            f"{db} does not exist. This is not the production ledger, and "
            f"creating one would produce a registration with nothing to append to."
        )
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        try:
            artefacts = con.execute("SELECT COUNT(*) FROM artefact").fetchone()[0]
            merkle = con.execute("SELECT COUNT(*) FROM merkle_log").fetchone()[0]
        except sqlite3.OperationalError as exc:
            raise LedgerRefused(f"{db} has no governance schema ({exc})") from exc
    finally:
        con.close()
    if artefacts == 0 or merkle == 0:
        raise LedgerRefused(
            f"{db} holds {artefacts} artefact(s) and {merkle} merkle row(s) — an "
            f"empty ledger. The real one carries prop_hft_classifier_coverage and "
            f"engine_1_deals_entity_verdict. Refusing to write a governance record "
            f"into a database that has no history to append to."
        )
    return db


def require_not_already_registered(
    experiment_id: str, spec_hash: str, env: str | None = None
) -> None:
    """Refuse to re-register an experiment that is already on the ledger.

    An identical re-run is refused rather than replayed: `INSERT OR REPLACE`
    would reset `created_at` and `trials_before` to the day of the re-run, and
    "registered before any outcome was computed" is a claim about a date.
    """
    db = require_populated_ledger(env)
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        row = con.execute(
            "SELECT spec_hash, created_at, status FROM experiment_registry "
            "WHERE experiment_id = ?", (experiment_id,)).fetchone()
    finally:
        con.close()
    if row is None:
        return
    existing, created_at, status = row
    if existing == spec_hash:
        raise LedgerRefused(
            f"{experiment_id} is already registered with this exact spec_hash "
            f"({spec_hash[:16]}…) on {created_at}, status {status}. Nothing to do. "
            f"Re-writing it would move created_at to today and restate a frozen "
            f"registration as a fresh one."
        )
    raise LedgerRefused(
        f"{experiment_id} is registered with a DIFFERENT spec_hash: ledger has "
        f"{existing[:16]}… from {created_at}, this script would write "
        f"{spec_hash[:16]}…. The specification is frozen — register a new "
        f"experiment instead of amending this one."
    )
