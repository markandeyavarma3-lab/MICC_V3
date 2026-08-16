"""hashing.py — content addressing for the provenance DAG (Plan 2 §8).

Every artefact the system produces is identified by the SHA-256 of its content,
and records the hashes of its inputs. That turns "what produced this number?"
into a graph walk instead of an archaeology exercise.

A linear hash chain — its predecessor's design — proves only that a record was
not altered. It cannot answer which data and which code produced a result, nor
which published results a source restatement invalidates. Those are the questions
that actually arise.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

CHUNK = 1024 * 1024
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()


def hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def hash_file(path: Path | str) -> str:
    """Streaming SHA-256. Handles the 1.2 GB seed without loading it."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while chunk := fh.read(CHUNK):
            h.update(chunk)
    return h.hexdigest()


def hash_params(params: dict[str, Any]) -> str:
    """Hash a parameter dict.

    Sorted keys and a fixed separator so logically identical params always hash
    identically regardless of construction order.
    """
    return hash_bytes(
        json.dumps(params, sort_keys=True, separators=(",", ":"), default=str).encode()
    )


def hash_inputs(input_hashes: list[str]) -> str:
    """Combine input hashes into one identifier for a derived artefact.

    Sorted, so the same inputs in any order produce the same result — the inputs
    are a set, not a sequence.
    """
    joined = "\n".join(sorted(input_hashes))
    return hash_bytes(joined.encode())


def spec_hash(spec: dict[str, Any]) -> str:
    """Hash an experiment specification (Plan 2 §2.1).

    Covers hypothesis, universe, horizons, cost policy, benchmark, pass bar and
    kill criteria. Changing any of them yields a different hash and therefore a
    different experiment — which is what stops an experiment being amended after
    its result is known.
    """
    required = {
        "hypothesis",
        "universe_definition",
        "holding_period",
        "entry_policy",
        "exit_policy",
        "cost_policy",
        "benchmark_policy",
        "pass_bar",
        "kill_criteria",
    }
    missing = required - spec.keys()
    if missing:
        raise ValueError(
            f"spec_hash requires {sorted(required)}; missing {sorted(missing)}. "
            "An experiment without a pass bar and a kill criterion is not pre-registered."
        )
    return hash_params(spec)


def merkle_root(hashes: list[str]) -> str:
    """Merkle root over artefact hashes — one fingerprint for the whole graph.

    Written to an append-only log daily, so the entire provenance DAG has a single
    verifiable value per day.
    """
    if not hashes:
        return EMPTY_SHA256
    level = sorted(hashes)
    while len(level) > 1:
        if len(level) % 2:
            level.append(level[-1])
        level = [hash_bytes((level[i] + level[i + 1]).encode()) for i in range(0, len(level), 2)]
    return level[0]
