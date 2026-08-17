# 0015 — Rights entitlements and DVR classes leave the universe

**Date:** 2026-08-17
**Decided by:** Claude, found while measuring the split
**Status:** ACTIVE

## Context
Of the 1,098 deal symbols that resolve to no ISIN, classification showed:

| class | count |
|---|---|
| genuine unmapped | 911 |
| rights entitlements (`-RE`) | 160 |
| DVR / partly-paid | 27 |

## Decision
`*-RE` is excluded outright. `*DVR` is excluded from headline results and retained
flagged for a sensitivity run. Measured cost: **1,953 deal rows, 0.83%.**

## Why
Rights entitlements are not equities. They trade for a few days and expire, so
they have no continuing price series — an "event" on one has no forward return to
measure, only noise. DVR classes are separate instruments on the same issuer, so
including both double-counts the company.

Neither was in any plan. Both were found by applying the split to real data, which
is an argument for doing arithmetic on the actual corpus before writing designs
about it.

## What would reverse this
A study specifically about rights issues, where the entitlement instrument is the
object of interest rather than contamination.

## Cost accepted
0.83% of deal rows. Trivially small, and stated so it is not rediscovered as a
discrepancy later.
