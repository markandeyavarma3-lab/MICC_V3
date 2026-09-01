# 0041 — The adjusted spine was carrying unadjusted splits, and its guard could not see them

**Date:** 2026-09-01
**Decided by:** Mine, and it is a correction of a guard I did not write but did trust
**Status:** ACTIVE

## Context

`spine.build_adjusted` splices raw prices onto the adjusted seed at 2026-06-25
and guards the splice like this:

> a SPLIT, BONUS or RIGHTS after the adjusted series ends means the tail
> genuinely needs adjusting and this refuses to build

The guard is correct and it passed. It was reading `corporate_actions.parquet`,
which **ends 2026-06-29** — four days past the boundary — while the spliced tail
ran to 2026-08-14 and, after the price collector, to 2026-08-31. A clean pass
meant "no action in the first four days", not "no action in the tail". Nothing
in the codebase stated the table's own horizon, so the gap was invisible.

Searching the tail directly for discontinuities >35% found 22. **Fifteen were
already in the spine before this project collected a single price** — they
arrived with the increments carried under [0027](0027-carry-the-warehouse-increments.md)
and have been there since. Each reads as a −50% to −90% return.

The 12-month result is not affected, and that was measured rather than assumed:
of 213,304 deals with a mature 12-month window, **zero** fall after 2026-06-25.

## Decision

Three changes:

1. **Corporate actions are collected** ([`src/archive/corporate_actions.py`](../../src/archive/corporate_actions.py),
   [`src/ingest/corp_actions.py`](../../src/ingest/corp_actions.py)), typed and
   factored. SPLIT and BONUS carry a factor; RIGHTS and DEMERGER carry NULL.
2. **`build_adjusted` applies those factors** to the whole series. Back-adjustment
   restates history, so for a row dated *d* the factor is the product of every
   action factor with an ex-date strictly after *d*.
3. **The discontinuity check runs on the finished, adjusted union** rather than
   on the actions table, with a declared tolerance of `MAX_UNEXPLAINED_JUMPS`.

## Why

A guard that reads a table without asserting that table's coverage is not a
guard, it is a lookup that happens to return zero. The fix is not a bigger
table — it is checking the thing the guard is a proxy for. Prices are where a
missed action shows up, so prices are what is now searched.

Only SPLIT and BONUS are applied. A rights factor needs the cum price and a
demerger's needs the value of the resulting entity; neither is in the subject
line, and a placeholder factor is worse than none because it produces a number
nobody can defend. Both remain in the discontinuity check, so an unadjusted one
still stops the build.

The tolerance is **12** rather than zero, and that is a real cost. After
adjustment the survivors are known data defects, not actions: NV20 carries a bad
print in the MICCV2 data (13.99 → 11,985 → 13.98 inside one week), BURNPUR fell
35.3% as a genuine move in a Z-group penny stock, and KSHITIJ-RE is a rights
entitlement 0015 already removed. A threshold of zero would refuse forever on
rows nothing can fix, and a guard that cannot pass gets switched off.

## What this moved, measured rather than assumed

Re-running the committed power grid after the fix:

| | before | after |
|---|---:|---:|
| 12-month MDE | 13.3038% | **13.2771%** |
| events | 4,750 | **4,772** |
| verdict vs the 6.00% bound | 2.22x short | **2.21x short** |

Twenty-two more events from eleven newly collected sessions, measured on a
series where sixteen splits no longer read as -50% days. **The verdict is
unchanged** and [0038](0038-no-horizon-survives-a-participation-cap.md) stands:
no Track D horizon is registrable.

That the number moved at all is the point. `tests/test_measure.py` pinned
13.3038% and demanded a decision record if it ever changed, which is why this
section exists rather than a quietly edited constant.

## What would reverse this

A rights issue or demerger large enough to matter landing in the tail. Both
carry NULL factors today, so the build would refuse — correctly — and the answer
would be to compute the rights factor from the cum price rather than to raise
the tolerance.

## Cost accepted

- **`MAX_UNEXPLAINED_JUMPS = 12` is a budget that could be abused.** Raising it
  to silence a failure would be the same class of error as editing a gate oracle.
  It is documented as a budget for *known* defects; nothing enforces that.
- **The seed's own adjusted history is not re-verified.** 65 of the 73 extreme
  drops the gate counts sit before the boundary, in MICCV2's adjustment, and this
  decision does not examine them. They may be genuine; nobody has checked.
- **Corporate actions are collected from 2026-06-01 only.** Anything before that
  relies on the seed's table, which is what this record just showed can end
  earlier than anyone assumed.
- **RIGHTS and DEMERGER are unadjusted.** Ten and three of them respectively sit
  in the current window, below the 35% threshold, silently slightly wrong.
