# 0021 — The pooled market-relative average is undefined, not merely weak

**Date:** 2026-08-18
**Decided by:** Claude, correcting my own error from earlier the same day
**Status:** ACTIVE — supersedes the reasoning in [0020](0020-market-relative-is-mandatory.md)

## Context
Decision 0020 and the first version of `PLAN_4_SCAN.md` reported this table and
built a plan on it:

| Basis | Mean pairwise ρ | n_eff of 21,000 | MDE/yr |
|---|---|---|---|
| PRICE (raw) | +0.2350 | 4.3 | 33.95% |
| MARKET_RELATIVE | +0.0001 | 6,694.1 | 0.86% |

concluding that removing the market factor multiplies effective sample size by
~1,550×. The owner asked "are you sure about the whole thing?", which prompted
the check that should have come first.

**Two errors, the second larger.**

**Error 1 — the ρ was an artifact.** Subtracting the cross-sectional mean forces
mean pairwise correlation to −1/(N−1) regardless of the input. Verified against
simulated controls:

| Input | Raw ρ | After demeaning |
|---|---|---|
| pure independence, N=657 | −0.00003 | −0.00148 |
| strong market factor, N=657 | **+0.4035** | −0.00145 |
| theoretical −1/(N−1) | — | −0.00152 |

A statistic that returns the same value for a 0.40-correlated panel and an
independent one is measuring the operation, not the data.

**Error 2 — the estimator has no content.** If market-relative means "minus the
cross-sectional mean", the cross-sectional mean *of* market-relative returns is
identically zero. Measured on 656 stocks × 2,870 sessions, the largest absolute
value on any day is **1.698 × 10⁻¹⁷**.

So "is trading day 47 good on average, market-relative?" cannot return a non-zero
answer for any day, ever. I had written a plan around an estimator incapable of
producing a number.

## Decision
1. The pooled *average* of market-relative returns is **FORBIDDEN** in config —
   flagged `pooled_average_of_market_relative: FORBIDDEN_IDENTICALLY_ZERO`.
2. The **cross-sectional rank IC is mandatory**, not preferred. It is the only
   surviving estimator.
3. **The unit of evidence is the date, not the stock-year.** Each date gives one
   IC observation however many stocks it ranks. Pooling stocks buys precision
   within a date and buys no additional dates. The "21,000 stock-years" figure
   was always a mirage.
4. Power is measured on the IC directly. Measured: sd 0.1190 across 568
   observations, SE 0.0050, **MDE on mean IC 0.0140**.

## Why
0020's conclusion — market-relative, cross-sectional — was right, and is now
right for a much stronger reason. It was presented as the best of several
options. It is the only option, because the alternatives are respectively dead
(raw pooling, n_eff 4.3), impossible (per-stock, 2 observations) and undefined
(pooled market-relative average).

The MDE floor of ~0.014 against typical real signal ICs of 0.02–0.05 means this
estimator can actually see something. That is the single fact that makes Track S
worth building.

## What would reverse this
A market definition **external** to the ranked universe — a published index
rather than the cross-sectional mean of the same stocks. Then the pooled average
is no longer identically zero and becomes a legitimate, if weak, second
estimator. Worth testing; it does not change the primacy of the IC.

## Cost accepted
Any pattern whose whole content is "the entire market rises on day 47" is
invisible by construction. That is the correct trade: such a pattern has 21
observations and was never detectable.

**And a process cost worth recording.** This error survived a config file, a
900-line plan document, two decision records and a commit message, and was caught
only because the owner asked whether I was sure. Rule 1 — no design element
without a computed number beside it — was satisfied in form: there *was* a number.
Nobody checked whether the number could distinguish the hypothesis from its
negation. That check is now part of the rule.
