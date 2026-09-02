# 0047 — The collector never rebuilt the spine, and the figures moved every time it ran

**Date:** 2026-09-01
**Decided by:** Mine. Found by a test written hours earlier.
**Status:** ACTIVE

## Context

Three defects, found in one chain while wiring the insider collector
([0046](0046-the-data-we-already-have-is-better-powered.md)). They share a
cause: **the pipeline's outputs were not held to the same standard as its
inputs.**

## 1. The daily job collected prices and never rebuilt the spine

`collect_daily.sh` fetched bhavcopy, parsed it, archived corporate actions and
backed everything up. It never rebuilt `price_spine`. The 20:22 run on
2026-09-01 collected that session, parsed it, and left the spine ending
2026-08-31.

Collection was working perfectly and **every downstream measurement was reading
yesterday**. The gate passed 20/20 throughout, because it is scoped to
`MICCV2_HORIZON` and cannot see the tail.

It was caught by `test_the_price_spine_reconciles_exactly_with_its_inputs`,
written earlier the same day for the previous instance of exactly this — and it
found the second instance within hours. **Row counts could not have caught it;
only the set difference against the inputs could.**

The rebuild now runs in `collect_daily.sh`, price spines only. `fno_spine` is
174M rows and nothing collects F&O, so rebuilding it daily would spend minutes
reproducing an identical file.

## 2. The committed figures were unreproducible by the next morning

`measure.grid()` measured every event on disk, so its answer moved whenever the
collector ran — **4,766 events at 20:00 and 4,790 at 20:22**, MDE 13.2701% then
13.2185%. Not because events were added: more price data completed more forward
windows.

PLAN_3 §6R records that Finding 001 *"is not reproducible … the analysis code
was never committed"*. Committing the code and leaving the **data** unbounded
reproduces that failure one layer down. A decision record quoting a figure that
cannot be recomputed tomorrow is a claim, not a measurement.

`REPRODUCIBILITY_HORIZON = "2026-08-31"` now bounds the spine every study reads.
Verified: it reproduces **13.270067% on 4,766 events exactly**, while
`cutoff=None` gives the live figure for anyone who wants it.

## 3. Exploratory scripts left eight views in the production database

`calchk`, `ev`, `evb`, `fw`, `mk`, `mkt`, `pr`, `px`, `rets`. Mine, from ad-hoc
analysis run against `research_db('prod')`, and `measure.grid()` leaves `rets`
and `mkt` behind on every run by design.

`information_schema.tables` includes views. `status.py` counted them in a dict
comprehension, so **one view whose dependency had been dropped took the entire
status page down** — the monitoring module becoming the thing that needs
monitoring. It now counts each table separately and survives the ones that fail.

Dropping them also removed `deal_resolution`, a legitimate view from
`identity/master.py`, which had to be rebuilt. **A cleanup that cannot tell its
own mess from the project's is not a cleanup.**

## Decision

The spine rebuild is part of collection. Every study reads a bounded horizon.
`status.py` degrades rather than dies.

## What would reverse this

Raising `REPRODUCIBILITY_HORIZON` is deliberate and changes what every quoted
figure means. It belongs in a decision record with the re-measured values beside
the old ones, never as a convenience.

## Cost accepted

- **The quoted figures now lag the data by design.** Anyone reading
  `docs/STATUS.md` sees live counts while the studies quote 2026-08-31. Two
  clocks in one repository, and only this record explains why.
- **[0043](0043-consensus-is-not-registrable-either.md) and
  [0044](0044-selling-is-underpowered-but-the-bound-is-now-the-question.md) were
  measured before [0045](0045-the-spine-is-eq-only-and-nothing-said-so.md) made
  the collector EQ-only.** Re-measured at the fixed horizon they read:

  | study | recorded | now | verdict |
  |---|---:|---:|---|
  | consensus STRICT 12m | 16.5196% | 16.6125% | unchanged, short |
  | consensus PERMISSIVE 12m | 11.6414% | 11.4847% | unchanged, short |
  | selling 12m | 11.7047% | 11.7658% | unchanged, short |

  Sub-0.2pp, no verdict moves, and the records are not edited — 0045 disclosed
  the change for `measure.py` and omitted these two, which this repairs.
- **`measure.grid()` still writes views into the production database.** Made
  survivable rather than fixed; the measurement layer should not be writing to
  the store it reads.
- **The daily job is now materially longer** — two spine builds over 7.7M rows,
  three times a session.
