# 0085 — exp_005 registered: does a wide signal search work on 2016+?

**Date:** 2026-10-03
**Decided by:** Owner ("yeah lets start", twice: approving the draft and its
four owner decisions, then the registration after the rehearsal).
**Status:** accepted. exp_005 is REGISTERED (spec_hash `96cffcb539f7…`,
commit `59e5e1b`). The CONFIRM run started 2026-10-03 13:14 IST.
**Related:** Plan 4 §4 and §9; 0084 (the statistic); 0083 (the participant
layer the deal signals still key on raw); draft
`docs/plan/EXP005_SCAN_PROCEDURE_REGISTRATION_DRAFT.md` revision 2.

## What was fixed before any 2016 IC existed

- **Folds.** 11 disjoint yearly test windows from 2016, with anchored
  training from 2005 and a 21-session embargo. All 11 are independent.
  Exploration had about 3.
- **The search.** 1,929,213 candidates: 143 base signals to depth 3, scored
  as in 0084. Selection takes the top 1, 10 or 100 by |mean train IC|, and
  the test is read in the training sign.
- **The null.** Block sign flips, 1,000 reps, seed 20261002. One-sided p,
  with Benjamini–Hochberg across the three N at 5%.
- **Attribution.** The same procedure on the partial IC net of hi_252 and
  downvol_126, the two factors exploration found the search selecting.
- **Costs.** Selected sets as long–short books (top/bottom 20%, monthly,
  ₹100 crore) at the pessimistic costs.yml level.
- **The verdict ladder:**
  - NO_SEARCH_SKILL
  - REDISCOVERS_KNOWN_FACTORS
  - SIGNIFICANT_BUT_UNPROFITABLE
  - SEARCH_FINDS_NEW_EDGE
- **The expectation, recorded:** REDISCOVERS_KNOWN_FACTORS.

## The rehearsal that preceded it (2005–2015, free data)

The rehearsal used six disjoint yearly folds (2010–2015) and gave
REDISCOVERS_KNOWN_FACTORS:

- **Primary:** 6/6, q 0.018.
- **Partial:** 5/6, q 0.11.
- **Net:** +1.5% per monthly rebalance.

It found two run-time defects, both fixed with identical results before
registering. Partial selection with a shared null pass made the null about
10× faster. A factor-column gather with batched matmul cut the attribution
step from an estimated 66 h to 7 min.

## Cost accepted

- **The confirmation data is spent.** 2016 onward has now been tested once.
  Any later hypothesis about searching on this data, the factor-neutral
  residual included, can only be confirmed on years not yet seen.
- **The attribution factors came from exploration.** They are the right two
  for the question asked, but a different pair would give a different
  partial row.
- **The cost check is an average across selected books**, not one tradable
  strategy. With no selection skill it describes the years, not a rule.

## What would reverse this

Nothing reverses a registration. A defect found in the CONFIRM run is
reported in its report with its effect, and a corrected analysis would be a
new experiment that pays its own family.

## Result (2026-10-03, run `9f95f95c68f2a962`, recorded write-once)

**NO_SEARCH_SKILL.**

- **Primary:** hit rates 0.73 / 0.73 / 0.82 for the top 1 / 10 / 100, with
  q 0.114 / 0.114 / 0.111. No N passes.
- **Out of sample:** test IC about +0.05 against train +0.09; rank decay
  0.40; PBO 0.27.
- **Partial (factor-neutral) procedure:** 10/11, q 0.009. This is
  significant but cannot override the ladder's order. It is recorded as a
  candidate hypothesis for a future registration, not a finding.
- **Costs:** +0.8–0.9% net per monthly rebalance.

The expectation (REDISCOVERS_KNOWN_FACTORS) was wrong in an informative way:
the plain search weakened after 2016 by more than expected. See
docs/reports/SCAN_CONFIRM_H21.md.
