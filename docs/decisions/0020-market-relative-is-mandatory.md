# 0020 — Pooled scans must use market-relative returns; the PRICE basis is dead

**Date:** 2026-08-18
**Decided by:** Claude, forced by measurement
**Status:** ACTIVE

## Context
Per-stock calendar analysis is arithmetically impossible: a cell fires once a
year, so a 21-year stock yields 21 observations, and the owner's fold design
leaves 2–5 in the test window. Two observations detect an effect of 49.5%/yr.

The obvious fix is pooling across stocks — 4,200 × 5 years = 21,000 observations,
MDE 0.48%/yr. **That reasoning is wrong.** Every stock experiences a given
calendar day simultaneously, so all of them share the market factor.

Measured on 657 liquid names, 2015+:

| Basis | Mean pairwise ρ | n_eff of 21,000 | MDE/yr |
|---|---|---|---|
| PRICE (raw) | **+0.2350** | **4.3** | **33.95%** |
| MARKET_RELATIVE | +0.0001 | 6,694.1 | **0.86%** |

Removing the market factor multiplies effective sample size by ~1,550.

## Decision
`MARKET_RELATIVE` is the only basis permitted for a pooled verdict. `PRICE` is
retained for single-stock reporting and for comparison with the predecessor's
atlas, and may never produce a pooled conclusion.

## Why
21,000 raw stock-years are worth 4.3 independent observations. The unit is
effectively the year, and there are 21 of them. Market-relative returns remove
the common factor, and the residual correlation is +0.0001 — indistinguishable
from independence.

This also means the honest question is cross-sectional: not "is day 47 good" but
"does day 47 rank stocks consistently, and does the ranking persist?"

**The predecessor scanned both bases and treated them as equals. Its entire
PRICE-basis pooled output was arithmetically worthless.**

## What would reverse this
A market definition that fails to remove the common factor — for example a
cap-weighted index against an equal-weighted universe, where residual beta
dispersion could leave real correlation. The estimator is the cross-sectional
mean of the universe itself, which is why it nets to +0.0001.

## Cost accepted
Any pattern whose entire content is "the whole market rises on day 47" is
invisible to the primary basis by construction. That is the correct trade — such
a pattern has 21 observations and is undetectable anyway.
