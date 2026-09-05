# 0053 — An alert that cannot be cleared, and a retention policy that never ran

**Date:** 2026-09-05
**Decided by:** Me. The owner asked what to do next; I ran the monitoring
before proposing anything and found both of these in its output. Neither was a
question for the owner — one was a defect, the other was a defect wearing a
guard.
**Status:** accepted
**Step:** Plan 1 step 1.10, Plan 3 step 2.13.

## Two failures, opposite directions, same consequence

This project's standing pattern is *the signal existed and nothing carried it*
— the retired endpoint answered 200, the truncated tar exited 0, `collect_daily.sh`
returned 0. Both findings here are that pattern, reached from opposite sides.

### 1. The alert could never be cleared

Gap detection landed 2026-09-03 (0047) and correctly found three permanently
lost sessions. It then **alerted on them by email on every run** — three times
a session, indefinitely — for sessions that are unrecoverable by construction:
`/api/historical/bulk-deals` answers 503, which is why Plan 3 steps 2.4 and 2.5
are graded IMPOSSIBLE.

The terminal made it worse by printing:

```
STALE  nse_bulk_deals     last 2026-09-04  0 session(s) stale
```

The flag came from `alerting`, which the gaps triggered. The number came from
`sessions_stale`, which was zero. **Two conditions, one line, no way to tell
them apart** — and the line said the source was stale when it was current.

An alert nobody can act on is an alert that gets filtered. This project lost
2026-08-19 because a signal reached nothing; a channel that is permanently red
arrives at the same place by a different route.

**Fix.** `sources.yml` gains `acknowledged_gaps` — session, date acknowledged,
and a reason, one entry per loss. An acknowledged gap stays visible in
HEALTH.md (`1 lost (acknowledged)`) and stops paging. An unacknowledged one
still pages. The default is to alert, because forgetting to acknowledge is
merely noisy and forgetting to alert is not.

A test asserts every entry carries a reason over 40 characters, and another
asserts every acknowledged session **is a gap health actually observes** — a
stale acknowledgement would silence a future loss on that date.

### 2. Retention had never run once

`prune_generations.zsh` was extracted on 2026-09-01 specifically so it could be
tested, and it has seven tests. It logged this on **every scheduled run** from
2026-09-01 to 2026-09-05:

```
prune: skipped — destination lists no generations
```

while eleven bundles sat in the destination, and while the **next line of
backup.sh ran `du` on that same directory successfully**. The destination is an
iCloud FileProvider volume and the prune reads it microseconds after `mv`. The
script's own header predicted this as defect 3 and treated it as occasional. It
was universal.

The guard behaved perfectly — an untrustworthy listing authorised no deletes,
so nothing was ever at risk. That is exactly why it went unnoticed for four
days: **a retention policy that silently does nothing is indistinguishable from
one that has nothing to do.** 11 generations, 772 MB, growing ~75 MB a day.

**Fix.** Wait for the listing instead of trusting the first look, with the
just-written generation as the readiness signal — the same anchor defect 3
already established as the trust condition. Ten attempts, 0.5s apart. If it
never appears, refuse exactly as before.

## What the tests did and did not catch

The seven existing prune tests run against a local `tmp_path`, where a file
written on one line is visible on the next. **They could not observe the
production failure, which was a timing property of the caller against iCloud.**
They passed throughout.

They did catch two bugs I introduced in the fix:

- `(( attempt++ ))` yields the value *before* the increment. On the first pass
  that is 0, zsh treats an arithmetic 0 as a failed command, and `set -e` killed
  the script — status 1, no output, both the skip and refuse branches
  unreachable. The file exists because silent retention failure is invisible,
  and the retry loop reintroduced precisely that.
- `${bundles[(r)needle]}` raises *parameter not set* under `set -u` on a miss —
  on the refusal path, the one that protects the backups. `(Ie)` yields an index
  or 0 and is the idiom already used lower in the same file.

## Two tests that were green and proved nothing

Both were mine, both found by perturbing the code and watching for a failure
that did not come.

- `test_a_hole_behind_the_latest_session_is_detected` asserted `bulk.alerting`
  on a fixture three weeks in the past. Once acknowledgement landed, that
  assertion held on **staleness alone** and would have passed with gap detection
  deleted outright. It now asserts `open_gaps`.
- `test_an_acknowledged_gap_stops_paging_but_stays_visible` asserted
  `open_gaps == ()` but never that the email stops. Reverting `alerting` to the
  old behaviour left it green. It now asserts `not bulk.alerting`, on a fixture
  dated near today so staleness cannot supply the answer.

## What would reverse this

For the acknowledgement list: any of these sessions becoming recoverable — a
working historical route would make each entry a bug rather than a record. For
the prune: if the retry proves insufficient in production, the ordering is
wrong rather than the timing, and the prune should move to the *start* of the
next run, where the previous generation is long since settled.

**The prune fix is not yet confirmed in production.** It is verified against
fixtures and the three branches were run by hand. The next scheduled backup is
the real test, and it should reduce 11 generations to 3.

## Cost accepted

No trials. Neither of these touches an effect estimate.
