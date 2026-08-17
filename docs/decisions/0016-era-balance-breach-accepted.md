# 0016 — The split's era-balance breach is disclosed, not re-drawn

**Date:** 2026-08-17
**Decided by:** Claude, following `configs/split.yml on_breach`
**Status:** ACTIVE

## Context
The partition passes on names (within 0.3pp of target) and on deal type (worst
deviation 0.030), but **breaches on era**:

| era | EXPLORE | SELECT | CONFIRM |
|---|---|---|---|
| 2006-11 | 0.280 | 0.149 | **0.571** |
| 2012-16 | 0.313 | 0.173 | 0.513 |
| 2017-21 | 0.318 | 0.173 | 0.509 |
| 2022-26 | 0.307 | 0.188 | 0.505 |

Targets are 0.30 / 0.20 / 0.50. Worst deviation **0.071** against a 0.05 limit,
driven by 2006-11.

## Decision
Record it as a stated limitation. Do not re-draw.

## Why
Re-drawing until the split looks balanced is p-hacking the split itself. The
assignment is a deterministic hash of the ISIN; the only way to "improve" it is to
try keys until the imbalance disappears, which optimises the partition against the
very data it is meant to hold out.

The cause is mechanical: deal rows per name vary enormously, and in the thin
2006-11 era a few heavily-traded names happened to land in CONFIRM.

## What would reverse this
Nothing about the split. If era imbalance materially affects a specific result,
the correct response is an era-stratified sensitivity run on that result, reported
alongside it.

## Cost accepted
Early-era analyses have less EXPLORE data than nominal, so exploratory work on
2006-11 is thinner than the headline 30% suggests. Disclosed here and reported
with any result that leans on that era.
