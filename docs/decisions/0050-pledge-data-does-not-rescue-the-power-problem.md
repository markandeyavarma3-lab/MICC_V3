# 0050 — Pledge disclosures do not rescue the power problem, and 0046's numbers are now reproducible

**Date:** 2026-09-03
**Decided by:** Owner asked whether the pledge categories in the insider seed
were an untested angle; measured.
**Status:** ACTIVE

## Context

0046 measured promoter buy and sell power on `insider_trading.parquet` and
reported the figures from an ad-hoc shell run that was never committed as code
— the same "analysis code was never committed" defect PLAN_3 §6R records about
exp_001. The owner then asked, in a brutal-honesty review of the whole data
inventory, whether more extraction could close the power gap on the three
already-failed studies (bulk buys, consensus, selling), and specifically
flagged the `Pledge` / `Pledge Revoke` / `Pledge Invoke` transaction types as an
unmeasured 29,109-row population sitting in the same table.

## What was built

`src/research/insider_power.py` — power only (0035: no effect estimate),
promoter-category-only (`Promoters`, `Promoter Group`), filtered on `value > 0`
because quantity is unreliable (128 of 14,148 Pledge rows have qty > 0 against
13,698 with value > 0, the same defect 0046 found on ordinary sells). Five
populations, three horizons, fixed at `measure.REPRODUCIBILITY_HORIZON`.

## The measurement

| population | 12m n | 12m cohort SD | 12m MDE | verdict |
|---|---:|---:|---:|---|
| promoter buy | 24,835 | 23.35% | 9.0728% | 1.51x short |
| promoter sell | 12,829 | 22.64% | 7.5268% | 1.25x short |
| pledge | 5,594 | 27.11% | 13.6390% | 2.27x short |
| pledge revoke | 4,134 | 24.60% | 11.0364% | 1.84x short |
| **pledge invoke** | **958** | **49.70%** | **27.3046%** | **4.55x short** |

Promoter buy and promoter sell reproduce 0046 exactly — n and MDE to four
decimal places, confirming the ad-hoc run was correct and is now a committed,
re-runnable module rather than a number someone has to trust.

## Decision

**Pledges do not open a new path.** All three pledge populations are worse
powered than promoter sell, which was already the closest thing in the project
to a registrable study and is itself not close.

## Why

`Pledge Invoke` — a lender foreclosing on a promoter's collateral — was the
economically interesting candidate: it is the closest thing in this dataset to
genuine forced selling by a party other than the promoter, comparable in kind
to the reasoning that put Selling ahead of Bulk Buys in 0031. If pledges were
going to rescue anything, it would be here.

It is instead the **worst-powered population measured in this project**: n=958
against promoter sell's 12,829 (13x fewer events), and a cohort SD of 49.70%
against 22.64% — the smallest, noisiest population found. `Pledge` and `Pledge
Revoke` are larger but still worse than promoter sell on both counts, because
the events that qualify (promoter/group only, value > 0) are simply less
common than sales.

The honest reading: a lender invoking a pledge is a **rare, already-late**
event — by the time a lender forecloses, the promoter's distress is usually not
news, and the market has likely already priced whatever information the
pledge itself carried. Small n and large dispersion together are what a
population made of only the most acute cases looks like.

## What would reverse this

Nothing found here. This closes the pledge question rather than opening a new
line — the remaining live question is 0044's, whether the observed 23.80% sell
effect means the plausible bound is miscalibrated, not whether more data
sources exist to try.

## Cost accepted

- **Five more populations now exist for the trial counter to eventually
  charge**, on top of the four studies and the promoter buy/sell pair 0046
  already added. `family_charge` is still 0 rows; this makes the eventual
  reckoning larger, not smaller.
- **`Pledge Invoke`'s n=958 is thin enough that its MDE is itself noisy** — a
  small change in filter (e.g. relaxing the value floor) could move the
  multiplier meaningfully. The verdict (worst-powered, not close) is robust to
  that; the exact 4.55x is not a number to defend to two decimal places.
- **This does not settle whether OTHER unloaded seed tables hold a better
  population.** It settles pledges specifically, because that was the question
  asked.
