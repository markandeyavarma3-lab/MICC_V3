# 0072 — Three slots a day, again: 22:30 restored

**Date:** 2026-09-17
**Decided by:** Owner, explicitly, after asking "what about the 22:30 backup?"
and being told plainly that no such slot currently exists — it was removed by
their own request in 0060, and they chose to bring it back rather than leave
it removed.
**Status:** accepted
**Supersedes:** 0060's two-slot calendar (08:30, 20:30) in
`scripts/com.institutional-research.collect.plist`.
**Related:** 0059 (cron retired), 0060 (removed the slot this restores), 0068
(measured the same-day hit rate this decision cites).

## Context

0060 dropped the evening's second attempt on the reasoning that since 0055 the
script does far more than fetch — spine, land, identity, mart, outcomes — so a
second full pass at 22:30 mostly re-runs the same rebuild to reach the same
state, and the 08:30 morning catch-up already recovers a missed evening
because NSE's rolling endpoints still serve the prior session at that hour.

That reasoning holds for a **failed** fetch. It does not cover a fetch that
succeeds *late* — NSE publishing after 20:30 but before the endpoint rolls to
the next session. 0068 measured this directly from the collector's own history:
checking at 20:00 catches the file ~82% of the time; checking again at 22:00
catches it ~93%. The 08:30 morning slot still recovers the remaining ~7%, but
only after the file has sat unprocessed overnight — the mart, outcomes and
every study reading them are that many hours stale for no reason except the
clock.

The owner was told this number while asking an unrelated question, asked what
happened to the 22:30 slot they remembered from before 0060, and decided to
restore it having heard the tradeoff.

## Decision

`StartCalendarInterval` gains a third set of seven entries — Weekday 0–6 at
Hour 22 Minute 30 — alongside the existing 08:30 and 20:30 sets, in both the
repo copy and the loaded `~/Library/LaunchAgents/` copy. 21 entries total.
`collect_daily.sh`'s header comment and `src/monitor/bot.py`'s reference to
"twice a day" are corrected in the same change; no executable line changed.

The agent was `bootout`-ed and `bootstrap`-ed so launchd re-read the calendar;
`launchctl print` after reload lists 21 calendar triggers at 8:30, 20:30 and
22:30, none at any other hour.

## Why 22:30 specifically, not some other later hour

Restoring the exact hour 0060 removed, rather than picking a new one, keeps
the 0068 measurement ("~93% by 22:30") applicable without re-deriving it.
There is no evidence a later hour would do meaningfully better — NSE's late
publishes cluster within roughly two hours of the usual time, not scattered
across the night — and a later hour trades against the operator's own
sleep schedule for no measured benefit.

## What would reverse this

- NSE tightening its publish window so 20:30 alone reaches ~93% or better,
  making the third slot redundant. Nothing currently suggests this; publish
  timing has drifted the other direction across September.
- The added pipeline pass proving costly rather than merely redundant — for
  instance, three DuckDB-writing passes a day instead of two measurably
  raising the odds of the exact lock collision found the night before this
  decision (2026-09-16 20:30: `outcomes` and `health` both lost a write-lock
  race against an unrelated external process). That collision was not caused
  by a second collector run; it is still a real cost that a third pass makes
  marginally more likely to coincide with, and worth revisiting if it recurs.
- Evidence that a 22:30 run's rebuild (mart, outcomes, spine) meaningfully
  disturbs anything already read by that hour. Nothing in this project reads
  the warehouse interactively at night; the risk is theoretical.

## Cost accepted

**A third full pipeline pass most evenings**, most of which will find nothing
new to fetch and will still re-run spine, land, identity, mart, charpanel and
outcomes against unchanged input — sha256 dedupe makes the FETCH free, not the
rebuild. Measured cost from the most recent full run: roughly 3 minutes.
Three times that per day is still a small fraction of the day, but it is not
zero, and it is the same "the second pass mostly repeats itself" cost 0060
already weighed once.

**A third daily `backup.sh` invocation**, tarring and bundling the same state
up to three times where it used to be twice. The retention (`prune_generations`,
3 generations) is unaffected — it prunes by count, not by how many ran that day
— but iCloud upload traffic and local write volume both rise proportionally.

**One more scheduled moment for the DuckDB lock-collision failure mode to land
on**, discussed above. Not new in kind — 0059 already exists because two
concurrent runs collide on the same lock — only in frequency.
