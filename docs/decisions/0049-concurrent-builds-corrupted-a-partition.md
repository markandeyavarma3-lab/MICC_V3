# 0049 — Two spine builds raced, corrupted a partition, and emptied three tables

**Date:** 2026-09-02
**Decided by:** Mine. Found while fixing an unrelated audit finding.
**Status:** ACTIVE

## Context

Immediately after wiring the relational half of the pipeline into
`collect_daily.sh` ([0048](0048-an-external-audit-found-what-the-machinery-did-not.md)),
the test suite began failing with `_duckdb.Error: TProtocolException: Invalid
data` and `238,032 raw rows produced 0 clean rows`.

`security_master` held **0 rows**. `institutional_deals_clean` held **0 rows**.
An hour earlier they held 3,421 and 238,032.

## What happened

**One parquet partition was corrupt:** `price_spine_adj/_y=2005/data_0.parquet`.

Two builds wrote it at once — a manual rebuild against the 22:30 scheduled run.
`collect_daily.sh` now rebuilds the spine three times a session, so the window
is no longer rare, and `spine.build()` had no mutual exclusion of any kind.

**The corruption was invisible to every count in the project.** `COUNT(*)` reads
the parquet footer, which was intact:

| query | result |
|---|---|
| `SELECT COUNT(*) FROM price_spine_adj` | 7,778,537 — fine |
| `SELECT COUNT(DISTINCT symbol) FROM price_spine_adj` | **TProtocolException** |

My first per-partition scan used `COUNT(*)` and reported **0 unreadable
partitions**. The file only fails when a column is actually read.

**Then `master.py` amplified it.** Its rebuild ran:

```
DELETE FROM symbol_history
DELETE FROM security_master
INSERT INTO security_master ... FROM read_parquet(spine)
```

DuckDB autocommits. The deletes stood; the insert died on the corrupt file.
`institutional_deals_clean` followed to 0 on the next mart build. **A transient
read error in one upstream file emptied three tables.**

## Decision

1. **`spine.build()` and `build_adjusted()` hold an exclusive lock**, one per
   spine, `mkdir`-based like `backup.sh`, with the same one-hour stale-lock
   rule. A second build raises `SpineError` rather than interleaving writes.
2. **`master.py` reads before it destroys.** The spine is materialised into a
   temp table *before* the deletes, so an unreadable partition raises with both
   tables still populated. Not a transaction: `security_master` and
   `symbol_history` are joined by a foreign key and DuckDB refuses the delete
   inside one.

Both verified by execution. The lock refuses a second acquisition and releases
cleanly; pointing `master.build()` at a deliberately corrupt parquet now fails
with `security_master` unchanged at 3,421 rows.

## What would reverse this

A build that legitimately needs to run twice at once — there is no such case
today, since the three daily slots are catch-ups for each other and `mkdir`
makes the loser exit rather than wait.

## Cost accepted

- **The spine has no integrity check of its own.** The gate's quality checks
  read `close`, so they would have caught this one, but nothing scans every
  partition column-by-column and nothing did so between the corruption and the
  next `master.py` run. The window was about an hour.
- **The lock is advisory and process-local.** Anything writing that directory
  without going through `spine.build()` still races.
- **A second build exits rather than waiting.** For a scheduled catch-up that is
  right; for someone running two by hand it is a confusing error rather than a
  queue.
- **`master.py`'s temp-table read duplicates work.** The spine's distinct
  symbols are now read twice per rebuild — once to prove it is readable, once in
  the INSERT.
- **The corruption itself was never explained beyond "concurrent writes".** No
  DuckDB bug was identified and no reproduction was attempted; the fix removes
  the condition rather than diagnosing it.
