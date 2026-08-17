# 0007 — Ship a stopgap archiver before any other work

**Date:** 2026-08-17
**Decided by:** Claude, recommended; Owner approved
**Status:** ACTIVE

## Context
`nsearchives.nseindia.com/content/equities/bulk.csv` is a rolling current-day
file. `/api/historical/bulk-deals` answers 503. No collector has ever existed in
this project or its predecessor. The hole runs from 2026-07-09 — about 27 sessions
— and every further uncollected session is lost permanently.

## Decision
~200 lines that fetch, sha256, write-once gzipped, and append a manifest line.
No parsing, no database, no symbol resolution. Cron at 20:00 and 22:30 weekdays
plus 08:00 Mon–Sat.

## Why
The real collector is one to two days of work. This is what makes those two days
cost nothing. Captured on the first run: BULK 100 rows, BLOCK 4 rows, FII_DII
JSON — verified by sha256 round-trip after a clean re-run.

The 08:00 slot is a genuine catch-up rather than belt-and-braces: NSE publishes
around 19:00 and does not republish, so at 08:00 the endpoint still serves the
previous session.

## What would reverse this
Cracking the historical endpoint, which would make missed days recoverable and
demote this from urgent to convenient. ~7 hours of the 8-hour spike budget remain.

## Cost accepted
Archived bytes are unparsed. If the schema is misunderstood later, the bytes are
still there — which is the entire design.
