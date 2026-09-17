# 0073 — Nothing was at risk, and three channels said otherwise

**Date:** 2026-09-17
**Decided by:** Me, after the owner forwarded the morning's Telegram reports and
asked "is there anything wrong?" and then "fix all those".
**Status:** accepted
**Related:** 0070 (stage alerts), 0071 (run report, Telegram), 0060/0072 (the
slots and why the morning one exists), 0053 (the August DNS failure this one
repeats).

## What the owner saw at 08:37 IST

```
COLLECTION FAILED: exit
  Rolling NSE feeds are recoverable only until the file
  turns over (~19:00 IST next session). Re-run: /collect
STAGES
  FAIL  exit             50m 20s  exit 1
```

and, from `stopgap.py` in the log: *"This session's bytes may be permanently
lost. Investigate today."*

Six things in that screen were wrong or misleading. None of them was the
failure itself, which was real: a DNS error, `nodename nor servname provided`,
the same class as 2026-08-28.

## 1. Nothing was at risk, and nothing checked

At 08:37 NSE's rolling endpoints serve the **previous** session — a session's
deals are not published until ~19:00 that evening. The 08:30 slot exists to
catch up a missed evening; on a morning after a clean evening it fetches a
duplicate. This morning it failed to fetch a duplicate of 2026-09-16, which
was already held from the 20:30 run. Nothing on the endpoint was missing.

Three channels said data might be lost. Not one of them asked what was held.

`src/common/sessions.py` now answers the one question — *which session should
the endpoint be serving right now* — with a stdlib approximation (previous
weekday before 20:00 IST, today from 20:00, Friday on a weekend). `health.
rolling_exposure()` compares that to the newest held session per rolling
source, and `stopgap`, `stage_alert` and `runreport` all print its sentence
instead of boilerplate:

```
held     nse_bulk_deals   newest held 2026-09-16 is what the endpoint is serving; nothing at risk, the next slot retries
```

or, the morning after a fully missed evening:

```
AT RISK  nse_bulk_deals   newest held 2026-09-15; the endpoint is serving 2026-09-16, which is NOT held — recoverable until the next session publishes (~19:00 IST). Fetch now
```

The failed stage still fails the run. The message now states its severity.

## 2. "1 session(s) stale" every morning

`health.py` counted stale sessions up to the calendar date, so every source
read one session stale on every trading-day morning, for a file that did not
exist yet. The count is now against `expected_session()`. A source holding
last night's file reads 0 stale until 20:00, and 1 from then until the
evening slot fetches today's — which is the number the 20:30 and 22:30 slots
exist to return to zero.

## 3. The 50 minutes were real, and `timeout=30` never fired

I told the owner the Mac had probably slept. It had not. From the manifest:
run start 03:07:55 UTC, `nse_bulk_deals` FAILED at 03:20:44 — six resolution
attempts (warm-up ×3, bulk ×3) at roughly two minutes each — then
`nse_block_deals` succeeded at 03:57:55, 37 minutes for one source.

Every fetcher passes `timeout=30` to `urlopen`. That bounds the socket after
`getaddrinfo` returns. Nothing bounds `getaddrinfo`, and on a half-up network
macOS's resolver blocks for minutes per call. The DNS error message is the
tell: the request never reached a socket.

`src/common/bounded.py` runs a call in a daemon thread and stops waiting at a
deadline. All six network call sites (`stopgap`, `prices`, `derivatives`,
`probe`, `corporate_actions`, `insider`) wrap their `urlopen`/`open` in it with
`DEADLINE = TIMEOUT + 15`. A dead resolver now costs 45 seconds per attempt,
not minutes; a stage that took 50 minutes takes at most about 10 in the same
conditions. `Deadline` subclasses `TimeoutError` so every existing
`except (URLError, TimeoutError)` catches it, and an exception raised inside
the call keeps its own type — a 404 still reads as a holiday to `prices.py`.

Verified by perturbation both ways: with `join(seconds)` replaced by `join()`
the test does not return; with `daemon=True` removed the daemon test fails.

## 4. Every run read FAIL, because `health` exited 1 on a finding

`health.main()` returned 1 whenever a source was stale or the backup was
behind. `collect_daily.sh` recorded `health=1`, the digest listed the run as
FAIL, and `stage_alert` paged *"PROCESSING FAILED: health"* — for a stage
that had just finished and paged its own finding through `broadcast`. The
backup has been behind by a session or two on most days since 0053, so
**every September run read FAIL for this reason alone.** A FAIL that is
always on is a FAIL nobody reads.

`main()` now returns 0 when the check ran. A finding is a finding; a failure
is the check itself dying, and that raises.

## 5. "no result" for a file that does not exist yet

The dated feeds (bhavcopy, F&O, participant OI) asked for today's file at
08:37 and got a 404, recorded as `PENDING`. `runreport` rendered any status it
did not recognise as *"no result"*, which is the wording of a failure. It now
says `2026-09-17 not yet published`, and `NO_SESSION` as `no session (holiday)`.

## 6. A stage called `exit`

The deal fetch was recorded as `note "exit" $?` — a name left over from when
the exit code was the only thing the script recorded. On a phone, `FAIL exit`
reads as the script dying. It is now `deals`. Records and log lines written
before today still say `exit`; `stage_alert.canonical()` maps the old name on
read, so the morning's own record and every historical FAIL line in the
digest keep naming a stage that exists.

## What would reverse this

- **NSE moving its publish time.** `PUBLISH_HOUR_IST = 20` is the one number
  the exposure logic rests on. If deals start publishing at 21:00, a 20:30 run
  will read "today's file is expected" and count one stale for an hour. Move
  the constant; the evening slots (0072) are already spaced for it.
- **A holiday being reported as a missed session.** The approximation treats
  every weekday as a session. On a holiday evening every source will read
  1 stale until the next trading day's file lands; if that ever pages
  (threshold 2 would need a second miss), the observed calendar should be
  consulted for dates it covers before falling back to weekdays.
- **The deadline being hit on a healthy network.** 45 seconds for DNS +
  connect + read of a ~1 MB file is generous on this connection; if
  `Deadline` starts appearing in the manifest on days the network was fine,
  raise `DEADLINE` rather than remove the bound.
- **A hung daemon thread holding a lock.** The abandoned call holds only a
  socket; nothing here holds DuckDB. If a future fetcher takes a database
  lock inside a bounded call, that is the wrong side of the bound.

## Cost accepted

- **A second calendar approximation**, in `src/common/sessions.py`, next to
  `health._weekday_sessions_between`. Both are weekday approximations, both
  documented as such, and the observed calendar cannot replace either because
  it ends at the last price held. Two is one more than ideal.
- **A thread per network attempt.** Trivial in cost; slightly harder to read
  than a bare `urlopen`. The alternative — a resolver with a timeout — does
  not exist in the standard library.
- **A failed duplicate fetch still fails the run and still pages.** The page
  now says "nothing at risk". I chose to keep the page rather than suppress
  it: a DNS failure at 08:30 is worth one message, because the same failure
  at 20:30 would matter, and an operator who sees the morning one is
  forewarned. If it becomes noise, the right change is to not page on a
  not-at-risk `deals` failure — not to stop recording it.
