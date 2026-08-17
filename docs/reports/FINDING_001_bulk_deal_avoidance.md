# Finding 001 — Bulk-deal avoidance filter: REJECTED

**Experiment:** `exp_001_bulk_deal_avoidance_filter`
**Spec hash:** `7072f730dcca586844e667dcd4e909d947a7962003911a3808ba2b468e84a0ab`
**Registered:** 2026-08-16, commit `f25608d` — *before* the test ran
**Verdict:** **REJECTED** by its own pre-registered rule
**Trial counter at registration:** 171

The governance store (`db/governance_prod.sqlite`) is gitignored, so this file is
the version-controlled record of the result. Two `study_result` rows exist in the
ledger, write-once verified.

---

## The result

| Holdout | Annualised diff | t | Bootstrap 95% CI | P(diff>0) | Verdict |
|---|---|---|---|---|---|
| FIT half of names | **+0.237%/yr** | +3.11 | [+0.089%, +0.386%] | 99.9% | **FAIL** |
| TEST half (holdout) | **−0.022%/yr** | −0.25 | [−0.193%, +0.150%] | 40.3% | **FAIL** |

The pre-registered bar: **> +0.25%/yr AND a bootstrap CI excluding zero, in both
holdouts.** It failed narrowly in the fit half and completely in the holdout. The
bar was not rewritten after the result was seen.

The forward-only holdout is now moot and will not be run.

---

## What was tested

> A long-only equal-weighted top-500 book that **excludes** names with a
> disclosed bulk-deal BUY in the trailing 10 trading sessions earns a higher net
> return than the identical unfiltered book.

Monthly rebalance, equal weight, point-in-time top-500, delisting-aware. Paired
difference against the same book unfiltered, so market and style exposure cancel.
2011 onward — the 2006–2010 events were excluded at registration because that era
returns NaN, indicating at least one bad price.

## Why it died, which matters more than that it died

The **event-level effect was real** and survived two controls designed to kill it:

| Control | Result |
|---|---|
| Random stocks, same dates | Event −0.898% vs random −0.039% at 10d → **−0.860% event-specific** |
| Volatility-matched peers | Event −1.079% vs peers −0.274% → **−0.805%, t −3.93** |
| Momentum reversal | Rejected — corr(pre-21d, forward-10d) = **+0.008**, quintiles U-shaped not monotonic |

And yet the portfolio filter does nothing. The reason is dilution: **the filter
excludes only 1.2% of names at any time.** Roughly 302 qualifying events a year
across a 500-name universe, each tainting one name for 10 sessions, is about six
names. A −0.8% effect on 1.2% of a book is ~1 basis point a month.

**A genuine event effect and a useless portfolio signal are entirely compatible.**
Nothing in the event study revealed that — every statistic there was correct and
pointed the right way. Only constructing the actual book did. That is the single
most useful thing learned today, and it generalises: an event study is not a
strategy test, and the gap between them is not a detail.

## An error in my own bar-setting, recorded rather than quietly fixed

At registration I derived the expected benefit as ~0.49%/yr, assuming the filter
would exclude ~2.4% of names. Actual exclusion is **1.2%** — half that — so the
true expected benefit was ~0.25%/yr. The bar I described as "half the expected
effect" was in fact **the full expected effect**, making it harder than I
intended.

It changes nothing: the holdout came in at −0.022% with t = −0.25, which fails any
bar above +0.10%. But the mis-derivation is recorded because a bar that was
wrong-by-accident and happened to reject is still a bar that was wrong.

## Context: what this cost, and what it was worth

The effect was found in an **unregistered exploratory search of ~100 cells** on
2026-08-16 — 4 event sets × 5 horizons × 4 liquidity tiers, plus controls,
quintiles, and era splits. That search is logged in `trial_counter` as its own
episode, which is why `trials_before` is 171 rather than 69.

At that search scale, a single winner at t = −3.93 is around what noise produces.
The stock-split holdout is what separated the two, and it took about ninety
minutes from first sighting to recorded death.

**The sequence that made this trustworthy:** register → commit → test → record.
The registration commit `f25608d` precedes the result in git history, and the
spec-freeze trigger was verified by attempting to edit the pass bar and being
refused. A registration committed after its result is unfalsifiable regardless of
what it says.

## What this does not close

- **Institutional SELLING** (34,270 events) — still unexamined
- **Consensus** (10,098 events at 3+ institutions / 21 sessions) — unexamined
- **Block deals** as a separate study — unexamined
- Whether the event effect is exploitable in a form other than a 500-name
  avoidance filter — e.g. a concentrated short in the ~210 single-stock-futures
  names, which was ruled out on implementability rather than on evidence

None of those are made more promising by this result. They are simply still open.

## The honest summary

A real, controlled, event-level abnormal return of −0.8% over 10 sessions exists
after bulk-deal buy disclosures in the top 500. It is **not tradable as a
portfolio filter**, because it touches too few names to matter. Reported as a
finding rather than buried, because the negative is the deliverable.
