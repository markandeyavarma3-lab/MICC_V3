# 0038 — No horizon survives any defensible participation cap

**Date:** 2026-08-30
**Decided by:** Owner asked for the cap to be challenged before accepting the
result. It was. The challenge failed.
**Status:** ACTIVE — supersedes [0034](0034-twelve-month-becomes-the-primary-horizon.md)

## Context

[0034](0034-twelve-month-becomes-the-primary-horizon.md) made twelve months the
primary horizon on a measured MDE of 5.5572% against a 6.00% bound — the only
horizon in the grid that reached its own bound.

That measurement had no size ceiling. Plan 2 §4.4 requires one: participation is
capped at a fraction of ADV per session, and *"where the position cannot be built
inside 5 sessions, the event is marked `TOO_LARGE` and excluded with the reason
recorded."* `costs.yml` sets 10% per session over 5 sessions, so **50% of ADV20**
is the largest position buildable. The mart had a floor and no ceiling, so
14,747 of 20,489 eligible events — **72%** — were positions nobody could
establish. One traced row was 204x ADV.

The owner declined to accept the consequence without first testing whether the
cap itself was the problem. Measured 2026-08-30, twelve-month horizon, bound
6.00%:

| participation assumption | ceiling | n | cohort SD | MDE | verdict |
|---|---:|---:|---:|---:|---|
| 10% × 5 sessions (`costs.yml`) | 0.50x | 4,750 | 37.09% | 13.3038% | 2.22x short |
| 20% × 5 sessions | 1.00x | 6,595 | 55.08% | 13.0895% | 2.18x short |
| 10% × 10 sessions | 1.00x | 6,595 | 55.08% | 13.0895% | 2.18x short |
| 20% × 10 sessions | 2.00x | 8,692 | 36.38% | 9.0805% | 1.51x short |
| 50% × 10 sessions | 5.00x | 11,470 | 27.55% | 7.1653% | 1.19x short |
| **no ceiling at all** | — | 17,705 | 19.22% | **5.2803%** | **POWERED** |

## Decision

**No Track D horizon is registrable.** The twelve-month result is withdrawn as a
powered horizon, and 0034 is superseded.

## Why

The table answers the challenge and the answer is not close. **The POWERED
verdict requires no ceiling at all** — not a generous cap, the absence of one.
Even 50% of ADV per session sustained over ten sessions, which is a five-times-ADV
position and far past anything `costs.yml` or the literature would defend, is
still 1.19x short.

So the earlier verdict did not depend on a debatable threshold. It depended on
assuming a position of unlimited size could be established instantly, which is
not an execution assumption at all.

The power was borrowed from events nobody could trade, and the mechanism is
arithmetic rather than a change in the data's character. The excluded deals have
a median 436.8% of ADV against 14.6% for those kept, at similar rupee value
(₹109.5M vs ₹141.5M) — so they were not larger deals, they were deals in
**thinner stocks**. Removing them leaves 3.5x fewer events per monthly cohort,
and a cohort mean of *k* events is ~1/√k noisy: 19.2% × √3.5 = 35.8% against
37.1% observed.

**A fragility worth recording.** Cohort SD is not monotone in the ceiling —
37.09%, then 55.08%, then 36.38%, 27.55%, 19.22%. A sample whose dispersion
swings that way as a threshold moves is one where a handful of extreme
observations carry real weight, which is an additional reason not to trust a
verdict that only appears at the permissive end.

## What would reverse this

Genuinely more independent evidence, not a looser assumption: a real listing-date
source recovering the MEDIUM-graded events, characteristic matching that reduces
dispersion rather than adding sampling noise, or a study whose events are
naturally tradable — small deals in liquid names, which is what the 5,742
survivors already are.

## Cost accepted

- **Phase 6 cannot register anything as specified.** `design.py` refuses a study
  whose horizons are all blind, and all of them now are. The project's central
  question is currently unanswerable at any horizon it declares.
- The project's honest position weakens from *"an effect that takes a year to
  appear"* to *"we cannot tell at any horizon"*. That is a worse headline and a
  truer one, and it is the outcome Plan 2 §10 named as most likely from the
  start.
- Four days of work — the ceiling, the pipeline, the identity layer — went into
  removing a result rather than producing one. That is what the machinery is
  for, but it should be said plainly rather than presented as progress.
- The 5,742 tradable events remain, and they are a narrower and more answerable
  question than the one originally asked. Pursuing that requires a fresh
  pre-registration with its own mechanism and side-predictions, not a
  re-labelling of this one.
