# 0005 — Six pre-declared slices instead of a 54,000-cell crossed grid

**Date:** 2026-08-16
**Decided by:** Owner, after I re-raised the arithmetic
**Status:** ACTIVE

## Context
The owner initially chose the full crossed slice grid with Romano–Wolf correction.
Computing it: 54,000 cells against 77,471 events is **1.43 events per cell**. Under
perfectly even spreading only 4.8% would clear the 30-event floor, and events
cluster heavily in liquid large caps and recent years. Every 10× slice carries MDE
4.89%/month against a plausible bound of 0.50% — ten times too weak.

## Decision
Six independent slices, each with a stated mechanism: side, deal type, liquidity
tier, participant category, regime, deal size. **Not crossed.** Family size is
6 × n_horizons, not a product.

## Why
The grid was finer than the data. Six real claims beat 54,000 shrugs.

## What would reverse this
A slice returning a strong non-underpowered result, justifying a deeper cut *within
that slice only* — registered separately, with its own correction budget.

## Cost accepted
Interaction effects are invisible. If the signal lives only in "FPI sells in
stressed regimes in small caps", this design cannot see it.
