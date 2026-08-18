# 0026 — Validate the seasonality atlas instead of rebuilding it

**Date:** 2026-08-18
**Decided by:** Owner, reversing their own [decision 0006](0006-seasonality-full-rebuild.md)
**Status:** ACTIVE — supersedes 0006

## Context
Decision 0006 chose a **full 31.9M-cell rescan** (~3 weeks) over validating the
predecessor's existing atlas (~1 week). The owner made that call against my
recommendation, and the reasoning was sound: independent confirmation, and clean
provenance through the DAG rather than trusting the predecessor's output.

Two days later the schedule rewrite ([decision 0025](0025-critical-path-schedule.md))
measured the plan honestly for the first time: **1.7 weeks of slack** against the
2027-02-28 deadline, on a project where every estimate so far has been wrong. A
25% overrun missed by five weeks.

Phase 7 was the single largest cut available.

## Decision
`rebuild_mode: validate_existing_atlas`. Phase 7 drops from 3 weeks to 1.

## Why the case is stronger now than when 0006 was made
- The predecessor **already ran this scan**, and its own verdict was that the
  best pattern sits at the **94th percentile of rotated noise** — an ordinary
  result of looking 31.9 million times.
- The corrected fee schedule then killed both surviving effects: turn-of-month
  goes from **+3.70 to −6.36 bps** net.
- So a rebuild spends two weeks re-deriving a known negative, and those two weeks
  are exactly what the critical path needs for buffer.

## What validation must still do — this is not "trust the old numbers"
1. **Recompute a 100,000-cell sample** (~0.3%) from scratch with new code.
   **Exact match required**; these are deterministic counts, so any tolerance
   would be hiding something.
2. **Escalate automatically on mismatch.** A sample that does not reproduce means
   the atlas cannot be trusted as input, and Phase 7 reverts to the full 3-week
   rescan. That branch is paid for in the cut order by dropping monitoring.
3. **Treat the atlas as INPUT DATA, not as a result.** Everything downstream is
   computed fresh with current machinery: the measured rotation null, the Track S
   walk-forward folds, and the simulated bar on the actual grid geometry
   ([0022](0022-multiplicity-had-three-errors.md)).

Point 3 is what makes this defensible. The predecessor's *cell counts* are cheap
to verify and expensive to recompute. Its *statistical conclusions* are neither
trusted nor reused — they are replaced.

## What would reverse this
The 100,000-cell sample failing to reproduce, which reverts Phase 7 to a full
rescan by the escalation rule rather than by a new decision. Or the critical path
landing early enough that three weeks becomes affordable again.

## Cost accepted
**Independent confirmation is given up.** If the predecessor's atlas contains a
systematic error that happens not to appear in a 100,000-cell sample, this
project inherits it. That risk is accepted in exchange for two weeks, and the
sample size is stated here so the exposure is explicit rather than implied.

It also means one of the project's stated goals from 0006 — clean provenance for
every seasonality cell through the DAG — is only partially met. The validated
sample gets full provenance; the remaining 99.7% carries a documented dependency
on MICCV2's run of 2026-08-13.
