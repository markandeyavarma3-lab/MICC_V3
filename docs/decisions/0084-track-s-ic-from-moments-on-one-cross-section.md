# 0084 — Track S scores every candidate on one cross-section, from moments

**Date:** 2026-10-02
**Decided by:** Owner ("start building the next ones"), building Plan 3
step 6S.6. The statistic below is fixed before any candidate has been scored
on real data. Every earlier benchmark run ended before scoring one.
**Status:** accepted
**Related:** 0021 (the pooled average is undefined; rank IC is the only
estimator), 0022 (multiplicity), 0023 (trial families), Plan 4 §5 and §10.

## Context

scan.yml requires that a benchmark on 1/1000th of the grid project the full
run inside 21 days before any full run. The grid is 143 base signals combined
to depth 3: 1,929,213 candidates. The first scorer re-ranked two
(sessions × names) arrays per candidate, so the 0.1% sample did not finish in
an hour, which puts the full grid at over a month. Most of that work was the
same each time: the forward return was re-ranked for every candidate.

## Decision

1. **One cross-section per date for every candidate.** On session t, J_t is
   the names in the point-in-time top 500 that have a forward return and
   every base signal defined. No candidate is scored on an easier or larger
   set of names than another on the same date. With fewer than 100 names
   (scan.yml `min_names_per_date`) there is no IC that date.
2. **The statistic.**
   - **Depth 1:** the Spearman correlation of the signal and the forward
     return on J_t, with average ranks for ties.
   - **Depth 2–3:** the Pearson correlation of the mean of the components'
     signed percentile ranks with the forward return's percentile rank on
     J_t. This is the standard rank-composite IC. It is not the Spearman of
     the composite, which would re-rank it per candidate; the difference is
     the cost removed here, and it is the same for every candidate of a
     depth.
3. **Computed exactly from per-date moments** (`src/scan/fastic.py`). The
   centred base ranks' cross-products (K×K), their products with the
   return's ranks, and the return's own sum of squares are built once per
   date. Each candidate's IC is then O(d²) per date. Tests check it against
   direct computation, to 1e-5, on data with ties, missing values and a thin
   date.
4. **Only names ever in the universe become columns**, and the rolling cache
   is cleared after each signal. Holding every rolling array for all 143
   signals would not fit in memory.

## Measured on the explore panel (2026-10-02)

The panel is 2,716 sessions × 1,979 securities (2005–2015), with a universe
mean of 453 names. Preparation takes 14 s once; **each candidate takes 0.1
ms**. The full depth-3 grid is projected at minutes for EXPLORE and about
twice that for CONFIRM, against a 21-day budget. The direct scorer's 0.1%
sample did not finish in an hour, so the speed-up is roughly 20,000×.

| | J_t, median names | dates with an IC |
|---|---:|---:|
| 2005–2006 | 0 | 0 — warm-up (252-session and 2-year lookbacks) |
| 2007 | 262 | 246 of 249 |
| 2010 | 374 | 251 of 251 |
| 2015 | 374 | 225 of 247 — the last 22 sessions' forward windows would reach 2016, which stays sealed |

## Cost accepted

- **The common cross-section drops names.** A name missing any one of 143
  signals on a date (a recent listing inside a 252-session lookback, say) is
  out for every candidate that date, including those that do not use the
  missing signal. Comparability is bought with coverage.
- **Depth 2–3 is a composite IC, not a re-ranked Spearman.** The two differ
  little when the composite is near-uniform, and the procedure test compares
  candidates within a depth on the same footing either way.

## What would reverse this

- A benchmark showing the direct re-ranked Spearman fits the budget, through
  faster hardware or a cut grid. The definition could then move back, with a
  new decision, before a CONFIRM run is registered. It must never move after
  one.
- Evidence that J_t is materially smaller than the universe on many dates.
  The floor would then be revisited, with the count of affected dates in the
  decision.
