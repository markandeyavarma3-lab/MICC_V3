# 0009 — Partition on ISIN, never on symbol

**Date:** 2026-08-17
**Decided by:** Claude, from measurement
**Status:** ACTIVE

## Context
Measured against the v1_export seed on 2026-08-17:

| quantity | value |
|---|---|
| ISINs carrying more than one symbol | 276 |
| symbols involved in a rename | 589 |
| ...appearing in deal data | 459 |
| deal rows on renamed symbols | 26,046 = **11.04%** |

Real cases: `CADILAHC → ZYDUSLIFE`, `PRISMCEM → PRSMJOHNSN`, `GEOJITBNPP →
GEOJITFSL`.

## Decision
Split key is the ISIN. Symbols fall back to `SYM:{symbol}` only when no ISIN
resolves; the fallback fraction is capped at 15% of rows and reported with every
result. Measured: **87.6% of deal rows are ISIN-keyed, 12.4% fall back** — passes.

## Why
Under a symbol key, a company that renames sits in one stratum under its old name
and another under its new one. The confirmation set is then contaminated by
construction, for 11% of the corpus, **and nothing in any output would look
wrong.** This is the same disease that produced MICCV2's 45% event attrition,
which the audit established was naming mismatch rather than survivorship.

Assignment is a sha256 modulo rather than a seeded shuffle: a seeded shuffle over a
symbol list reassigns every name whenever the list changes, and it changes with
every listing and delisting.

## What would reverse this
A better identifier — a permanent internal `security_id` surviving corporate
actions that even ISIN does not (ISIN itself changes on some reconstitutions).
That would be strictly better and would supersede this record.

## Cost accepted
12.4% of deal rows are symbol-keyed and carry residual rename risk. The fallback
is defensible only in the narrow sense that an unmapped symbol is one we cannot
demonstrate ever renamed.
