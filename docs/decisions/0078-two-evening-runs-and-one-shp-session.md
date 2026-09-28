# 0078 — Two evening collector runs (18:30, 21:00) and one SHP session (18:45)

**Date:** 2026-09-28
**Decided by:** Owner: "keep collector time at 18:30 … and next at 21:00 —
that's all", with the commitment to have the laptop on at those times every
day.
**Status:** accepted
**Supersedes:** 0060 (08:30 / 20:30) and 0072 (08:30 / 20:30 / 22:30) for the
collector; 0074 amendment 2 (01:00 / 10:30 / 14:30) for the SHP sweep.
**Related:** 0063 (the rolling files roll on publish, not on the calendar),
0074 (the SHP sweep and its wall clock).

## Context

The schedule had drifted to six scheduled runs a day: three collector slots
and three SHP sessions, spread from 01:00 to 22:30. Most of them ran at hours
when the laptop was not available, and those runs collected nothing: from
09-25 to 09-28 the collector completed 3 of 9 slots, and the 01:00 SHP
session failed every night. Only runs at times the owner is on the laptop
work, and the owner has named those times.

## Decision

**Collector: 18:30 and 21:00, every day.** Fourteen `StartCalendarInterval`
entries in `scripts/com.institutional-research.collect.plist`, Weekday 0–6.

**SHP sweep: one session at 18:45, every day,** with the wall clock cut from
150 to 130 minutes (`scripts/shp_nightly.sh`) so it ends by 20:55, before the
21:00 collector, and the two never hit nseindia together.

## Why these times work for NSE's files

NSE publishes the day's bulk and block deals around 19:00 and serves that file
until the next trading session publishes (0063).

- **21:00** fetches the day's file, about two hours after publish.
- **18:30** the next day is the last chance at the same file before the next
  publish replaces it. A missed 21:00 is caught here, not lost.
- Friday's file is served until Monday's publish, so the weekend runs and
  Monday 18:30 all see it.
- The dated feeds (bhavcopy, F&O, index closes) can be re-fetched for any
  past date, so neither time can lose them.

The first run of each day is 18:30, so the daily digest (`--once-daily`)
goes out then.

## What would reverse this

- **NSE publishing before 18:30.** Then 18:30 would fetch the new file, and a
  missed 21:00 the evening before would lose that session. The 18:30 run's
  own staleness report would show it: the held and served dates would
  disagree.
- **The laptop not being on at these times.** A run at an hour when the
  machine is off does nothing; move the times to when it is on.

## Cost accepted

**One SHP session a day instead of three.** In practice three a day
delivered little more, because most of them found the laptop unavailable.
The sweep's pace is measured by `scripts/register_exp004.py`'s coverage line,
52.4% on 2026-09-28.
