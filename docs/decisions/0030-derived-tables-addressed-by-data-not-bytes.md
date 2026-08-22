# 0030 — Derived tables are content-addressed by their data, not their bytes

**Date:** 2026-08-22
**Decided by:** Claude, on measurement, while commissioning the provenance DAG
**Status:** ACTIVE

## Context

Plan 2 §8.1 addresses every artefact by "the SHA-256 of content", and §8.2 claims
the graph can answer *"can I re-derive it exactly?"* with a yes. The first
implementation took that literally and hashed the files an artefact consists of.

Commissioning the DAG on 2026-08-22 falsified the claim immediately. Three
rebuilds of `price_spine` from **byte-identical inputs**, with no code change
between them, produced three different artefacts:

| rebuild | rows | total bytes | artefact hash |
|---|---:|---:|---|
| 1 | 7,749,148 | 169,144,874 | `a732879e40a5…` |
| 2 | 7,749,148 | 169,070,178 | `c5de91fc3c06…` |
| 3 | 7,749,148 | 169,182,344 | `181c6c6e2945…` |

The row count is identical and the byte count is not. DuckDB's parquet writer is
not byte-deterministic — row-group boundaries and dictionary-encoding decisions
vary with thread scheduling — so the same data serialises differently each run.

**Two consequences, both real.** Every rebuild of unchanged data registered a
duplicate node, so the graph grew without anything changing. And two results
computed from identical data would have recorded different input hashes,
making them look incomparable when they are not — the exact question Plan 2 §8.2
lists as the DAG's advantage over a hash chain.

## Decision

A **SOURCE** artefact continues to be addressed by its bytes. A **derived**
artefact — `TABLE`, `FEATURE`, `RESULT` — is addressed by an order-independent
checksum over its *data*: row count, `bit_xor` of per-row hashes, and `sum` of
per-row hashes, combined.

Verified: two consecutive rebuilds now yield `cbc344aea9a0d941` for
`price_spine` and `3adfebf3bf14d991` for `fno_spine`.

## Why

For a source file the bytes *are* the artefact, and reproducing them is exactly
the guarantee wanted. For a derived table the bytes are an implementation detail
of the writer; what must be reproducible is the content.

Both aggregates are order-independent because row order across parquet files is
not meaningful, and neither is used alone: XOR cancels on duplicated pairs, sum
is weak to compensating changes, and the row count catches gross truncation. A
collision must now defeat all three.

Options rejected:

- **Force deterministic writes** (`threads=1`, fixed row-group size). Slower on
  174M rows, dependent on DuckDB internals that carry no stability guarantee, and
  it would break again silently on a version bump.
- **Address derived tables by `derived_hash(inputs, params)`** — inputs plus
  settings, never looking at the output. Cheap and stable, but it asserts the
  output follows from the inputs rather than checking it, so a bug in the
  transform produces the same address as a correct run. That is the wrong
  direction for a provenance system to be wrong in.

## What would reverse this

DuckDB offering a documented byte-deterministic parquet write, which would make
file hashing correct again and strictly stronger — it would detect corruption
that a data checksum reads through.

## Cost accepted

- The checksum costs a full scan of the table on every registration: ~174M rows
  for `fno_spine`. Acceptable at Phase 1 cadence, and it would not be if this ran
  per-study.
- **Two artefacts can now share an address while differing on disk.** A corrupted
  parquet file that still decodes to the same rows hashes identically. File-level
  integrity is no longer covered by the artefact hash and would need its own
  check.
- The prod graph permanently carries **four superseded nodes** — three
  `price_spine` and one `fno_spine` registered under byte addressing before the
  fix. `artefact` is append-only by design, so they cannot be removed, and
  removing them would violate the guarantee this table exists to provide. They
  are commissioning residue, they informed no published result, and the correct
  nodes are distinguishable by `params_json.addressing = 'data_checksum'`.
