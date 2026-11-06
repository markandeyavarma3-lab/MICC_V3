# 0097 — The 2026 F&O hole is filled from the salvaged bhavcopies

**Date:** 2026-11-06
**Decided by:** Owner asked for every blank that can be filled to be filled
("lets try to extract each and every data"). The audit and the method are mine.
**Status:** ACTIVE
**Related:** 0065 (landing collected F&O), 0066 (append_sessions), 0027 (the seed),
`src/ingest/fno.py`.

## What was found

`fno_spine` has no session from 2026-01-01 to 2026-06-16: 110 trading sessions. The
seed resumes on 2026-06-17 and the V1 increment stops at 2025-12-31 before picking
up again in July, so nothing feeds those months. No check noticed, because a spine's
checks look at its keys and its last date, not at holes in the middle.

`data/raw/salvaged/v1_raw/nse_fo` holds NSE's own raw bhavcopy for exactly those 110
sessions. A dry run parsed all of them through the collector's parser: 48,60,684 rows,
35,244 to 54,042 a session, each file's own date matching its name.

## What changed

- `src.ingest.fno --salvaged --build-spine` lands those 110 sessions into
  `collected/fno` and rebuilds the spine from zero, re-registering it.
- Landing them is refused without the rebuild. They are older than the spine's last
  date, so `append_sessions` raises until a full build has taken them in, and on their
  own they would stop the collector's F&O stage that night.
- The 2026-06-17 to 07-07 stretch with raw UDiFF codes (0062, 0065) is untouched.

- The Phase 1 reconciliation's frozen F&O count stays 174,272,768. Those 110 sessions
  fall inside its date range, and they raised the count by exactly the 48,60,684 rows
  landed. The figure is not edited: the measurement now leaves them out by name
  (`reconcile.FNO_NOT_FROM_MICCV2`), the same scoping the horizon already uses, and a
  new test checks them row for row against their files.

## Why

The bytes are the exchange's and are already held; the parser is the one every
collected session goes through. Nothing is estimated.

## What this does not change

No registered experiment is re-run and no result restated. The spine's checksum
changes, as it does on any night a session is appended, so the DAG records the new
artefact and its parents.

## What would reverse this

A defect found in those files: delete the 110 `date=` files from `collected/fno` and
rebuild.

## Cost accepted

- About 49 lakh more rows on disk.
- The reconciliation gate names a window it does not measure. A wrong date range there would hide rows, so the window is exact and the row-for-row test stands behind it.
- One full spine rebuild, run outside the collector window.
