# 0054 — A twelve-month label on a nine-year holding period

**Date:** 2026-09-05
**Decided by:** Me. The owner asked for step 6.3 to be built. What it found on
the way was not part of the request and is not a judgement call — the horizon
arithmetic was wrong and is now right. The choice I did make, and which is the
owner's to overturn, is that the four benchmark/config deviations below are
DECLARED rather than fixed, because fixing them needs data this project does not
have.
**Status:** accepted
**Step:** Plan 3 step 6.3, and part of 5.6.

## What was built

`deal_forward_outcomes` held 0 rows from the day its schema landed. Every study
— 0038, 0043, 0044, 0046, 0050, 0051, 0052 — recomputed forward returns inline
in its own SQL, so **nine horizons and six benchmarks were specified and one
horizon against one implicit benchmark was ever measured.**

Now: **52,365 outcomes** across all nine horizons, and **237,271 benchmark rows**
against five benchmarks.

| exit reason | n | treatment |
|---|---|---|
| `HORIZON` | 49,950 | real exit at the horizon close |
| `SUSPENDED` | 634 | marked at the last price before the gap, excluded from headline |
| `DELISTED` | 171 | marked at last close × recovery factor, three factors each |
| `CENSORED` | 2,138 | **no row written** — no outcome exists yet (0052) |

## The defect it found

`measure._returns_sql` takes the exit as `LEAD(close, 252)` over a **row index**.
That is 252 traded *rows*, not 252 sessions. A name that stops trading for years
and relists supplies its 252nd row years later, and the result was carried as a
twelve-month return.

Measured on the EXPLORE sell population 0051 and 0052 both used:

- **37 of 1,145 events (3.2%)** span more than 500 calendar days
- 2 span more than 1,000; the worst is **ATLASCYCLE at 3,506 days — 9.6 years**,
  carried as a twelve-month outcome at −117.8% abnormal
- those 37 average **−51.4%** against **−29.6%** for the other 1,108

So the published **−30.30% is −29.59%** once suspensions are excluded, a 0.71pp
distortion of the headline every sell-side decision has quoted.

**No verdict changes.** The effect is ~5x its bound either way and 0050 already
found no population powered. But a twelve-month label on a 9.6-year holding
period is wrong regardless of whether the wrongness is convenient, and Plan 2
§3.4 has named `SUSPENDED` as one of its four cases since the beginning with
nothing able to detect it. It is detectable now: a window whose calendar span
exceeds 1.5x its expected span plus ten days did not hold a position for that
many sessions.

This was found by building the constructed benchmarks, where the same bug
produced a **+77,226% single-day return** (RNAVAL, suspended five years and
relisted) and a mean daily return of +0.087% against a median of −0.094% — the
mean carried entirely by 43 such artefacts.

## Four things the config claims that the data does not support

All four are **declared, not fixed**, because fixing them needs data that does
not exist here. Each is now in the module, the status note, and a test.

1. **`NIFTY500_TR` cannot be built at all.** benchmarks.yml sources it from
   `warehouse.benchmark_n500tr`, which exists in neither the warehouse nor the
   seed and has never been written by any code in this repository. It is the
   config's own declared `broad_market_headline`. **Every result carrying
   benchmark returns is missing its headline broad-market comparison.**

2. **`NIFTY50_TR` is a price index.** It is declared `total_return: true`; the
   only NIFTY50 series held is OHLCV with no dividend leg. Indian large-cap
   yield runs ~1.2%/yr, so at the twelve-month primary horizon this understates
   the benchmark by roughly **a fifth of the 6% plausible-effect bound**, in the
   direction that flatters a long-side result.

3. **`SMALLCAP_SYNTH` is equal-weighted**, not `free_float_proxy_mcap` as
   specified. `pit_universe` carries no market cap at all.

4. **`CHAR_MATCHED` covers 74% of outcomes.** 882 of 886 unmatched event-dates
   have no `char_panel` row at all — the 12-1 momentum characteristic needs a
   year of history a newly-listed name does not have. Of those matched: 29,830
   at the full `SIZE_MOM_VOL`, 8,575 degraded to `SIZE_MOM`, 56 to `SIZE`. The
   `industry` dimension remains absent entirely (`sector_history` is unbuilt).

## Two bugs in my own build, both found by checking rather than by testing

- **CHAR_MATCHED excluded every delisted event.** The event was joined to the
  peer pool to find its own cell, and the peer pool requires a non-null forward
  return — which a name that delisted inside the window does not have. So all
  513 delisted outcomes and half the suspended ones got no characteristic
  benchmark, and those are precisely the events 0052 found load-bearing for the
  liquidity gradient. Now joined to the characteristic map instead, with the
  self-exclusion applied only where there is a self to exclude.
- **`n > min_names_per_cell` where the config says `min_names_per_cell: 10`.**
  A minimum read as an exclusive bound silently required eleven. Fixing it moved
  3,223 outcomes up to the finest match level.

## And one process note

The build was launched with `nohup ... &`, and the harness reported **exit 0
while the Python process was still running.** Had I trusted it, these tests
would have run against a half-written table. This is the same failure as the
truncated `shp.tar.gz` that reported exit 0 over a 10% archive, and it is the
seventh instance of *the signal existed and nothing carried it*. The process
list is the check, not the exit code.

## What would reverse this

Any of the four declared deviations becoming fixable: a real NIFTY 500 total-
return series, a dividend leg for NIFTY 50, a market-cap column in
`pit_universe`, or `sector_history` built so the fourth DGTW dimension exists.
The suspension rule itself would be reversed by evidence that 1.5x-plus-ten-days
excludes legitimate windows — the current split is 634 suspensions against
49,950 horizons, and every one of the 634 exceeded its allowance by more than a
holiday run could explain.

## Cost accepted

No trials. This writes a table and computes no effect estimate; the 0.71pp
restatement above is a correction to an already-charged measurement, not a new
one. The first study to READ this table charges its family.
