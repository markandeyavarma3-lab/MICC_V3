# 0046 — The best-powered event class was already on disk, unused

**Date:** 2026-09-01
**Decided by:** Mine, prompted by the owner asking whether more data could be found
**Status:** ACTIVE

## Context

Four studies are measured and none is registrable
([0038](0038-no-horizon-survives-a-participation-cap.md),
[0043](0043-consensus-is-not-registrable-either.md),
[0044](0044-selling-is-underpowered-but-the-bound-is-now-the-question.md)), and
the arithmetic on waiting is hopeless: consensus needs 3.76x more monthly
cohorts, which is 70 years.

The owner asked whether more data could be extracted. The first place to look
was the disk, and the answer was there.

**Of 119 non-empty tables in `data/raw/v1_export`, exactly 10 are referenced by
any code in `src/`.** The seed has been carried, hash-verified and reconciled
since [0027](0027-carry-the-warehouse-increments.md), and 109 of its tables have
never been read.

## What is in there

| table | rows | why it matters |
|---|---:|---|
| `insider_trading` | 283,281 | a whole event class; SEBI PIT disclosures 2016-2026 |
| `pit_universe` | 359,047 | **the point-in-time universe step 1.8 calls "still missing"** |
| `shp_institutional_summary` | 3,565,899 | quarterly institutional holdings |
| `shp_promoter_group` | 2,526,543 | promoter holdings |
| `stock_delivery` | 7,685,343 | delivery quantity, absent from bhavcopy |
| `global_indices_daily` | 212,955 | the benchmarks Phase 5.6 needs |

## The measurement

Power only — cohort SD and MDE, **no effect estimate**.
[0035](0035-power-may-use-the-full-universe-effects-may-not.md) permits power on
the full universe; [0002](0002-preregistration-before-results.md) forbids
peeking at outcomes, and no mean was computed.

| population | n | cohorts | cohort SD | MDE | verdict |
|---|---:|---:|---:|---:|---|
| all insider buys | 102,232 | 116 | 19.84% | 14.3520% | 2.39x short |
| all insider sells | 95,874 | 116 | 22.67% | 18.3349% | 3.06x short |
| PROMOTER buys | 24,835 | 116 | 23.35% | 9.0728% | 1.51x short |
| **PROMOTER sells** | **12,829** | **116** | **22.64%** | **7.5268%** | **1.25x short** |
| promoter buys ≥ ₹1cr | 7,883 | 116 | 31.94% | 8.9928% | 1.50x short |

**Promoter sells at 1.25x is the closest anything in this project has come**, against
bulk buys at 2.22x, consensus at 1.94x and disclosed selling at 1.95x.

And unlike those, the gap is closeable. MDE falls as 1/√cohorts, so 1.25x needs
1.56x more cohorts: **116 → 181 months, about five more years**, against seventy
for consensus. The binding constraint is that insider data starts in 2016, not
that the events are too few.

## The source is live, and the predecessor's own notes are why we know

`/api/corporates-pit` answers **HTTP 200 with `{"acqNameList":[],"data":[]}`** —
a valid empty envelope. MICC's `insider_trading_fetch.py`, recovered from the
bundle 0042 salvaged, records why:

> *NSE retired /api/corporates-pit around late April 2026: the old path still
> answers HTTP 200 with a VALID EMPTY envelope, which made this fetcher go
> silently green-but-empty for ~2 months.*

The live route is **`/api/corporates-pit-gg`**: verified 2026-09-01 at 344,173
bytes, 644 filings and 231 symbols in one month, each carrying a
`broadcastDateTime` to the second and an XBRL detail file that fetches 200 and
contains `CategoryOfPerson`.

**That timestamp matters beyond this study.** `available_from` is LOW confidence
on 5,742 of 5,877 eligible deals because publication time is assumed. Insider
filings publish their own broadcast time, so this event class would be HIGH
confidence from the first collected row.

## Decision

**Insider trading becomes a candidate study**, and the collector for
`corporates-pit-gg` is the next thing built. Nothing is registered yet and
nothing here is a finding.

## What would reverse this

The bound question in 0044. At 1.25x short, promoter sells is the study most
sensitive to whether [0011](0011-plausible-effect-bound.md)'s 0.5%/month is
right — a modestly larger bound makes it registrable today, and a smaller one
puts it back with the others.

## Cost accepted

- **This is a fifth study and the trial counter must charge for it.**
  [0022](0022-multiplicity-had-three-errors.md) and
  [0023](0023-trial-families-and-track-s-wiring.md) exist so that widening the
  search is paid for; finding a better-powered population by looking at five
  instead of four is exactly the multiplicity this project corrects for.
- **The five populations above were selected after seeing their power.** They
  are power figures, not effects, so no outcome was observed — but a
  registration must disclose that the population was chosen this way.
- **`quantity` is 0 on 119,112 of 120,765 insider sell rows** in the seed, so
  size filters on the sell side must key on `value`. Unexplained, and it means
  the seed's insider data is not uniformly clean.
- **Insider data starts 2016**, so it cannot use the 2005-2015 price history
  that makes the bulk studies' 232 cohorts possible. Half the warehouse is
  unusable for it.
