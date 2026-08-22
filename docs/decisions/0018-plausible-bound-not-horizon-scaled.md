# 0018 — OPEN DEFECT: the plausible bound is not horizon-scaled

**Date:** 2026-08-17
**Decided by:** Not yet decided — raised by Claude, awaiting the owner
**Status:** SUPERSEDED by [0028](0028-plausible-bound-scales-with-horizon.md) — the owner chose the **rate view** on 2026-08-21

## Context
`configs/research.yml` carries a single `plausible_effect_bound_monthly: 0.005`,
and the `UNDERPOWERED` rule compares **every** horizon's MDE against it.

That comparison is only dimensionally valid at roughly 21 sessions. Judging a
1-session MDE against a *monthly* bound is a unit error, and it currently makes
short horizons look powered when they may not be.

| horizon | MDE corrected | vs fixed 0.5% | vs scaled bound |
|---|---|---|---|
| 1s | 0.191% | detectable | bound 0.024% → **UNDERPOWERED** |
| 5s | 0.423% | detectable | bound 0.119% → **UNDERPOWERED** |
| 10s | 0.660% | UNDERPOWERED | bound 0.238% → UNDERPOWERED |
| 21s | 0.968% | UNDERPOWERED | bound 0.500% → UNDERPOWERED |

## The decision required
Which model of the effect applies:

- **Event view** — disclosure causes a one-off repricing, so the effect is fixed
  regardless of horizon and a single bound is correct. "Per month" is then a
  misnomer and should read "per event".
- **Rate view** — skill is persistent, so the effect accrues per unit time and
  the bound must scale with horizon. Under this reading **every horizon becomes
  UNDERPOWERED**, including the two currently marked detectable.

## Why it is not being decided unilaterally
It determines whether this project can conclude anything at all at short
horizons, and the honest answer under the rate view is that it cannot. That is
the owner's call, not a default I should pick while building — which is the same
failure recorded in [0011](0011-plausible-effect-bound.md), where a number of
mine sat in a config for a day looking like a measurement.

## What would reverse this
n/a — the record closes when the decision is made, and is superseded by the
record that makes it.

## Cost accepted
Until decided, every `UNDERPOWERED` verdict at a non-21-session horizon carries
an asterisk and should not be quoted as final.
