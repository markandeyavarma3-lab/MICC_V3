# 0045 — The spine is EQ-only, nothing said so, and the collector disagreed with it

**Date:** 2026-09-01
**Decided by:** Mine, found by external validation after the owner asked
"are you sure about the data warehouse?"
**Status:** ACTIVE

## Context

The warehouse audit earlier the same day checked structure — OHLC bounds,
duplicates, partitions, reconciliation against inputs — and passed everything.
It never checked the spine against an **external** source, because until
[0042](0042-salvage-before-deleting-the-predecessors.md) salvaged MICC's raw
bhavcopy archive there was no external source to check against.

There is now: 3,700 original NSE files covering 2005-04 to 2019-10.

**168 (symbol, date) pairs across 25 sessions: 161 exact matches to the
exchange's own file, 0 mismatches, 7 absent.** The prices are right. The seven
absences are the finding.

## What the seven turned out to be

All seven were `SERIES = BE`. Comparing the full symbol sets for 2018-04-23:

| series | in bhavcopy | in spine | |
|---|---:|---:|---|
| EQ | 1,503 | **1,503** | 100.0% |
| BE | 134 | **0** | 0.0% |
| SM | 83 | 0 | 0.0% |
| BZ | 21 | 0 | 0.0% |
| GB | 14 | 0 | 0.0% |

**The spine is exactly the EQ series.** Twenty-one years of it, and no config,
docstring or decision record said so. It was discoverable only by comparing to
the exchange.

Two consequences followed.

**1. The collector disagreed with the seed.** `src/ingest/bhavcopy.py` declared
`SERIES = ("EQ", "BE", "BZ")`. From 2026-08-17 the spine would have started
carrying BE and BZ — the same class of boundary inconsistency 0040 created for
fund units, and a worse one, because **BE is the trade-to-trade surveillance
segment that stocks enter precisely when their price behaves unusually**, which
is exactly the population a deal study is about.

**2. Excluding a series puts holes in the price series.** 52,896 session-steps
skip at least one session (0.68%), 9,154 of them skip more than 20. Because
`_returns_sql` uses `LEAD(close, 252)` over the symbol's own row number, a hole
stretches the horizon: the "12-month" window on eligible events has a median
span of **372 days**, a mean of 383, **4.86% run past 450 days**, and the worst
is **1,553 days — 4.3 years labelled as twelve months**.

## Decision

**`bhavcopy.py` collects EQ only.** The collector matches the seed rather than
the reverse, because the seed is twenty-one years that cannot be re-derived and
the collected tail is eleven sessions that can.

## Why not the other way

BE and BZ are real prices and including them would arguably be better data. But
"better data after 2026-08-17 only" is not better data — it is a universe that
changes definition mid-series, which is the defect this record exists to close,
not to relocate.

## The stretched horizon was measured, not assumed

Restricting the twelve-month sell measurement to windows spanning 300-450 days:

| | n | cohort SD | MDE | mean | verdict |
|---|---:|---:|---:|---:|---|
| all events ([0044](0044-selling-is-underpowered-but-the-bound-is-now-the-question.md)) | 3,626 | 40.15% | 11.92% | −24.26% | 1.99x short |
| span 300–450 days | 3,293 | 36.16% | 12.66% | **−23.78%** | 2.11x short |

The effect estimate moves by **half a percentage point** and the verdict does not
change. So the stretched horizon is a real defect and it is **not** what produced
0044's result. Recording this because the opposite would have been the more
convenient finding and it needed checking either way.

## What the fix moved

Re-running the committed power grid after the collector became EQ-only:

| | before | after |
|---|---:|---:|
| 12-month MDE | 13.2771% | **13.2701%** |
| events | 4,772 | **4,766** |

Six BE/BZ events left the tail. 0.007 percentage points of MDE, verdict
unchanged. `tests/test_measure.py` demanded a decision record for any movement
in that figure, which is why this section exists rather than an edited constant.

## What would reverse this

Evidence that BE-series sessions carry information a deal study needs — likely,
given surveillance correlates with unusual activity. The fix would then be a
calendar-anchored exit rather than an *N*-rows-ahead one, applied to both the
seed and the tail, and the seed cannot gain rows it never had.

## Cost accepted

- **The holes remain.** Making the collector EQ-only keeps the tail consistent
  with the seed; it does not fill the 52,896 gaps, and every forward return in
  this project is still *N* available rows rather than *N* sessions.
- **A stock suspended into BE vanishes from the universe for that period** and
  reappears with no marker. Nothing distinguishes "did not trade" from "traded
  in a series we do not carry".
- **The 1,000 spine symbols absent from `symbol_history` remain unverified for
  ticker reuse.** Reuse was measured at zero across issuers for the 3,382
  symbols the table covers; the rest are simply unchecked.
- **The external validation covered 2005-2019 only.** The `secfull` archive
  covering 2020-2026 was salvaged and has not been used the same way.
