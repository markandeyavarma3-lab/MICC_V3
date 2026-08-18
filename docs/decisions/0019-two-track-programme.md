# 0019 — The project is two parallel tracks, not one with a side-quest

**Date:** 2026-08-18
**Decided by:** Owner, correcting my structure
**Status:** ACTIVE

## Context
The owner's original brief had two halves: institutional flow, and "the 31
million combinations". I built the entire discipline framework around the first
and reduced the second to config entries, two decision records, and one paragraph
of prose. **Zero lines of code served it.**

In the HOD report I listed it as "Study 4 of 4", last. The owner's objection —
*"where the heck you placed that?"* — was correct.

## Decision
Two co-equal tracks running in parallel:

- **Track D** — institutional deal event studies. Machinery built.
- **Track S** — mass pattern search, calendar and signal combinations. To build.

They share registration, decision records, multiplicity and hashing. They do not
share `split.py` or `power.py`, both of which are event-study specific.

## Why
`split.py` partitions by ISIN, which is meaningless for a calendar cell.
`power.py` collapses to monthly cohorts, which does not apply to observations
that occur once a year. The overlap between the tracks is the governance layer,
not the statistics.

Track D pauses nothing: its machinery is finished and idle, so building Track S
next wastes none of it. Owner chose parallel operation.

## What would reverse this
Track S's procedure test returning a hit rate at chance AND Track D failing its
portfolio gates, in which case both tracks are done and the project reaches its
kill criterion ([0010](0010-project-kill-criterion.md)) rather than being
restructured again.

## Cost accepted
Two tracks at 2–3 h/day means both advance at half speed against a 2027-02-28
deadline. Accepted by the owner explicitly.
