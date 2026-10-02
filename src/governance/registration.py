"""registration.py — writing a pre-registration so the stored row reproduces its hash.

Extracted 2026-10-03 from scripts/register_exp004.py for exp_005, carrying the
two repairs exp_004's rehearsal forced (docs/plan/EXP004_..._DRAFT.md §9):

  - spec fields with no registry column are stored in configuration_json
    under EXTRA_KEY, never silently dropped while still being hashed;
  - the INSERT is committed only if the row read back reproduces the hash.

register_exp004.py keeps its own copy (it was rehearsed and pinned as it is);
new registrations use this.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
from datetime import UTC, datetime

from src.common.hashing import spec_hash

EXTRA_KEY = "spec_fields_without_a_column"


def stored_spec(row: dict, spec_keys: list[str]) -> dict:
    extra = json.loads(row["configuration_json"] or "{}").get(EXTRA_KEY, {})
    return {k: (extra[k] if k in extra else row[k]) for k in spec_keys}


def register(con: sqlite3.Connection, experiment_id: str, engine_id: str, spec: dict,
             config: dict, commit: str, trials_before: int, created_by: str) -> str:
    sh = spec_hash(spec)
    cols = [r[1] for r in con.execute("PRAGMA table_info(experiment_registry)")]
    cfg = {**config, EXTRA_KEY: {k: v for k, v in spec.items() if k not in cols}}
    row = {"experiment_id": experiment_id, "engine_id": engine_id, "status": "REGISTERED",
           "decision_reason": None, **{k: v for k, v in spec.items() if k in cols}, "spec_hash": sh,
           "created_at": datetime.now(UTC).isoformat(), "created_by": created_by,
           "configuration_json": json.dumps(cfg, sort_keys=True),
           "code_commit_hash": commit, "trials_before": trials_before}
    if con.execute("SELECT 1 FROM experiment_registry WHERE experiment_id = ?", (experiment_id,)).fetchone():
        raise RuntimeError(f"{experiment_id} is already registered; a registered spec is not rewritten.")
    use = {k: v for k, v in row.items() if k in cols}
    con.execute(f"INSERT INTO experiment_registry ({','.join(use)}) VALUES ({','.join('?' * len(use))})",
                list(use.values()))
    back = dict(zip(cols, con.execute("SELECT * FROM experiment_registry WHERE experiment_id = ?",
                                      (experiment_id,)).fetchone(), strict=True))
    again = spec_hash(stored_spec(back, list(spec)))
    if again != sh or back["spec_hash"] != sh:
        con.rollback()
        raise RuntimeError(f"the stored row does not reproduce the hash ({again[:12]} != {sh[:12]}); "
                           "nothing was committed")
    con.commit()
    return sh


def dirty_code() -> list[str]:
    out = subprocess.run(["git", "status", "--porcelain", "--", "src", "scripts", "configs", "migrations"],
                         capture_output=True, text=True).stdout
    return [ln for ln in out.splitlines() if ln.strip()]


def head() -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
