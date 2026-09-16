# 0068 — The figures restated under `security_id`, and one inconsistency reopened

**Date:** 2026-09-16
**Decided by:** Me, closing the re-measurement that
[0061](0061-studies-join-prices-on-security-id.md) deliberately deferred. 0061
changed how returns attach to events and refused to re-pin without a record of
its own — this is that record. The owner's instruction was to find out why the
collectors were "not working at all"; four of the failures turned out to be
these stale pins, and the other three were real.
**Status:** accepted
**Related:** 0055 (the last restatement), 0061 (the join change), 0064 (spine
checksum on the collect path).

## 1. What was actually broken, and what was not

The launchd error log carried "one or more stages FAILED" on **every run since
2026-09-11**. Measured stage by stage, the collectors were **not** the problem:

| stage | state | note |
|---|---|---|
| prices / bhavcopy | **working** | 4 FAILED sessions (09-02, 09-07, 09-08, 09-10) all later STORED; the spine has every trading day through 09-15 |
| deals (bulk / block / fii_dii) | **working** | through 09-15 |
| derivatives (participant_oi, F&O) | **working** | 21 sessions each, through 09-15 |
| spine → land → identity → mart → outcomes | **working** | all `=0` |
| **charpanel** | **FAILED every run** | FOREIGN KEY — fixed below |
| health | failing | cascade from backup AT RISK |
| backup | failing | `rm: Operation not permitted` under launchd — owner said leave it |
| insider | partial | 1 of 2 windows fails; 840 filings indexed |

**The one real collector outage** was 2026-09-10 22:30 → 2026-09-15 20:31: the
machine was shut down ([0059](0059-two-sessions-lost-to-a-shutdown-and-one-scheduler.md)).
[0063](0063-one-session-recovered-one-was-a-holiday.md) recovered 09-11 from
the rolling file and found 09-14 was a holiday; only `fii_dii_cash` 09-11 is
lost.

`fred_dgs10` / `fred_vixcls` FAILED ×3 are **manual probes** from
`src/archive/probe.py`, not scheduled feeds; FRED answered in ~1s when re-probed
today. The 09-15 timeouts were transient.

## 2. charpanel: the parent edge pointed at a hash that was never registered

`charmatch.build_panel` computed `data_checksum(price_spine_adj)` and registered
`warehouse:char_panel` with an `input` edge to it. The spine build registers its
own artefact under a **file-level** hash — `4a8ca804…` — not the content
checksum `22b486ca…` that charmatch computes. The edge pointed at nothing, the
FOREIGN KEY failed, and the panel that 0055 had just un-frozen froze again for
five days while the log said FAILED twenty times.

Fix: charmatch registers the parent itself, idempotently, before registering
the child. The error message said exactly this: *"register inputs before the
things derived from them."*

## 3. Three block-deal gaps that are not gaps

Health reported `nse_block_deals` MISSING on 09-08, 09-09, 09-10. Every fetch
on those days returned the **identical** empty file (`sha ec820a0b`, rows=0).
Measured against the trailing year: **94 of 226 trading days had zero block
deals — 42%.** Three consecutive empty days is ordinary. The file carried no
session date, so health could not count it as "asked and got nothing".
Acknowledged in `sources.yml`; [0066](0066-empty-days-are-dated-and-fno-appends-nightly.md)
dates empty files from 09-15 onward, though the 09-16 morning record was still
`session=None` — that fix has not reached the collect path yet.

## 4. fno_spine: the bound, not a new number

Commit 891a905 landed 21 sessions of collected UDiFF F&O and `fno_spine` grew
174,272,768 → 174,973,029. The reconciliation pin is a **seed** figure (0029).
`price_spine` already bounds its count to `MICCV2_HORIZON` so collected rows
cannot move a frozen pin; `fno_spine` was exempt only because nothing had ever
appended to it. Bounded to 2026-08-14 the count is **exactly 174,272,768**. The
bound is applied; the number is untouched.

## 5. The restatement 0061 deferred

0061 moved `_returns_sql` from `PARTITION BY symbol` to `PARTITION BY
security_id`. 331 spine symbols were recycled across companies and 275
securities renamed; a symbol window ran one company's last rows into the next's
first. Every figure moves. **No verdict changes.**

| figure | 0055 | **now** |
|---|---|---|
| 21s MDE | 2.1334% | **2.1214%** (4.24× short) |
| 63s MDE | 4.6715% | **4.3997%** (2.93× short) |
| 252s MDE | 11.5374% on 4,673 | **10.8496% on 4,630** (1.81× short) |
| EXPLORE sell baseline | n=1,115, −22.68% | **n=1,080, −20.49%** |
| liquidity: top100 / top500_ex100 / off500 | −17.09 / −25.09 / −54.66% | **−16.56 / −20.24 / −52.74%** |
| promoter buy 12m | 24,169, MDE 8.06% | **23,616, MDE 7.92%** |
| promoter sell 12m | 12,231, MDE 7.81% | **11,972, MDE 7.95%** |

The gradient still runs the wrong way; nothing is powered; 0051/0056/exp_002
verdicts stand.

## 6. Reopened: the mixed state 0055 closed

0061 moved the **market leg** to `security_id` and noted that `confounds`,
`insider_power` and `delisting` still join their **event side** on the string.
The consequence is measurable today: `confounds` reports the EXPLORE population
as **1,080** while `delisting` — which keeps its own symbol-partitioned
classifier — reports **1,115**. Two modules that 0055 forced into agreement
disagree again by 35 events.

This is not fixed here. The migration is another session's in-flight work, the
owner's question was about the collectors, and half-finishing someone else's
join change is how a third inconsistency gets introduced. It is recorded so the
next person to touch those three modules knows the two numbers should match and
currently do not.

## What would reverse this

The event-side migration completing, which will move `delisting` to 1,080 (or
both to a third number) and should be the next restatement.

## Cost accepted

No trials. Re-measurement of already-charged figures under a corrected join.
