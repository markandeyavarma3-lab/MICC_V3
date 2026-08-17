# 0013 — Re-run exp_001 under the DAG rather than annotate it as unreproducible

**Date:** 2026-08-17
**Decided by:** Owner, against my recommendation
**Status:** ACTIVE

## Context
Discovered 2026-08-17: **Finding 001's result is not reproducible.** The
registration was correctly ordered and the spec genuinely frozen, but the analysis
code was never committed. `scripts/` contains only `register_exp001.py` and
`collect_daily.sh`. The registry records the holdout as prose — "the complementary
half of names" — with no seed, no rule, no name list.

Nobody can regenerate `+0.237%/yr` and `−0.022%/yr`. Including me. And the
`artefact` table holds zero rows, so the provenance DAG has never had a node.

## Decision
Rebuild the analysis as committed, hashed code under the new partition and the
provenance DAG, and re-derive every number.

## Why
I recommended leaving it rejected and annotating it, on the grounds that re-running
to confirm a rejection buys little. The owner overrode this, and the stronger
argument is theirs: it makes exp_001 the first fully-provenanced result and proves
the DAG end-to-end **on a case where the answer is already known** — which is the
only safe way to commission a provenance system.

It also recovers the event-level −0.805% finding as a record rather than an
anecdote.

## What would reverse this
Deadline pressure. This is roughly a day spent confirming a known rejection, and
if the four studies fall behind, [0010](0010-project-kill-criterion.md) makes that
day expensive.

## Cost accepted
~1 day. Also: the re-run cannot be clean confirmation, because ~100 exploratory
cells were run against the full universe on 2026-08-16. It carries a
`PRIOR_EXPOSURE` flag permanently.
