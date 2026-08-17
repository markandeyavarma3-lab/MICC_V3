# 0012 — Seasonality cells must survive a time split AND an index split

**Date:** 2026-08-17
**Decided by:** Owner
**Status:** ACTIVE

## Context
The name-based partition in [0008](0008-three-way-split.md) is meaningless for
seasonality, whose unit is a (window × alignment × basis) cell across 202 indices —
~31.9M cells — not a stock. Seasonality needed its own answer and had none.

## Decision
Both splits, and a cell must clear its bar under both.

- **Time:** explore 2005–2015, confirm 2016–present. `min_obs` thresholds apply
  per half, not overall.
- **Index:** sha256 on index name, 40% explore / 60% confirm.

## Why
The time split is the one that tests what a seasonal claim actually asserts —
**persistence**. MICCV2's atlas never did this: 31.9M cells scored against a single
sample, best pattern at the 94th percentile of rotated noise.

The index split is weaker and is labelled as such: the 202 indices overlap heavily,
since NIFTY 50 constituents sit inside NIFTY 100, NIFTY 500 and most sector and
thematic indices. Its result is reported as corroborating, never as independent
confirmation.

## What would reverse this
Evidence that halving the sample per cell pushes every cell below its observation
floor, making the design vacuous rather than strict. That is measurable before the
rescan and should be measured first.

## Cost accepted
Very few cells will survive both. Given the prior — best pattern at the 94th
percentile of noise — near-zero survivors is the probable correct answer, and this
design is built to be able to say so.
