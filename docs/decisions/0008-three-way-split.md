# 0008 — Three-way EXPLORE / SELECT / CONFIRM partition

**Date:** 2026-08-17
**Decided by:** Claude; Owner instructed "choose which gives the best output"
**Status:** ACTIVE

## Context
On 2026-08-16 an unregistered exploratory search of ~100 cells moved the trial
counter from 68 to 171. Under a single-pool regime that cost is permanent and
global: every future study's bar is higher forever because of one afternoon.

## Decision
30% EXPLORE (free, uncharged, unregistered), 20% SELECT (charged; where candidates
are compared), 50% CONFIRM (registered experiments only, one touch each).
Deterministic sha256 assignment, enforced by `ConfirmationGuard`.

## Why
Charging full price for looking makes examining your own data expensive, so you
examine it less, so you find less. The fix is not to look less — it is to have
somewhere that looking is free.

Three strata rather than two because *finding* a hypothesis and *choosing among
candidates* are different expenditures. MICCV2's champion was not mined into
existence; it was SELECTED from a factory, and the selection was never charged for.

## What would reverse this
Measured leakage so severe that CONFIRM provides no real independence — see
`effective_sample_size`. If n_eff/n falls below 0.10 the partition is buying less
than it costs, and a time-based split would be the alternative.

## Cost accepted
Half the universe carries the statistical burden, so every CONFIRM MDE is worse
than a full-sample MDE by roughly √2. Measured on real data: CONFIRM holds 122,994
deal rows across 1,930 names and 247 months.
