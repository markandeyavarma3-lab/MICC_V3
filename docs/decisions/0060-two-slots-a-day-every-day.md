# 0060 — Two slots a day, every day: 08:30 and 20:30

**Date:** 2026-09-15
**Decided by:** Owner. Executed and verified the same morning, 10:40 IST,
before the day's first slot.
**Status:** accepted
**Supersedes:** the three-slot calendar (20:00 and 22:30 Mon–Fri, 08:00
Mon–Sat) in `scripts/com.institutional-research.collect.plist`, which 0059
had just made the only trigger.
**Related:** 0059 (cron retired; two sessions lost to a shutdown).

## Context

0059 left launchd as the sole scheduler with the calendar it inherited from
cron: 20:00 and 22:30 on weekdays as two shots at the evening file, 08:00
Monday to Saturday as the catch-up. Two of those three slots existed to
hedge each other — 22:30 re-fetched what 20:00 had fetched, and sha256
dedupe made the repeat free — and the third was bounded to Mon–Sat on the
assumption that nothing needs catching on a Sunday.

The owner asked for a simpler calendar: **08:30 and 20:30 IST, every day.**

## Decision

`StartCalendarInterval` is replaced in both copies of the plist — the repo
file and the loaded `~/Library/LaunchAgents/` file, which are kept
byte-identical — with 14 entries: Weekday 0–6 at Hour 8 Minute 30, and
Weekday 0–6 at Hour 20 Minute 30. `man launchd.plist` confirms 0 and 7 are
both Sunday, so 0–6 is every calendar day. `RunAtLoad` stays `false`. The
agent was `bootout`-ed and `bootstrap`-ed so launchd re-read the calendar;
no run was kicked. `launchctl print` after the reload lists exactly 14
calendar triggers, all at 8:30 or 20:30, none at 20:00, 22:30 or 08:00; the
crontab has no `collect_daily` line.

The stale "three times a session" sentence in `collect_daily.sh`'s header
comment was corrected in the same change. No executable line of the script
changed (`zsh -n` clean).

## Why

**20:30, not 20:00.** NSE publishes bulk and block deals around 19:00 IST
and does not republish. 20:00 was already comfortably after that; 20:30
adds thirty minutes of headroom for a late publish and costs nothing,
because the file is current-day until the next evening.

**One evening slot, not two.** The 22:30 run was insurance against the 20:00
run failing. Since 0055 the script does far more than fetch — spine, land,
identity, mart, outcomes — and a second full pass two and a half hours later
rebuilds the same mart to reach the same state. The insurance the design
actually needs is against the *file* being missed, and 08:30 the next
morning provides that: the endpoint is still serving the prior session
then. So the second evening slot is dropped and the morning slot is kept.

**Every day, including Saturday and Sunday.** The old calendar had no Sunday
slot, on the reasoning that Friday's file is caught Saturday 08:00. It is —
if the machine is on Saturday morning. 0059 recorded exactly the case where
it was not. A Sunday 08:30 run is one more chance at Friday's file if
Saturday's was missed, and on any weekend it finds nothing new and costs one
HTTP request. Symmetry also removes a class of mistake: there is no longer
a day of the week on which "the collector didn't run" is normal.

## What would reverse this

- NSE routinely publishing after 20:30. The 08:30 slot still catches it, but
  the evening slot would then be doing nothing useful and should move later.
- Evidence that the collector's later stages (mart, outcomes) benefit from
  running twice in an evening — for example a fetch that succeeds at 20:30
  but a downstream stage that reliably needs a second attempt. Nothing in
  the September log suggests this; every second-of-pair failure was the
  lock collision, not a transient.
- A launchd calendar that does not fire on weekend days for some reason
  this session did not test. The first Saturday and Sunday (2026-09-19/20)
  will show whether the 0 and 6 weekday entries fire.

## Cost accepted

**One evening attempt instead of two.** If the 20:30 run fails for a reason
that would have cleared by 22:30 — a transient NSE 503, a DNS blip — the
session's file is not retried until 08:30 the next morning. The morning
endpoint still serves the prior session, so nothing is lost; the cost is up
to twelve hours of latency on the mart for that session, and the
dependency that the machine is on at 08:30. That dependency already existed
for the Saturday catch-up and is now simply true every day.

No trials. No study module, identity code, mart code, or effect estimate is
touched.
