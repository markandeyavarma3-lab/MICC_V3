# 0070 — Nothing watched whether the pipeline ran, and the email never worked

**Date:** 2026-09-16
**Decided by:** Me. The owner asked how they would know what is going on. The
answer was "you would not", and these are the three reasons.
**Status:** accepted
**Related:** 0053 (acknowledged gaps; the email leg was added there), 0055
(char_panel staleness), 0068 (the September stage failures).

## 1. Staleness was watched. Execution was not.

`health.py` answers *is the data stale?* and has answered it well — every
archive gap since 2026-09-03 was reported. It does not answer *did the pipeline
run?*, and nothing else did.

Measured cost: `src.research.charmatch` raised a foreign-key error on **twenty
consecutive scheduled runs** (2026-09-11 → 2026-09-16). The only signal was one
line, `COLLECT: one or more stages FAILED`, in `logs/launchd_collect.err` — a
file with no reader. Every feed was current the whole time, so every
staleness check was green while the characteristic panel refroze and
CHAR_MATCHED quality degraded daily. The mart's foreign-key failure before it
ran the same way for five days and cost 767 deals their place in the mart.

`RC=1` said *something* broke. It never said *what*. `collect_daily.sh` now
accumulates `FAILED_STAGES` and hands the names to `src/monitor/stage_alert.py`,
which reuses the channels health.py already has rather than adding a second
thing to configure and a second thing to go quietly missing.

The message distinguishes the two kinds of failure, because they need different
reactions:

- **COLLECTION** (`exit`, `prices`, `bhavcopy`, `corpact`, `derivatives`,
  `insider`) — data may not have been fetched, and `nse_bulk_deals`,
  `nse_block_deals` and `fii_dii_cash` are rolling endpoints recoverable only
  until the file turns over. **Re-run now.**
- **PROCESSING** (everything after) — the bytes are on disk, the next run
  retries, nothing is lost. Act only if it repeats.

## 2. The email has never worked, and it was not the credentials

`notify_email` connected with `SMTP_SSL(host, 465)`. Measured on this machine:

```
smtp.gmail.com:587   reachable in 0.0s
smtp.gmail.com:465   TimeoutError: timed out
```

**Implicit-TLS 465 is blocked on this network.** Every stale-source and backup
email since the leg was added has failed at the socket, reporting
`email FAILED: TimeoutError` — which reads like a wrong app password and is
not one. The desktop notification worked throughout, which is why nobody
chased it: alerts appeared to be firing.

587/STARTTLS is now tried first, 465 second, and the **last** error is reported
so a genuine auth failure still surfaces as one rather than being masked by a
timeout. The transport is named in the result (`sent to … via 587/starttls`) so
a fallback that saves the day is visible. Verified with a real send.

## 3. Three reports, and none answered the question

`HEALTH.md` (is data stale), `STATUS.md` (which steps are built) and
`DATA_INVENTORY.md` (what is on disk, and is it wired) are each correct and each
answer a question nobody asks at 9am. The question is *did last night work, and
is anything rotting* — which needs one line from each, plus the thing none of
them tracked: whether the pipeline ran.

`src/monitor/digest.py` prints that in one screen: last four runs with the
stages that failed, sessions held per feed over seven days, staleness per
source, backup state, and where to look for more. Emailed from the **08:30 slot
only** — a digest that arrives twice a day is a digest that gets filtered.

Two defects were found writing it and are pinned: it reused
`SourceHealth.render()`, which returns a **markdown table row** shaped for
HEALTH.md and printed `| \`nse_bulk_deals\` | … |` into a terminal; and a stage
echoed twice in one run was counted twice, so `mart, mart` read as two failures.

## What would reverse this

The stage alerter becoming noisy — if a stage fails routinely for a reason
nobody intends to fix, it belongs in an acknowledged list the way lost sessions
do, not in a daily email. Watch for that before it trains the reader to filter.

## Cost accepted

No trials. Nothing here measures an effect.
