# 0029 — The F&O gate figure was a double-count; it becomes 174,272,768

**Date:** 2026-08-21
**Decided by:** Claude, on measurement. Amends one figure that
[0027](0027-carry-the-warehouse-increments.md) — an owner decision — said would
stand unchanged. Flagged for the owner rather than absorbed silently.
**Status:** ACTIVE

## Context

[0027](0027-carry-the-warehouse-increments.md) carries `v1_export` **plus** the
warehouse increments, and states that *"the eight gate numbers in
`configs/universe.yml` stand unchanged."* That was written on the arithmetic
that the two sources are contiguous:

```
prices  7,676,618 (seed) +      72,530 (increment) = 7,749,148
F&O    69,193,526 (seed) + 105,422,837 (increment) = 174,616,363
```

Both right-hand totals match `universe.yml`. **For prices the premise is true.
For F&O it is false**, and the sum matching anyway is the coincidence that hid it.

Measured 2026-08-21 on the carried data:

| | seed `fo_data` | increment `fno` |
|---|---|---|
| rows | 69,193,526 | 105,422,837 |
| distinct dates | 2,862 | 2,373 |
| span | 2005-01-03 .. 2026-07-07 | 2016-07-01 .. 2026-08-14 |

**The two sources share ten trading dates** — 2016-07-01 through 2016-07-15 —
carrying **343,595 rows present in both**. An `INTERSECT` on the full contract
key returns exactly 343,595, so they are the same rows, not merely the same
dates.

`174,616,363` is therefore the sum of two overlapping sets. The distinct count is
**174,272,768**. The predecessor evidently reported the sum, so its published
"174.6M F&O rows" overstates by 343,595 (0.20%).

### A second defect found in the same measurement

The seed's F&O export carries **4,025,340 rows (5.8%) with a blank `expiry`**.
The increment carries none. Those rows are real, distinct contracts whose expiry
label was lost in the V1 export — they are *not* duplicates, though any
uniqueness check keyed on `(date, instrument, symbol, expiry, strike,
option_typ)` will report them as such. A naive `SELECT DISTINCT` over the union
would have silently destroyed about two million rows of real data while
appearing to "clean" it.

## Decision

1. `configs/universe.yml` `expect_fno_rows` becomes **174,272,768**, with the
   provenance of the old figure recorded beside it.
2. The spine resolves the overlap by rule: **for any date the increment covers,
   the increment wins.** Implemented as an anti-join on the date set, never as a
   `DISTINCT` over rows.
3. The blank-`expiry` rows are **kept**, and the defect is recorded here for the
   identity phase to address.

## Why

The increment wins on shared dates because it came from the maintained collector
and — decisively — it can identify its contracts while the seed cannot: zero
blank expiries against 5.8%. Where both hold a date, one of them is strictly
better data.

The alternative was to keep `174,616,363` and make the gate pass by summing the
sources without de-duplication. That would have required the pipeline to
deliberately double-count 343,595 rows in order to match a number, which is
writing the test to fit the answer. Plan 1 §3.4 says a mismatch is *"a blocking
failure, investigated before proceeding"*; it was investigated, and the finding
is that the expectation was wrong.

## What would reverse this

Evidence that the 2016-07-01..07-15 rows differ between the two sources in some
field outside the contract key, making them genuinely distinct observations
rather than one dataset written twice. The `INTERSECT` on the key does not rule
this out — it was not extended to every value column.

## Cost accepted

- The Phase 1 gate no longer reproduces the predecessor's published figure, so
  the "the rebuild matches MICCV2 exactly" claim now carries an asterisk and an
  explanation. Eight of nine checks are exact; the ninth is exact against a
  corrected expectation.
- The correction is 0.20%. It changes no research conclusion, and the effort
  spent on it buys only the knowledge that the number is now right — which is
  the whole business this repository is in, but is worth stating as a cost.
- **4,025,340 F&O rows cannot currently be uniquely keyed.** Any future work
  joining on the contract key must handle that, and no such join exists yet to
  be audited.
