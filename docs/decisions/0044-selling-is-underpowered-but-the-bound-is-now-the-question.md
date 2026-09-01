# 0044 — Selling is underpowered too, and the plausible bound is now the question

**Date:** 2026-09-01
**Decided by:** Mine — a measurement and a stop, not a finding
**Status:** ACTIVE

## Context

[0038](0038-no-horizon-survives-a-participation-cap.md) found no registrable
bulk-buy horizon; [0043](0043-consensus-is-not-registrable-either.md) found none
for consensus. Selling was the last of the four with the event count to
plausibly clear the bar — 4,306 tradable events against consensus's 1,064.

**I projected it would be POWERED at 5.787% and I was wrong.** The projection
assumed cohort SD would fall as 1/√n. It fell from 58.17% to 40.07%, a factor of
1.45 rather than the 2.0 assumed, because the cohort count barely moved (223 to
232) and it is cohorts, not events, that the MDE turns on. Recording the failed
projection because it was stated before the measurement and a project that only
records its correct predictions is not measuring anything.

## What was measured

Sells, same filters as the buy side, market-relative, monthly cohorts, serial
lag covering the label overlap:

| horizon | n | cohorts | cohort SD | MDE | bound | verdict |
|---|---:|---:|---:|---:|---:|---|
| 21s (1m) | 4,126 | 243 | 12.43% | 2.7037% | 0.50% | 5.41x short |
| 63s (3m) | 4,080 | 242 | 19.53% | 4.9533% | 1.50% | 3.30x short |
| 252s (12m) | 3,626 | 232 | 40.07% | 11.7047% | 6.00% | **1.95x short** |

**No horizon is registrable. All four studies are now out.**

## The part that stops this being a simple negative

A null calibration on 2,509,559 stock-dates over the same sessions:

| | mean | median | hit rate |
|---|---:|---:|---:|
| **null** | −0.00% | −11.28% | **32.0%** |
| buys | −14.51% | −19.50% | **33.0%** |
| sells | −23.80% | −32.36% | **24.0%** |

The null mean is exactly zero, as [0021](0021-pooled-average-is-undefined.md)
implies it must be — the cross-sectional mean of a demeaned panel over *all*
stocks is identically zero. A subset may deviate, and that is what makes the
comparison meaningful rather than circular.

**Buys match the null hit rate (33.0% against 32.0%).** That is the 2026-08-16
audit's "right skew, not edge", confirmed on a different pipeline.

**Sells do not: 24.0% against 32.0%.** The hit rate is distribution-free, so it
does not inherit the right-skew problem that makes every mean here look terrible
— the universe's own 12-month returns have a mean of 25.62% against a median of
3.57%, a 22-point skew gap.

An obvious confound was checked and does not obviously explain it: sold names'
prior 12-month market-relative return has a **mean of +1.15%**, so this is not
institutions selling after a run-up and the market reverting.

## Decision

**Stop here and register before going further.** Nothing above is a finding and
none of it may be reported as one. [0002](0002-preregistration-before-results.md)
requires the spec frozen first, and every number in this record was produced by
looking at outcomes without one.

The finding that IS available is this: **the observed effect is 4x the
pre-registered plausible bound.** MDE 11.70% against a bound of 6.00% reads
"underpowered" — but the effect on the table is 23.80%. A study cannot be
underpowered for an effect it is measuring at twice its own detection floor.

So exactly one of these is true, and both are owner decisions:

1. **[0011](0011-plausible-effect-bound.md)'s bound of 0.5%/month is
   miscalibrated for this event class.** It was set as a plausible bound for a
   disclosed-information edge; nothing measured it. If a real effect here is
   ~2%/month, every UNDERPOWERED verdict in this project needs recomputing.
2. **The sell result is confounded** by something the checklist in
   `confounds.yml` covers and this measurement did not: size, sector, delisting
   recovery, era, or time concentration.

## What would reverse this

A registered sell study running the full `confounds.yml` checklist and either
surviving it — in which case option 1 is live and the bound must be revisited on
the record — or failing it, in which case option 2 is the answer and Selling
joins the other three.

## Cost accepted

- **This record contains exploratory numbers, which is a cost, not a benefit.**
  They are here because deleting them would be worse — a future registration
  must disclose that the outcome was seen first, exactly as the bulk-buy
  registration must disclose the 2026-08-16 audit.
- **Survivorship cuts the conservative way and is still unquantified.** A
  delisted stock has no 252-session forward close and is dropped, so the −23.80%
  is measured on survivors only. If sold names delist more, the true figure is
  worse — but "unquantified" is the honest word.
- **The momentum check used the mean and the median disagrees.** Prior
  market-relative return is +1.15% on the mean and −22.80% on the median against
  a null median of −11.28%, so the typical sold name was already weak. That is
  not resolved here.
- **Three of the four studies are now measured and none is registrable.** The
  remaining route to 0010's deadline is Blocks, which has the cleanest data and
  the fewest events.
