"""provenance.py — the content-addressed DAG, finally carrying rows.

WHY THIS MODULE EXISTS, AND WHY IT IS LATE.

Plan 2 §8 specified a provenance DAG on 2026-08-16 and migration 0001 created
`artefact` and `artefact_edge` the same week. On 2026-08-21 both tables still
held **zero rows**. The schema was real, the triggers were real and verified, and
nothing had ever written to them — so the project's answer to "which data and
which code produced this number?" was, in practice, the same answer its
predecessor gave: none.

That is the shape of defect this repository keeps finding in itself. A
declaration with no storage behind it is a diary entry (see migration 0002, which
is the same failure one level up, in the trial counters).

WHAT A CONTENT-ADDRESSED GRAPH BUYS OVER A HASH CHAIN.

A linear chain proves a record was not altered. It cannot answer which inputs
produced an output, whether two results used the same data version, or — the
operationally valuable one — **which published results a source restatement
invalidates**. NSE and BSE silently restate bulk-deal files (Plan 1 §5.4). When
that happens the question "what do I have to recompute?" is a graph walk here and
an archaeology exercise otherwise.

THE IDENTITY RULE. An artefact IS its content hash. Registering the same bytes
twice is a no-op, not a duplicate and not an error — that is what makes the
pipeline safely re-runnable. Registering DIFFERENT bytes under the same logical
name creates a SECOND artefact, and both persist. The triggers in migration 0001
refuse UPDATE and DELETE, so there is no way to express "this artefact changed";
the only expressible thing is "a new artefact exists", which is the truth.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from src.common.hashing import hash_file, hash_inputs, hash_params, merkle_root
from src.common.migrate import migrate_sqlite
from src.common.paths import ROOT, governance_db

ArtefactType = Literal["SOURCE", "TABLE", "FEATURE", "RESULT", "FIGURE", "CONFIG"]

#: Matches the CHECK constraint in migration 0001. Duplicated deliberately so a
#: bad type fails in Python with a readable message rather than as a SQLite
#: constraint error naming no column.
VALID_TYPES: frozenset[str] = frozenset(
    {"SOURCE", "TABLE", "FEATURE", "RESULT", "FIGURE", "CONFIG"}
)


class ProvenanceError(RuntimeError):
    """An illegal use of the graph. Deliberately fatal."""


@lru_cache(maxsize=1)
def code_commit() -> str:
    """The commit that produced an artefact, or an explicit marker.

    Never silently returns a placeholder that reads like a hash. A result whose
    provenance says 'UNKNOWN' is honest; one that says '0000000' looks like a
    commit and is a lie the DAG would carry forever.
    """
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT, capture_output=True, text=True, timeout=10,
        )
        if out.returncode == 0 and out.stdout.strip():
            sha = out.stdout.strip()
            dirty = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=ROOT, capture_output=True, text=True, timeout=10,
            ).stdout.strip()
            # A dirty tree means the code that ran is NOT the commit. Recording
            # the bare sha would make an unreproducible run look reproducible.
            return f"{sha}-dirty" if dirty else sha
    except (OSError, subprocess.SubprocessError):
        pass
    return "UNKNOWN"


@dataclass(frozen=True, slots=True)
class Artefact:
    """One node. `artefact_hash` is the identity, not `logical_name`."""

    artefact_hash: str
    artefact_type: ArtefactType
    logical_name: str
    produced_by: str
    row_count: int | None = None
    byte_size: int | None = None
    params: dict[str, Any] | None = None


def _con(env: str | None = None) -> sqlite3.Connection:
    db = governance_db(env)
    migrate_sqlite(db)
    con = sqlite3.connect(db)
    con.execute("PRAGMA foreign_keys = ON")
    return con


# --- hashing whole datasets ---------------------------------------------------


def hash_dataset(path: Path | str, pattern: str = "**/*.parquet") -> tuple[str, int]:
    """Content hash of a multi-file dataset, plus its total byte size.

    A partitioned parquet dataset is one logical table across many files, so its
    identity must be one hash. Built from the sorted per-file hashes via
    `hash_inputs`, which means:

      - file ORDER cannot change the result (the inputs are a set)
      - adding, removing or altering ANY file changes the dataset hash
      - the same data written with different partition file NAMES hashes the
        same only if the bytes are identical, which is the property wanted

    Raises on an empty match rather than returning the hash of nothing. A silent
    empty dataset registering successfully is how a broken build reports GREEN.
    """
    root = Path(path)
    files = sorted(p for p in root.glob(pattern) if p.is_file())
    if not files:
        raise ProvenanceError(
            f"no files matching {pattern!r} under {root}. Refusing to register an "
            f"empty dataset: the hash of nothing is a valid hash and would look "
            f"like a successful build."
        )
    digests = [hash_file(p) for p in files]
    total = sum(p.stat().st_size for p in files)
    return hash_inputs(digests), total


# --- writing ------------------------------------------------------------------


def register(
    artefact: Artefact,
    parents: Sequence[tuple[str, str]] = (),
    env: str | None = None,
) -> bool:
    """Insert one artefact and its inbound edges. Returns True if newly inserted.

    `parents` is a sequence of (parent_hash, edge_role). Every parent must
    already exist — the foreign key enforces it — because an edge to an
    unregistered input is a lineage that cannot be walked.

    IDEMPOTENT BY CONSTRUCTION. Re-registering identical content does nothing and
    returns False. This is what lets the Phase 1 rebuild be re-run at will: the
    second run confirms the hashes still match rather than duplicating the graph.
    """
    if artefact.artefact_type not in VALID_TYPES:
        raise ProvenanceError(
            f"unknown artefact_type {artefact.artefact_type!r}; "
            f"valid: {sorted(VALID_TYPES)}"
        )
    if not artefact.artefact_hash or len(artefact.artefact_hash) != 64:
        raise ProvenanceError(
            f"artefact_hash must be a 64-char sha256 hex digest, got "
            f"{artefact.artefact_hash!r}"
        )
    if not artefact.logical_name.strip():
        raise ProvenanceError("an artefact needs a logical_name to be findable")

    con = _con(env)
    try:
        cur = con.execute(
            "INSERT INTO artefact (artefact_hash, artefact_type, logical_name,"
            " produced_by, code_commit, produced_at, row_count, byte_size, params_json)"
            " VALUES (?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT (artefact_hash) DO NOTHING",
            (
                artefact.artefact_hash,
                artefact.artefact_type,
                artefact.logical_name,
                artefact.produced_by,
                code_commit(),
                datetime.now(UTC).isoformat(),
                artefact.row_count,
                artefact.byte_size,
                json.dumps(artefact.params or {}, sort_keys=True, default=str),
            ),
        )
        inserted = cur.rowcount > 0

        for parent_hash, role in parents:
            if parent_hash == artefact.artefact_hash:
                raise ProvenanceError(
                    f"{artefact.logical_name}: an artefact cannot be its own "
                    f"parent — that is a cycle, and this is a DAG."
                )
            con.execute(
                "INSERT INTO artefact_edge (child_hash, parent_hash, edge_role)"
                " VALUES (?,?,?) ON CONFLICT (child_hash, parent_hash) DO NOTHING",
                (artefact.artefact_hash, parent_hash, role),
            )
        con.commit()
        return inserted
    except sqlite3.IntegrityError as exc:
        con.rollback()
        raise ProvenanceError(
            f"{artefact.logical_name}: {exc}. A foreign-key failure here means an "
            f"edge points at an input that was never registered — register inputs "
            f"before the things derived from them."
        ) from exc
    finally:
        con.close()


def register_file(
    path: Path | str,
    artefact_type: ArtefactType,
    logical_name: str,
    produced_by: str,
    parents: Sequence[tuple[str, str]] = (),
    params: dict[str, Any] | None = None,
    row_count: int | None = None,
    env: str | None = None,
) -> str:
    """Register a single file by its content hash. Returns the hash."""
    p = Path(path)
    if not p.is_file():
        raise ProvenanceError(f"{p} is not a file")
    digest = hash_file(p)
    register(
        Artefact(digest, artefact_type, logical_name, produced_by,
                 row_count=row_count, byte_size=p.stat().st_size, params=params),
        parents=parents, env=env,
    )
    return digest


def register_dataset(
    path: Path | str,
    artefact_type: ArtefactType,
    logical_name: str,
    produced_by: str,
    pattern: str = "**/*.parquet",
    parents: Sequence[tuple[str, str]] = (),
    params: dict[str, Any] | None = None,
    row_count: int | None = None,
    env: str | None = None,
) -> str:
    """Register a multi-file dataset as one node. Returns the dataset hash."""
    digest, total_bytes = hash_dataset(path, pattern)
    register(
        Artefact(digest, artefact_type, logical_name, produced_by,
                 row_count=row_count, byte_size=total_bytes, params=params),
        parents=parents, env=env,
    )
    return digest


def register_config(path: Path | str, env: str | None = None) -> str:
    """Register a config file as a CONFIG artefact.

    Configs are inputs like any other. `research.yml` changing between two runs
    is exactly as consequential as the price data changing, and until it is in
    the graph the two results look comparable when they are not.
    """
    p = Path(path)
    return register_file(
        p, "CONFIG", f"config:{p.name}", "configs", params={"path": str(p.name)}, env=env
    )


# --- reading ------------------------------------------------------------------


def lineage(artefact_hash: str, env: str | None = None) -> list[dict]:
    """Full ancestry of one artefact, breadth-first. The point of the whole DAG.

    Answers "what produced this number?" as a query rather than a memory.
    """
    con = _con(env)
    try:
        seen: set[str] = set()
        frontier = [artefact_hash]
        out: list[dict] = []
        while frontier:
            batch = [h for h in frontier if h not in seen]
            if not batch:
                break
            seen.update(batch)
            marks = ",".join("?" * len(batch))
            rows = con.execute(
                f"SELECT artefact_hash, artefact_type, logical_name, produced_by,"
                f" code_commit, produced_at, row_count FROM artefact"
                f" WHERE artefact_hash IN ({marks})",
                batch,
            ).fetchall()
            for r in rows:
                out.append({
                    "artefact_hash": r[0], "artefact_type": r[1], "logical_name": r[2],
                    "produced_by": r[3], "code_commit": r[4], "produced_at": r[5],
                    "row_count": r[6],
                })
            parents = con.execute(
                f"SELECT parent_hash FROM artefact_edge WHERE child_hash IN ({marks})",
                batch,
            ).fetchall()
            frontier = [p[0] for p in parents]
        return out
    finally:
        con.close()


def descendants(artefact_hash: str, env: str | None = None) -> list[dict]:
    """Everything derived from an artefact, transitively.

    THE RESTATEMENT QUERY. When a source file is restated, this is the list of
    results that are now suspect. Plan 2 §8.2 lists it as the row a hash chain
    cannot answer.
    """
    con = _con(env)
    try:
        seen: set[str] = set()
        frontier = [artefact_hash]
        out: list[dict] = []
        while frontier:
            marks = ",".join("?" * len(frontier))
            children = [
                c[0] for c in con.execute(
                    f"SELECT child_hash FROM artefact_edge WHERE parent_hash IN ({marks})",
                    frontier,
                ).fetchall()
            ]
            children = [c for c in children if c not in seen]
            if not children:
                break
            seen.update(children)
            marks = ",".join("?" * len(children))
            for r in con.execute(
                f"SELECT artefact_hash, artefact_type, logical_name, produced_by"
                f" FROM artefact WHERE artefact_hash IN ({marks})", children,
            ).fetchall():
                out.append({
                    "artefact_hash": r[0], "artefact_type": r[1],
                    "logical_name": r[2], "produced_by": r[3],
                })
            frontier = children
        return out
    finally:
        con.close()


def count(env: str | None = None) -> tuple[int, int]:
    """(artefacts, edges). Used by the status report and by tests."""
    con = _con(env)
    try:
        return (
            con.execute("SELECT COUNT(*) FROM artefact").fetchone()[0],
            con.execute("SELECT COUNT(*) FROM artefact_edge").fetchone()[0],
        )
    finally:
        con.close()


# --- tamper evidence ----------------------------------------------------------


def write_merkle_root(as_of: str | None = None, env: str | None = None) -> str:
    """One verifiable fingerprint over the whole graph, per day (Plan 2 §8.3).

    The append-only triggers already make individual rows immutable. This makes
    the SET of rows verifiable too: a row quietly inserted with a backdated
    `produced_at` changes the root for that day.

    Idempotent within a day only while the graph has not grown. If it has, the
    root genuinely differs, and `merkle_log` refuses the UPDATE — which is the
    correct behaviour and surfaces as an error rather than a silent overwrite.
    """
    day = as_of or datetime.now(UTC).date().isoformat()
    con = _con(env)
    try:
        hashes = [r[0] for r in con.execute("SELECT artefact_hash FROM artefact")]
        root = merkle_root(hashes)
        existing = con.execute(
            "SELECT merkle_root FROM merkle_log WHERE as_of_date = ?", (day,)
        ).fetchone()
        if existing:
            if existing[0] != root:
                raise ProvenanceError(
                    f"the merkle root for {day} is already recorded as "
                    f"{existing[0][:12]} and the graph now hashes to {root[:12]}. "
                    f"The log is append-only, so this cannot be overwritten. The "
                    f"graph grew after the day's root was sealed — record "
                    f"tomorrow's root, or seal later in the run."
                )
            return root
        con.execute(
            "INSERT INTO merkle_log (as_of_date, merkle_root, artefact_count,"
            " computed_at) VALUES (?,?,?,?)",
            (day, root, len(hashes), datetime.now(UTC).isoformat()),
        )
        con.commit()
        return root
    finally:
        con.close()


def params_digest(params: dict[str, Any]) -> str:
    """Stable digest of a parameter set, for artefacts that are computed rather
    than stored — a result has no file to hash, so its identity is its inputs
    plus its parameters."""
    return hash_params(params)


def data_checksum(con, glob: str, columns: Sequence[str]) -> str:
    """Content address of a TABLE's DATA, independent of how it was serialised.

    WHY HASHING THE FILES IS WRONG FOR A DERIVED TABLE. Measured 2026-08-22:
    rebuilding `price_spine` three times from byte-identical inputs produced
    three different dataset hashes, with total sizes of 169,144,874 /
    169,070,178 / 169,182,344 bytes for the same 7,749,148 rows. DuckDB's parquet
    writer is not byte-deterministic — row-group boundaries and dictionary
    encoding vary with thread scheduling — so the same data serialises
    differently every run.

    The consequence was not cosmetic. Every rebuild registered a NEW artefact for
    unchanged data, so the graph accumulated duplicate nodes, and Plan 2 §8.2's
    claim that an artefact can be "re-derived exactly" was false at the byte
    level. Two results computed from identical data would have recorded different
    input hashes and looked incomparable.

    So a derived table is addressed by WHAT IT CONTAINS. `bit_xor` and `sum` over
    per-row hashes are both order-independent, which is the property needed since
    row order across parquet files is not meaningful. Both are combined with the
    row count: XOR alone cancels on duplicated pairs, and sum alone is weak to
    compensating changes, but a collision must now defeat all three at once.

    A SOURCE file keeps being hashed by its bytes — there, the bytes ARE the
    artefact, and reproducing them is exactly the guarantee wanted.
    """
    cols = ", ".join(columns)
    n, x, s = con.execute(
        f"SELECT COUNT(*), CAST(bit_xor(hash({cols})) AS VARCHAR),"
        f" CAST(sum(hash({cols}) % 1000000007) AS VARCHAR)"
        f" FROM read_parquet('{glob}')"
    ).fetchone()
    return hash_params({"rows": n, "xor": x, "sum": s, "columns": list(columns)})


def derived_hash(input_hashes: Iterable[str], params: dict[str, Any]) -> str:
    """Content address for a computed artefact with no file behind it.

    Combines the inputs and the parameters, so two runs agree if and only if both
    the data and the settings agree. This is what makes "did these two results
    use the same data version?" answerable.
    """
    return hash_inputs([*sorted(input_hashes), hash_params(params)])
