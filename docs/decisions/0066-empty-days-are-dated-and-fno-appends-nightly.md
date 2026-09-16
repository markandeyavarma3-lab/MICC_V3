# 0066 — Empty block days are dated; F&O appends on the collect path

**Date:** 2026-09-16
**Decided by:** Owner, on the 09-16 08:30 run's health output and
`handover_delta5/14_BLOCK.md` (diagnosis only, that morning).
**Status:** accepted
**Related:** 0053 (a false "LOST" trains the reader to ignore the alert),
0064 (the spine registers on the path the collector calls), 0065 (history
landed once, by hand).

## Context

**1a.** `nse_block_deals` had read STALE since 09-11 with "3 MISSING behind
it". The archived bytes showed why: NSE served its `NO RECORDS` sentinel on
09-07, 08, 09, 10 and 15 — days with no block deals — while `bulk.csv` on the
same host was fresh each time. Nothing was missed. But `stopgap.capture`
deduped on sha256 *before* classifying, so only the first fetch of each
sentinel byte-variant (08-25 unquoted, 09-07 quoted) was ever `EMPTY_DAY`;
every later empty day was `DUPLICATE` with `session=None`, and
`health.read()` credits an empty answer only from an `EMPTY_DAY` row. The
alert grew by one session per quiet day and was wrong every time.

**1b.** 0065 landed 21 archived F&O sessions and 56 participant-OI sessions
by hand with a full `spine.build(FNO)`. `collect_daily.sh` archives both
feeds nightly (`derivatives` stage) and landed neither, so on 09-16 the
spine was one session behind again and would stay so. A nightly full
rebuild is a minute of disk and CPU to reproduce 174.3M unchanged rows —
the reason the script had declined to rebuild F&O daily since 0055.

## Decision

**1a. An empty day is a dated fact, every day.** `capture(src,
session_hint)` classifies the sentinel as `EMPTY_DAY` *before* the dedupe
and credits it to `session_hint` — the session the run's dated source
(`bulk.csv`) resolved to, which `main()` now threads through the loop. The
bytes are still written once (a second identical sentinel reuses the
archived path); the manifest row is dated `EMPTY_DAY` regardless. With no
hint (bulk failed) the row stays undated rather than guessing.
`health.read()` needed no change: a dated `EMPTY_DAY` row already lands in
`held` and advances the feed's last session.

**1b. F&O appends nightly through the spine's own machinery.**
`spine.append_sessions(spec)` takes the collected sessions newer than the
spine's last date and rewrites only the year partition(s) they fall in,
under the same lock as a build, refusing if a collected session on or
before the last date is absent from the spine (a hole only a full build can
fill) or if the merged partition violates the unique key; the whole spine is
then re-registered by data checksum (0064). `python -m src.ingest.fno
--append` lands new UDiFF and participant-OI sessions and calls it;
`collect_daily.sh` runs that as a new `fno_land` stage immediately after
`derivatives`. `--build-spine` (0065's full rebuild) remains for a
one-off; the two flags are mutually exclusive.

Tests: `tests/test_stopgap_empty_day.py` (six; three watched failing
unpatched, three pin unchanged dedupe behaviour) and
`tests/test_spine_append.py` (seven; synthetic partitioned spine, throwaway
ledger, wiring order pinned on the script).

## Why

**Classify before dedupe.** Dedupe answers "have I archived these bytes?";
classification answers "what did the exchange say today?". Two identical
sentinels on two days are one file and two facts. Ordering them the other
way collapsed the second fact into the first.

**Date from the run, not the calendar.** The sentinel carries no date and
the rolling file rolls on publish, not on the clock (0063). The only honest
witness in the same run is the dated file the same host served seconds
earlier; that is what `bulk.csv` is used for.

**Append a partition, not rebuild a spine.** The alternatives were a
nightly full rebuild (rejected above) or leaving the land manual (the
condition that produced today's staleness). Rewriting one year's file
keeps every guarantee of the full build that matters — key uniqueness,
no holes, one writer, registration — at the cost of one partition's I/O.

**Refuse rather than fill around a hole.** If a collected session older
than the spine's last date is missing from the spine, the append cannot
know why. It stops and names the full build. Quietly appending the newer
sessions would leave a gap that reads as a holiday.

## What would reverse this

- `bulk.csv` and `block.csv` ceasing to be served from the same host or
  ceasing to roll together; then the hint is wrong and the empty day
  should be dated from the price calendar instead.
- A year partition growing large enough that rewriting it nightly costs
  what a full build costs (~250 sessions × ~35k rows is 9M rows; fine).
- `_collected_part` or the unique-key check finding the append and the
  full build disagree on the same collected files. They share `_select`
  and the spec; a divergence is a bug in one of them.

## Cost accepted

`fno_land` is a new stage that can go red and set `RC=1` — on a parse
error, a hole, or a duplicate key. That is the point: the spine going
stale silently was the failure mode; the stage failing loudly is the fix.
The stage opens the research DB read-write for the participant-OI insert,
sequentially with the rest of the script; 0059 removed the only concurrent
writer.

No trials. Nothing here estimates anything.
