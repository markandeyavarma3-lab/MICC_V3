# REMEASURE_0088.md — every registered verdict on the corrected price spine

**Step 2 of the owner's order (2026-10-09): fix the prices (decision 0088),
then re-check every verdict, then build the website. Nothing here touches the
registry. Each line is a new, documented measurement of committed code on
corrected inputs; the registered results stand as recorded. Decision 0089.**

## What changed in the inputs

- **226 seed-missing splits and bonuses back-adjusted.** Each was confirmed
  by NSE's own action record or by a flat Kite series (0088).
- **203 single-day prints dropped.** Each jumped more than 35% and was back
  within 15% the next session (0088 addendum).
- **char_panel rebuilt without duplicates.** 29,833 keys had been held
  twice since August by stale partition files; every CHAR_MATCHED benchmark
  read them, nondeterministically. The writer now replaces the whole table.
- **Quarantine.** 2,566 one-day moves > 35% remain, every one registered.
  Of these, 1,850 are price changes across a trading gap, 31 are real moves,
  and 312 are unexplained.

## The verdicts

| study | registered verdict | re-measured | verdict holds |
|---|---|---|---|
| exp_001 bulk-deal avoidance | REJECTED: FIT +0.237%/yr, TEST −0.022%/yr | rebuilt from the spec (its code was never committed): all names **−0.114%/yr** net, +0.140% gross; the filter's own costs are ~0.25%/yr; 0 of 200 random splits pass | **yes** |
| exp_002 entity persistence | DEAD | not alive on corrected prices, and with quarantined windows excluded. TOP tier −1.56% net out of sample; rank IC −0.22 over 12 entities; now deterministic | **yes** |
| exp_003 F&O positioning | UNDERPOWERED, unfitted | unaffected: the outcome is the NIFTY index, not the stock spine | **yes** |
| exp_004 v2 holdings change | UNDERPOWERED, q 0.61 / 0.92 / 0.61 | at the registered data date (2026-10-08): q 0.64 / 0.92 / 0.64; MDE 3.57% / 3.04% / 1.66% (d_mf 1.10× short, was 1.12×). The registered panel is reproduced exactly: 33,228 rows, 21,212 tradeable | **yes** |
| exp_005 signal search | NO_SEARCH_SKILL, q 0.114 / 0.114 / 0.111 | q 0.126 / 0.126 / 0.126; the partial (factor-neutral) procedure q 0.046 / 0.012 / 0.012 (registered 0.009) | **yes** |
| seasonality | DEAD (21 yearly observations) | structural; the tests pass on corrected prices | **yes** |

## Power checks that moved

| check | before | after |
|---|---|---|
| deal grid, 1 month | 2.12% (4.24×) | 2.07% (4.13×) |
| deal grid, 3 months | 4.40% (2.93×) | 4.41% (2.94×) |
| deal grid, 12 months | 10.85% (1.81×) | unchanged |
| insider promoter sell, 12 months | 6.80% | 6.83% (~1.13×) |

## Defects found by re-measuring, all fixed

- **exp_001: not reproducible.** Fixed with `src/research/avoidance.py`.
  The recorded FIT figure does not come back; the verdict does. The
  original name-split rule was never recorded.
- **exp_002: different answers on identical inputs.** The cause was the
  duplicated char_panel. Fixed with `src/common/partitioned.py`, which all
  four partitioned writers now use.
- **exp_004: a re-run read newer filings than the registered run.** Fixed
  with `holdings.run(as_of=)` and `REGISTERED_AS_OF`.
- **exp_005: the atlas reuse guard ignored prices.** Fixed with
  `prices_hash` in the manifest.

## What it means

**No verdict changed.** The price errors were real: 226 missing actions,
203 bad prints, a duplicated benchmark panel. They were not what stood
between this project and a finding. The one live thread, exp_005's
factor-neutral residual, survives the correction (q 0.012). Its forward
test (exp_006, drafted) would need ~62 forward blocks at the re-measured
effect (test IC 0.028, from 0.030).
