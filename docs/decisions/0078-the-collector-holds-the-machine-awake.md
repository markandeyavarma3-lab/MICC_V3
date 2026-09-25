# 0078 — The collector holds the machine awake, because launchd does not

**Date:** 2026-09-20
**Decided by:** Me, at the owner's "can you find and fix this to make the
extraction even better" — the "this" being the SHP sessions that were
retrieving fifty symbols in a 150-minute budget.
**Status:** accepted
**Related:** 0074 (the SHP sweep and its wall clock), 0072 (the slot
calendar), 0059 (launchd as the sole scheduler).

## What looked like a slow host

Three SHP sessions a day, each budgeted at 150 minutes and 2,500 XBRL files.
The healthy ones on 09-18 and 09-19 did 3,000+ fetches in their window at a
median gap of 2.3 seconds — the 2-second rate limit plus a 0.3-second fetch.
Then the 09-19 14:30 session did **174 records in 150 minutes**, and the
09-20 01:00 session did 949 in its first hour and then **one failed fetch in
the next 48 minutes**. The insider stage of the 09-19 22:30 collector ran
159 minutes for 12 files (fixed separately, with a wall clock and a breaker
— but those guard against a refusing host, and that is not what this was).

The manifest cannot show a gap's cause, only its length. `pmset -g log` can.
Laid side by side:

```
01:03:15  SHP session starts                 (shp log)
01:03:17  Entering Sleep state               (pmset)
   ...    Wake / Sleep / Wake / Sleep
02:27:39  last successful record             (manifest)
02:27:45  Entering Sleep state               (pmset)
03:15:51  next record — a FAILED fetch       (manifest)
03:33     wall clock: 150 min after 55 symbols
```

and, for the 14:30 session on 09-19: sleep at 14:36:31, six minutes in, then
a "DarkWake from Deep" lasting two seconds every fifteen minutes until the
clock expired at 17:00. Eighteen minutes of work in a 150-minute budget.

Both power profiles are set to sleep after **one idle minute**. launchd
starting a job does not count as activity. Nothing in any script asked the
machine to stay up.

The 48-minute "fetch" was a socket that died while the laptop slept; the
retry cascade ran only once the machine woke. The 14:30 session's ten
symbols were ten dark-wakes. What every guard in 0074 read as a throttling
host was the host's client being asleep — and a breaker cannot trip on a
failure that never gets to happen.

## Decision

Every launchd-started collection script holds an idle-sleep assertion for
exactly its own lifetime:

```sh
caffeinate -i -w $$ >/dev/null 2>&1 &
```

in `scripts/collect_daily.sh` and `scripts/shp_nightly.sh`, immediately after
the environment is sourced. `-i` prevents idle sleep and works on battery.
`-w $$` releases the assertion when the script's process ends, however it
ends, so a run that dies leaves nothing holding the machine up. A test pins
the line's presence in both scripts.

## What it does not do

**A closed lid still sleeps the machine.** No user-space assertion prevents
that on a MacBook without an external display. The owner knows the schedule;
this record does not pretend to fix a lid.

**It costs battery.** Three 150-minute SHP sessions and three collector runs a
day, awake, on battery. That is the price of collecting, and it was being
paid already — for two seconds of work every fifteen minutes.

## What was checked and NOT changed

**The rate limit.** With a healthy host the median gap between fetches is
2.3 seconds, of which 2.0 is `RATE_LIMIT`. Halving the sleep would nearly
double throughput on paper. It was not done: 0074 measured the host's
tolerance at roughly 1,150 files an hour before it slowed every response to
the deadline, and 2.3-second spacing is already ~1,300 an hour. The sleep is
not the ceiling; the host is. Lowering it would buy an earlier throttle, not
more files.

## What would reverse this

- `caffeinate` failing to hold the assertion on a future macOS, which would
  show as the same signature: sessions with long empty gaps whose `pmset`
  log says "Entering Sleep state" inside them.
- The machine moving to a desk with mains power and a "never sleep" profile,
  at which point the line is harmless and redundant.

## Cost accepted

One more process per run, and a laptop that stays awake for its collection
windows on battery. Against a sweep that was spending most of its budget
asleep, this is not a close call.

## Amendment 1 — 2026-09-25: `-i` does not hold a dark wake

**What happened.** Four collector slots in three days went wrong, and the
first diagnosis given to the owner, "the lid was closed", was right for only
one of them. `last reboot` and `pmset -g log` together say:

| slot | machine state | cause |
|---|---|---|
| 09-23 08:30 | **powered off** until a boot at 09:24 | nothing can run on a switched-off Mac |
| 09-24 08:30 | **shut down at 00:15**, booted 09:35 | same |
| 09-24 20:30 | lid open, idle-slept at 20:17 | run launched in a DARK WAKE at 20:41:08; asleep again at 20:41:10 |
| 09-25 08:30 | lid closed (the 09:43 wake cites the lid) | run launched in a dark wake at 08:30:39; asleep at 08:30:48 |

The 09-24 power log showed no sleep between 00:14 and 09:41, which read as
"awake and launchd didn't fire". It was the absence of a machine, not the
presence of one. `kern.boottime` settled it.

**The fixable one is 09-24 20:30.** When launchd starts a job on a sleeping
Mac, the job runs inside a dark wake: display off, a few seconds granted.
`caffeinate -i` prevents IDLE sleep; a dark wake ending is not idle sleep, and
the assertion does not extend it. `caffeinate -u` declares the user active,
which is what converts a dark wake to a full wake — pmset logged exactly that
transition at 09:44 the same morning ("DarkWake to FullWake ... due to
UserActivity Assertion"). Both scripts now run `caffeinate -u -t 5` before the
`-i` hold. The test that pins `-i` now pins `-u` too.

**Still not fixable in software:** a closed lid on battery (09-25), and a
powered-off machine (09-23, 09-24). The first needs the lid open or AC power
with an external display; the second needs the Mac left on.

**Unverified until it happens.** The assertion was confirmed accepted
(`pmset -g assertions` lists `UserIsActive`), but a dark-wake start with the
lid open cannot be reproduced on demand. The signature to look for in the
next such slot is a `DarkWake to FullWake ... UserActivity` line within
seconds of the run's start, and no "Entering Sleep" until the run ends.

**Cost:** the display lights for about five seconds at each slot that finds
the Mac asleep with the lid open.
