# 0088 — The price spine is corrected where a second source confirms, and quarantined where none does

**Date:** 2026-10-09
**Decided by:** Owner, asked whether to fix the price history first, then
re-check the verdicts, then build the website. They answered: "start 1 and
then after 1 is done, go for the 2 then 2 is done then go for the 3".
**Status:** accepted; applied 2026-10-09
**Related:** 0087 (the Kite audit that found it), 0045 (the EQ-only spine),
`src/warehouse/spine.py`, `src/ingest/corp_actions.py`.

## Context

`price_spine_adj` is the inherited seed's back-adjusted series plus this
project's own tail. It held 3,107 one-day moves larger than 35%. The build's
discontinuity guard checked only moves after the seed boundary (2026-06-25),
so 21 years were never examined. 0087 found that many of these moves are
splits and bonuses the seed's action table never recorded: TCS 2018 and
INFY 2015, both 1:1 bonuses, read as −50% days.

**A correction to 0087's own figure.** 0087 reported 1,481 moves "within
1.5% of a clean fraction a/b (a < b ≤ 20)". That set of fractions is so
dense that nearly any number lands within 1.5% of one of them, so the
figure overstated the problem. The strict set below gives 895 moves on a
split or bonus ratio. 0087's deal-outcome shares (2.3% / 3.4% / 4.1%) were
computed on the overstated set and are superseded by the re-check under
step 2.

## Decision

1. **Every one-day move > 35% is classified by one pure rule**
   (`scripts/build_price_corrections.py::classify`) using three tests:
   - **Is it a level?** The median close of the next 5 sessions must hold
     the shifted level within 15% (log). A one-day print reverts, and
     "correcting" it would rescale the whole history before it. Such moves
     are classed **REVERTED** and never corrected.
   - **Does NSE record an action that day?** The record comes from NSE's
     corporate-action archive, now fetched back to 2005: 709 bonuses and
     709 splits. If NSE's factor matches the move, it is used. If the day
     was partly adjusted already (ONGC 2011: split plus bonus, factor 0.25,
     ours moved 0.47), the residual strict ratio is used. Such moves are
     tier **T1**.
   - **Is Kite flat that day while ours moved by a strict ratio?** Kite's
     move must be under 0.2 in log terms. The strict ratios are 1/2, 1/3,
     1/4, 1/5, 1/6, 1/8, 1/10, 1/20, 2/5, 3/5 and 2/3, plus their inverses
     for consolidations. Such moves are tier **T2**.
2. **Only T1 and T2 are corrected: 226 rows** (55 T1, 171 T2), in
   `configs/price_corrections.csv`. Each carries its evidence. They are
   applied over the whole series, seed included, as back-adjustments:
   prices before the ex-date are multiplied by the factor, and volume is
   divided by it. The file is frozen and reviewed like code. Kite's data is
   held for one month; the evidence outlives it.
3. **Everything else is quarantined, never changed: 2,881 rows** in
   `configs/price_suspect_days.csv`:

   | class | rows | meaning |
   |---|---:|---|
   | UNEXPLAINED | 1,116 | no second source |
   | UNEXPLAINED_KITE_FLAT | 716 | Kite flat, not a split ratio |
   | UNCONFIRMED_RATIO | 522 | on a split ratio, no second source |
   | REVERTED | 481 | a one-day print |
   | REAL | 31 | Kite shows the same move |
   | UNEXPLAINED_BOTH_MOVE | 15 | both moved, differently |

   A split ratio alone is not proof: 4 of 42 Kite-confirmed real moves land
   on one. Correcting UNCONFIRMED_RATIO would change real prices about one
   time in ten. Studies may exclude windows that touch a suspect day, and
   step 2 measures every verdict both ways.
4. **The guard covers the whole history.** Any move > 35% that is not on
   the suspect register counts against `MAX_UNEXPLAINED_JUMPS`, so a new
   unexplained jump stops the build instead of entering a study.
   After the rebuild:
   - 2,881 moves remain, every one registered;
   - 0 are unregistered;
   - the 226 corrected days now read as ordinary sessions.

## What would reverse this

- A third source confirming an UNCONFIRMED_RATIO day, such as a BSE action
  record or an annual report. It moves to the corrections file through the
  same rule and a rebuild.
- A correction found wrong. It is removed from the CSV with a note, and the
  spine rebuilt.

## Cost accepted

- **The quarantine is large.** 2,881 days in about 1,400 symbols stay as they
  were, mostly in delisted small caps. Excluding windows that touch them
  costs observations. Keeping them costs fake returns. Step 2 reports both.
- **Every study's inputs change**, so every registered verdict is
  re-measured (step 2). The registry is write-once: a re-measurement is a
  new, documented analysis, never an edit of a recorded result.

## Pinned figures this moved (2026-10-09)

- **0068's twelve-month MDE (deals):** 10.8496% → 10.8462%, on the same
  4,630 events. Still 1.81× short; the verdict is unchanged.
- **`reconcile.py`'s `adj_extreme_drops`** (single-session falls below
  0.1×): 73 → 55. Eighteen were seed-missing 1:10 actions, now corrected.
- **0046's promoter-sell twelve-month MDE (insider power):** 6.8027% →
  6.8288%, on the same 9,284 events. That is slightly worse, and still
  about 1.13× short. The 2027-09-15 re-measure reads the corrected spine.

## Addendum 2026-10-10: the quarantine, understood

- **GAP (1,850 days).** For 1,850 of the quarantined days, the previous
  trading day was more than 30 days earlier (median 98). These are the first
  sessions after a suspension or a spell outside the EQ series. They are
  real price changes across months, not one-day moves, and the deal and
  insider studies already drop windows across such gaps (0052's span rule).
  `scripts/build_price_corrections.py --reclassify-gaps` adds `gap_days` and
  the prior class (`was`); no (symbol, date) key changed.
- **Single-day prints dropped (203 rows).** These are REVERTED days that
  jump more than 35% and are back within 15% of the prior close the next
  session. NSE's circuit filters (2–20%) rule that out as a trade for nearly
  every equity. They are listed in `configs/price_bad_prints.csv`, and
  `spine.py` drops those rows: the day becomes missing and no price is
  invented. Kite holds none of these 203; all are in names it does not
  carry.
- **After both changes,** the adjusted spine holds 2,566 one-day moves over
  35% (from 3,107), every one registered. The quarantine now reads:

  | class | days |
  |---|---:|
  | GAP | 1,850 |
  | REVERTED, not single-day | 355 (152 after the drops) |
  | UNCONFIRMED_RATIO | 333 |
  | UNEXPLAINED | 312 |
  | REAL | 31 |

  Of the original 1,847 "unexplained", 312 remain unexplained.
