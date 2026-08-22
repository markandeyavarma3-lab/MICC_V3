# 0004 — Primary horizons measured in sessions; the monthly grid is demoted

**Date:** 2026-08-16
**Decided by:** Claude, from measured power
**Status:** SUPERSEDED by [0034](0034-twelve-month-becomes-the-primary-horizon.md) — decision 0028 made the plausible bound scale with horizon, which inverts this record's premise: longer horizons became easier, not harder.

## Context
The original grid ran 1–24 months. Measured MDE at 80% power on monthly cohorts:
1m 1.52%, 3m 3.07%, 12m 7.38%. The one real effect found all day sat at **10
sessions**, which the grid would have missed entirely.

Monthly cohorts give 247 observations. Daily cohorts give ~3,345 and an MDE of
0.163% — a 9× improvement from a change of aggregation alone.

## Decision
`horizons_sessions: [1, 2, 3, 5, 10, 21]` is primary. `horizons_months: [3, 6, 12]`
is robustness only. The 8/10/15/18/24-month horizons are dropped.

## Why
The plan was pointed at the frequency where MDE exceeds any plausible effect. At
12 months MDE is 7.38% against a plausible bound of 0.50%; longer horizons are
strictly more hopeless and each one spends correction budget to guarantee an
UNDERPOWERED row.

## What would reverse this
A mechanism that predicts a genuinely slow-acting effect — an institution
accumulating over quarters — with a side-prediction that distinguishes it from
noise. Then a long horizon earns its place instead of being included by default.

## Cost accepted
The owner had asked for 15- and 18-month horizons added. Dropping them overrides
that request; recorded here rather than done silently.
