# 0079 — NSDL daily FPI flows, back to December 1998

**Date:** 2026-09-29
**Decided by:** Owner ("yeah lets start"), after asking whether FII/DII cash
flows before August 2026 could be had at all.
**Status:** accepted
**Related:** 0078 (the evening schedule this stage runs in), sources.yml
`fii_dii_cash` (the NSE series this extends backwards on the foreign side).

## Context

The project's only institutional cash-flow series was NSE's
`fiidiiTradeReact`, which serves today's figure and nothing earlier: 68 rows
inherited from V1 (June–July 2026) and the sessions collected since August.
sources.yml recorded the history as "unobtainable retrospectively", and on
that basis Engine E (flow-driven studies) was out of scope.

NSDL, the depository that holds FPI securities, publishes its own daily series
on the FPI Monitor site. Its archive page is an ASP.NET form: a date in the
hidden field `hdnDate`, posted back with `__EVENTTARGET=btnSubmit1`, returns
every reporting day of that date's month. Probed 2026-09-29, a few requests
three seconds apart:

| asked for | answered |
|---|---|
| 31-Jan-1993, 31-Jan-1997, 31-Mar-1998, 30-Sep-1998 | empty |
| 31-Dec-1998 | 31-Dec-1998 only — the first reporting day |
| 31-Jan-1999 onward | every month, through today |

## Decision

Archive every month from December 1998 as raw pages, and parse them into two
tables:

- `collected/fpi_nsdl/fpi_investment.parquet`: per reporting day, category
  (Equity, Debt and its later limits, Hybrid, Mutual Funds, AIFs, Total) and
  route (stock exchange / primary market / sub-total, from about 2009), with
  gross purchases, gross sales, net in Rs crore and US$, and the day's rate.
- `collected/fpi_nsdl/fpi_derivatives.parquet`: per reporting day and
  product, contracts and value bought, sold and open at the day's end.

The collector (`src/archive/fpi_nsdl.py`) asks for each month by its last day,
or by today in the current month, and refuses a page whose own header names a
different date. A page "up to the 25th" is never filed as the whole month. The
daily stage re-fetches the current and previous month, which NSDL is still
filling in and may revise, plus at most four older months not yet held, with
a five-minute cap.

## What the data does and does not give

**Foreign flows, yes; domestic, no.** NSDL covers FPIs only. No official
archive of daily DII flows has been found; that side still accrues forward
from NSE.

**Point in time.** NSDL's reporting date is the day custodians reported the
trades, which the page itself describes as the day after the exchanges'
provisional T-day figure. A flow reported on D was not public before D, and
describes trading on or before D−1. A study using it enters no earlier than
the session after the reporting date. This is written into the collector's
and the parser's docstrings and into sources.yml, where a registration will
find it.

**Checked, not assumed.** In September 2026, stock-exchange plus primary
market equals the sub-total on 108 of 108 category-days. In January 2010 the
only differences are ±0.1, which is NSDL's own one-decimal rounding.

## What would reverse this

- NSDL changing the form or retiring the archive page: `verify()` refuses
  anything that is not the report for the date asked, so this shows up as
  FAILED rows, not as silently wrong data.
- A licence or robots change on fpi.nsdl.co.in that disallows automated use.

## Cost accepted

About 670 requests for the one-time backfill (a form load and a post per
month, three seconds apart), then two to six months a day.

## Power, measured the same day

`python -m src.research.fpi_power` (dispersion and n only; the flow amounts
are never read, 0035) against the NIFTY 500 total-return index, entered the
session after each reporting date: **UNDERPOWERED at every horizon, 4.2x to
4.9x short** of the 0.5%/month plausible bound. One month: MDE 2.33% against
0.50%, on 332 monthly cohorts. The series is one market observed about 330
independent months; the market's own month-to-month swing (6.1%) is several
times any plausible flow effect. Detecting one would take about 22x more
independent months. `docs/reports/FPI_POWER_PRELIMINARY.md`.

This is not a verdict on FPI flows — no study was run — only on whether a
market-timing study on this series could be answered. It cannot, on its own.
