# 0059 — Two sessions lost to a shutdown, and one scheduler where there were two

**Date:** 2026-09-15
**Decided by:** Owner, on a handover audit's findings (`handover_delta2/`,
`handover_delta3/`). The gap acknowledgement is a record of fact; the
scheduler change is the owner's call, executed 2026-09-15 10:27 IST.
**Status:** accepted
**Supersedes:** the "CRON IS DELIBERATELY LEFT IN PLACE" rationale in the
header comment of `scripts/com.institutional-research.collect.plist`. The
plist itself is unchanged; only the crontab was emptied.
**Related:** 0053 (acknowledged gaps), 0055 (`land → identity → mart` added
to the collector; launchd cannot enumerate iCloud).

## Context

The machine was shut down on Friday 2026-09-11 at 17:19 IST and not booted
again until Tuesday 2026-09-15 at 09:33 IST (`last`: `shutdown time Fri Sep
11 17:19`, `reboot time Tue Sep 15 09:33`). NSE publishes bulk and block
deals around 19:00 IST as a rolling current-day file; the historical route
answers 503. Every slot that could have captured Friday's and Monday's files
— Fri 20:00, Fri 22:30, Sat 08:00, Mon 20:00, Mon 22:30, Tue 08:00 — fell
inside the powered-off window. launchd's `StartCalendarInterval` replays a
slot missed during *sleep*; it does not replay across a *shutdown*, and the
rebooted job reports `runs = 0`. Verified absent: no `*20260911*` or
`*20260914*` file under `data/raw/archive/{BULK,BLOCK,FII_DII}`, no manifest
entry for either session, 0 rows in `institutional_deals_raw` and
`institutional_deals_clean` for either date.

Separately, the September log shows that on every scheduled slot two
`collect_daily.sh` processes started within 0–17 seconds of each other
(`--- 2026-09-10 20:00:00 IST pid=46305` / `--- 2026-09-10 20:00:04 IST
pid=46311`, and the same at 22:30). cron and launchd were both registered for
the same three minutes. That was a deliberate belt-and-braces choice made
when the script only archived and a duplicate was a free sha256 no-op. 0055
then added `land → identity → mart → outcomes` and the spine rebuild to the
same script. Those open DuckDB read-write, so the second process of each
pair failed on `Conflicting lock is held` — on `research_prod.duckdb` and
on the spine parquet files, once as a torn read (`too small to be a Parquet
file`). One of the pair always finished, so the mart was never wrong; but
every run reported `RC=1`, which made the real failures indistinguishable
from the manufactured ones.

## Decision

1. `nse_bulk_deals`, `nse_block_deals` and `fii_dii_cash` for sessions
   **2026-09-11** and **2026-09-14** are acknowledged as permanently lost in
   `configs/sources.yml` `acknowledged_gaps`, six entries, in the exact shape
   of the 2026-08-19 / 2026-08-27 entries. Prices and bhavcopy for both dates
   are *not* acknowledged: those archives are dated and will backfill on the
   next successful run.
2. **cron is retired. launchd is the only trigger for `collect_daily.sh`.**
   The three crontab lines were removed (previous crontab preserved verbatim
   at `handover_delta3/crontab.bak`; a comment-only crontab explains why).
   The launchd plist was not edited, not reloaded, not started. Verified:
   zero active cron lines, one launchd job, 16 calendar triggers intact,
   only one file under any `LaunchAgents`/`LaunchDaemons` references the
   script.

## Why

**The gaps.** The same reason as 0053: a loss with a date and a reason
written down stays visible in HEALTH.md and stops paging; a loss without one
alerts forever and gets filtered. There is no recovery route — the rolling
endpoint has advanced and the historical one returns 503 — so an entry is
the only honest artefact. Both days are in one record because they have one
cause.

**One scheduler.** The belt-and-braces argument was correct for what the
script did in August and wrong for what it does now. Two schedulers that
both no-op are harmless; two schedulers that both write are a race, and the
race was being won by whichever process got the lock first while the other
wrote a traceback and set the run's exit code. launchd is kept rather than
cron because it is the one correctly pointed at this checkout, it is the
one with the sleep-replay property the design wanted from the start (Plan 3
Phase 2.9), and — decisively for a change made hours before the next slot —
retiring cron touches nothing that could arm a second launchd trigger
tonight. The rule applied was the audit's own: if unsure whether a change
fires twice, leave launchd as-is and disable only cron.

## What would reverse this

For the gap entries: a working historical route for bulk/block/FII-DII.
Each entry would then be a bug to fix rather than a record to keep, exactly
as 0053 says of its own.

For the scheduler: launchd failing to fire on a machine that was awake at
the slot. The first test is tonight — Tue 20:00 and 22:30 IST, then Wed
08:00. Expect one `--- 2026-09-15 20:00` header in `logs/collect_2026-09.log`,
not two, and no `Conflicting lock is held` after it. If launchd does not
fire at all with the machine awake, the answer is to fix launchd, not to
re-add cron; a second scheduler is how this started.

What would **not** reverse it: another shutdown. That loses sessions under
any scheduler. The mitigation for that is operational — the machine stays
on through 22:45 IST on trading days — and is written in
`handover_delta3/04_TONIGHT.md`, not in code.

## Cost accepted

Two cash-flow sessions, unrecoverable. On a corpus of 239,480 raw rows two
sessions are roughly 0.1% by count; the cost is not statistical, it is that
the collector's own guarantee — every traded session either archived or
acknowledged — was breached by the machine being off, which no code change
here prevents.

No trials. Nothing here touches an effect estimate, a study module, the
identity layer, or the mart.
