# 0092 — exp_004 v3 waits: the clean quarters stay unread until they can see the bound

**Date:** 2026-10-25
**Decided by:** Owner. Shown the v3 draft with a capped (A) and an uncapped (B)
version side by side and a third option to register neither, they wrote
"go with c".
**Status:** ACTIVE
**Related:** 0076 (v2 registered and UNDERPOWERED), 0035 (dispersion-only power),
`docs/plan/EXP004_V3_REGISTRATION_DRAFT.md`, `docs/reports/HOLDINGS_POWER_PRELIMINARY.md`.

## What was decided

**Nothing is registered.** `exp_004_holdings_change_v3` does not exist, and
`TRACK_H_HOLDINGS` stays at 3 trials.

**The clean pool is protected.** v2 read the quarter-ends from 2021-Q3 up to
its data date; every quarter-end from 2021-07 to 2026-06 is treated as read
(2026-Q2 included, conservatively), for the capped and the uncapped outcome
alike. A v3 may be tested only on the rest:
- the 21 quarter-ends 2016-Q2 → 2021-Q2, opened by the BSE backfill and the
  2016-schema parser fix of the same day;
- every quarter-end from 2026-Q3 on, four a year.

No code reads a holding change against a return on the clean pool. The only
thing measured there is dispersion (`holdings_power.clean()`), with random
deciles.

## Why

On the clean pool, today:

| version | MDE | vs the 1.50% bound |
|---|---:|---:|
| A — outcome capped at 1st/99th | 2.20% | 1.47× |
| B — uncapped (v2's rule) | 7.13% | 4.76× |

Both would land UNDERPOWERED by their own kill criterion 1. Registering
either would charge two trials to learn what the power run already says. The
only version inside the bound (capped, 0.88×) uses the 20 quarters v2 already
read, and is not a test.

## What happens next

- `configs/remeasure.yml` re-measures the clean pool yearly. The power report
  carries a "clean pool" section.
- At about 46 clean quarters (about 2032), the capped version reaches the
  bound. Version B does not reach it this decade.
- **The tail rule (A or B) is still open.** It must be chosen on which
  question is the right one, not on the power row. It must be recorded
  before the clean pool is next allowed to be read, and in any case before
  any registration. The draft sets out both.

## What would reverse this

- The owner choosing to register A or B now, accepting a likely UNDERPOWERED
  landing and two trials.
- A defect found in the clean-pool data (the 2016-2017 BSE filings, read only
  from today). That would be re-measured, and the pool redefined, not read.

## Cost accepted

- No answer on institutional holding change for years.
- The 21 past quarters wait unread. Their value as an untouched test is kept
  by not using it.
