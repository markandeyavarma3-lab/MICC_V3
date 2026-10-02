# 0082 — Why a security left the universe: six reasons, four of them measured

**Date:** 2026-10-01
**Decided by:** Owner ("yeah lets start doing"), on the recommendation to build
Plan 3 step 3.3 next.
**Status:** accepted
**Related:** 0040 (fund units leave the universe), 0045 (the price universe is
EQ only), 0049 (read before destroying), 0051 and step 6.4 (pricing the events
that stop trading), 0081.

## Context

`security_master.delisting_reason` was UNKNOWN on every one of 1,041 DELISTED
rows. Step 6.4 therefore prices every stopped event as a delisting. Building
the classifier showed that the DELISTED status was itself wrong in three ways:

1. **Renames.** A security's last trade was read from its canonical
   (longest-held) symbol only, so a company was DELISTED on the day it was
   renamed. 106 rows were still trading under their new symbol.
2. **No stale rule.** `universe.yml` says a security is dead after 20 sessions
   without a trade. The code used "did not trade on the last spine day".
3. **Not delistings at all.** A face-value split gives a company a new ISIN
   on the same symbol, and the old ISIN looked delisted (212). A stock moved
   from EQ to the BE or BZ surveillance series vanishes from an EQ-only spine
   (0045), and so does a fund unit (0040). 483 symbols had no spine price after
   2026-08-14, the day MICCV2 stopped; most were still trading.

## Decision

1. **The last trade is taken across all of an ISIN's symbols.** A recycled
   ticker is the trap. A symbol held by more than one ISIN is counted for an
   older holder only up to that holder's own last date, and only where a later
   holder exists. The current holder keeps every trade since.
2. **The 20-session stale rule is applied.**
3. **A new source: the full bhavcopy, every series, 2005 to now**
   (`src/ingest/listing_history.py`). It covers 5,413 sessions: the salvaged
   legacy, sec_full and UDiFF files, plus the collector's own archive, with
   one file per session.
4. **A second new source: NSE's `delisted.csv`** (`src/archive/delisted.py`).
   It has 328 rows from 2002 to 2020: voluntary delistings map to
   ACQUISITION, and compulsory delistings and liquidations map to SUSPENSION.
   Mergers are not on it.
5. **Reasons, first match wins:**
   - ISIN_CHANGE: status MERGED, with `merged_into_id` naming the new ISIN.
     The symbol must trade again within 10 days of the old ISIN's last
     session. isin_master's dates are not day-accurate, so continuity is
     what tells a split from a recycled ticker taken up weeks later. Two
     candidates failed it.
   - LEFT_UNIVERSE: any series traded within the last 30 days.
   - NSE's list: within 400 days of the exit, so that an old delisting of a
     reused ticker cannot match.
   - BSE suspended: SUSPENSION.
   - UNKNOWN.
   - MERGER is never assigned. `universe.yml` requires a link to the
     acquirer, and no source names one.
6. **Status keeps its meaning (the EQ price universe), and the reason says
   what happened at the exchange.** Nothing computes from either field today:
   outcomes and step 6.4 derive their exit reasons from the spine. So this
   changes no published number.

## Result (2026-10-01, on a copy of the production database)

| | before | after |
|---|---:|---:|
| ACTIVE | 2,375 | 2,316 |
| DELISTED, UNKNOWN | 1,041 | 487 |
| DELISTED, LEFT_UNIVERSE | — | 254 |
| MERGED, ISIN_CHANGE (linked) | — | 212 |
| DELISTED, SUSPENSION | — | 112 |
| DELISTED, ACQUISITION | — | 35 |

ACTIVE falls because both ISINs of a split company used to count as active.
The 487 unknowns are now spread evenly, about 30 a year, where before 321 of
the apparent stops fell in 2026. Spot checks: HEXAWARE is ACQUISITION, which
is right (taken private in 2020). PPAP is LEFT_UNIVERSE (trading in BE).
CADILAHC is an ISIN change and then a rename to ZYDUSLIFE. HDFC is UNKNOWN: a
real merger, with nothing in hand to say so.

## Cost accepted

- **Mergers stay UNKNOWN.** Most of the 487 are probably mergers, and step 6.4
  still prices them as delistings. That overstates the sell effect, and the
  overstatement remains declared.
- **NSE's list stops in November 2020.** Exits since then reach a reason only
  through BSE's status or the listing history.
- **BSE's status is a snapshot (July 2026).** A company suspended then and
  revoked since would be misread.
- **A data gap.** No full bhavcopy is held for 2026-06-26 to the collector's
  first session, so a non-EQ stop inside that gap can be misread. The 30-day
  LEFT_UNIVERSE window starts after it.

## What would reverse this

- A source naming the acquirer, such as NCLT scheme orders or an exchange
  list of amalgamations. MERGER could then be assigned with its link, as the
  config requires.
- Step 6.4 starting to read `delisting_reason`. ISIN_CHANGE and
  LEFT_UNIVERSE events should then be priced from the successor ISIN or the
  other series, not at a recovery factor. That changes an effect estimate and
  is charged to a family (0035).
