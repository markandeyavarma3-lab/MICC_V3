# 0027 — The seed is `v1_export` **plus** the warehouse increments

**Date:** 2026-08-21
**Decided by:** Owner, on a blocking contradiction raised by Claude
**Status:** ACTIVE

## Context

Plan 1 §3.1 carries `MICCV2/data/raw/v1_export/`. Plan 1 §3.2 drops
`MICCV2/data/warehouse/` as *"Derived. Rebuilt by new code from `v1_export`."*
Plan 1 §3.4 then gates Phase 1 on reproducing eight numbers exactly, and
`configs/universe.yml` codifies them with `tolerance: 0`.

**Measured 2026-08-21, all eight resolve against the directory marked for
deletion and none against the directory marked for carrying:**

| Gate check | Expected | `v1_export` (carried) | `warehouse/` (dropped) |
|---|---:|---:|---:|
| Price rows | 7,749,148 | 7,676,618 | **7,749,148** |
| Trading sessions | 5,339 | 5,312 | **5,339** |
| Date max | 2026-08-14 | 2026-07-08 | **2026-08-14** |
| Dead symbols | 1,497 | — | **1,497** |
| F&O rows | 174,616,363 | 69,193,526 | **105,422,837** |

The arithmetic is exact, not approximate:

```
prices  7,676,618 (seed) +      72,530 (warehouse/prices/stock_data_inc)  = 7,749,148
F&O    69,193,526 (seed) + 105,422,837 (warehouse/fno)                    = 174,616,363
```

**Why the two diverge.** The gate figures were measured on 2026-08-16 against
MICCV2's *live* warehouse. `v1_export` was frozen on **2026-07-08**. The gap is
72,530 price rows (2026-07-09 → 2026-08-14) and — far worse — **F&O years 2017
through 2025 in their entirety**: `fo_data/` jumps straight from `_y=2016` to
`_y=2026`.

None of it is derivable from the seed. NSE does not re-serve this history.
"Rebuilt by new code from `v1_export`" is not a description of work that can be
done.

## Decision

`data/raw/v1_export/` and the non-derivable warehouse partitions —
`warehouse/prices/stock_data_inc/` and `warehouse/fno/` — are **both** carried
into `data/raw/`, and treated as equally immutable seed input. The eight gate
numbers in `configs/universe.yml` stand unchanged.

## Why

The plan's "carry raw, drop derived" rule is sound, but it mis-classifies these
two partitions. They are *derived* in provenance and **irreplaceable** in fact:
they were accumulated by MICCV2's daily collector over years against endpoints
that no longer serve history. The rule's purpose is to avoid carrying anything
that can be regenerated; these cannot.

Options rejected:

- **Seed only, restate the gate to its true values.** Cleanest story, and it was
  the literal reading of the plan. Rejected because it silently abandons nine
  years of F&O history and five weeks of prices to preserve a tidy rule, and the
  gate would then verify a smaller claim than the one the project has been
  making.
- **Drop F&O from scope entirely.** Defensible on the critical path — Engine E is
  deferred and all four registered studies are bulk/block deal studies, so 174M
  F&O rows may earn nothing before 2027-02-28. Rejected because the cost of
  keeping them is ~1.2 GB of disk, and the cost of being wrong is permanent.

## What would reverse this

A measured demonstration that the F&O partition is not required by any study on
the critical path **and** disk pressure that makes 1.2 GB material. The prices
increment is not reversible on any grounds: it is inside the study window.

## Cost accepted

- ~1.2 GB of additional disk, on a machine with no backup ([0014](0014-no-remote-yet.md)),
  which makes Risk 8 proportionally worse.
- The clean "raw is raw, derived is derived" boundary is now a
  **three**-category distinction: raw, derived-and-regenerable, and
  derived-but-irreplaceable. Every future teardown must reason about the third
  category explicitly rather than applying the rule mechanically.
- `MICCV2/data/warehouse/` may **not** be deleted until the copy is verified by
  hash. Plan 3 §8's "first irreversible act" is deferred accordingly.
