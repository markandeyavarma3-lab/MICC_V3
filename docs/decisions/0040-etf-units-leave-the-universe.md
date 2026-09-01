# 0040 — ETF and fund units leave the universe

**Date:** 2026-09-01
**Decided by:** Owner, presented with three options and the measured cost of each
**Status:** ACTIVE — extends [0015](0015-rights-entitlements-excluded.md)

## Context

Extending the price spine past 2026-08-14 exposed 22 price discontinuities
greater than 35% in the spliced tail. Eleven were corporate actions confirmed
independently by the NSE actions API, at the same ex-date and the same ratio.

Seven were not confirmed by anything, and they had a pattern:

| symbol | jump | ISIN | instrument |
|---|---:|---|---|
| PSUBANK | 0.1037 | INF174KA1A86 | Kotak PSU Bank ETF |
| GOLDADD | 0.1004 | INF740KA1ZP2 | DSP Gold ETF |
| SILVERADD | 0.1016 | INF740KA1ZQ0 | DSP Silver ETF |
| IVZINNIFTY | 0.1007 | INF205KA1CC7 | Invesco India Nifty ETF |
| HEALTHADD | 0.1026 | INF740KA1ZG1 | DSP Healthcare ETF |
| MIDQ50ADD | 0.0998 | INF740KA1ZF3 | DSP Q50 ETF |
| NV20 | 0.0012 | INF174KA1ZE1 | Kotak NV20 ETF |

All seven are clean 1:10 unit splits with **no record in the corporate-actions
API**, because `index=equities` does not cover fund units. They are precisely the
rows that cannot be adjusted and cannot be verified.

They also buy nothing. Measured on `institutional_deals_clean`:

| ISIN prefix | instrument class | deals | **eligible** |
|---|---|---:|---:|
| INE | equity shares | 206,153 | 5,738 |
| IN9 | see below | 319 | 4 |
| INF | fund and ETF units | 174 | **0** |

## Decision

**Instruments whose ISIN does not begin `INE` leave the universe.**
`src/ingest/bhavcopy.py` collects prices only for `INE` instruments.

## Why

The exclusion costs **zero eligible research events** and removes seven
unadjustable discontinuities from the adjusted spine. That is not a trade-off.

Keying on the ISIN prefix rather than the symbol is the part worth defending.
Indian ISINs encode instrument class in their first three characters by registry
rule — `INE` equity, `INF` mutual-fund and ETF units — so it holds where a
name heuristic would not. Nothing about the strings "PSUBANK" or "NV20" says
fund, and a suffix rule keyed on "ETF" or "BEES" would have missed every one of
the seven above.

The thesis is about disclosed institutional activity in **companies**. A bulk
deal in a gold ETF is a fund flow, not a signal about an issuer, and it has no
issuer-level characteristics for the DGTW matching in Plan 2 to match on.

Rejected: hunting for an ETF corporate-actions route. It may exist, but it would
be work spent making a class of instrument tradable-in-principle that contributes
zero eligible events and does not fit the thesis.

Rejected: keeping them unadjusted and flagging them. That is knowingly leaving
rows in the warehouse that read as -90% returns, protected only by a flag every
future query would have to remember to honour.

## What would reverse this

A study whose subject is fund flows rather than issuer information — ETF
creation and redemption around index events is a real question, and it would
need exactly these rows. It would also need its own price adjustment, which is
the work deferred here rather than done.

## Cost accepted

- **The universe is now inconsistent across 2026-08-14.** Sessions before it came
  from MICCV2 and contain fund units; sessions after it do not. An ETF's series
  simply stops. The deals side is unaffected — those 174 rows were already
  ineligible — but a query that reads the price spine directly and does not
  filter will see a universe that changes shape at that date.
- **`IN9` is unexamined.** 319 deals, 4 of them eligible, and this decision does
  not cover them: `IN9` is not the equity prefix, so those four are now excluded
  as collateral. Four events is small enough not to chase today and large enough
  that pretending it was deliberate would be dishonest.
- Two symbols in the price data are excluded that a human would call equities if
  they only read the ticker. The ISIN is right and the intuition is wrong, but
  the rule is now invisible unless someone reads this file.
