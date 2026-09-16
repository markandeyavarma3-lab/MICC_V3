# 0071 — Telegram is the channel, the digest follows the machine, and commands come back

**Date:** 2026-09-16
**Decided by:** Me, at the owner's direction. They asked for one clean place to
see what the collector is doing, said the digest must not be pinned to a clock
hour, and asked whether commands could be sent back into the system.
**Status:** accepted
**Related:** 0070 (stage alerts, and the email that never worked), 0060 (the two
daily slots), 0059 (cron retired because two concurrent runs collide on the
DuckDB write lock), 0053 (the email leg).

## 1. 0070 argued against a third channel. It was half right.

Yesterday's decision deliberately did **not** add a notification channel, on the
grounds that each one is another thing to configure and another thing to go
quietly missing. That reasoning was correct about *configuration* and wrong
about *delivery*, and 0070 itself measured why:

| channel | reaches the operator when a scheduled run fails? |
|---|---|
| desktop notification | only if they are sitting at this Mac |
| email | **never** — port 465 blocked; every alert since 0053 died in the socket |

0070 fixed the email socket. It did not fix the fact that neither channel is
*read* — a desktop notification vanishes into Notification Centre and an alert
mail lands in the same inbox as everything else. Every scheduled run happens
when nobody is at the machine, which is the entire point of scheduling it.

Telegram is a channel that reaches a phone, waits when the phone is off, and
keeps its own history. `src/monitor/telegram.py` is stdlib-only `urllib` —
`pyproject.toml` records that `requests` was declared, never imported, and
removed as an unused supply-chain surface, and four HTTP calls do not justify
putting it back.

**The lesson from 0070 was kept in a different form.** The objection to a third
channel was maintenance, so the fan-out now lives in exactly one place:
`health.broadcast(title, body)` calls desktop, email and Telegram, and every
alert site calls `broadcast`. Adding Telegram touched `health.py` only.
Previously each site named `notify_desktop` then `notify_email` by hand, so a
missed site would alert to two channels while its neighbour alerted to three.

## 2. A clean run produced nothing, anywhere

`stage_alert.py` fires only on failure. `digest.py` is a standing daily state.
Between them nothing answered *the collector just ran; what did it get?*

A silent success is not free. An operator who only ever hears from a system when
it breaks cannot distinguish a healthy silence from a dead scheduler — and
**both of this project's real losses looked exactly like a quiet, working
collector.** 19 August: cron never fired, three slots missed, session gone
permanently. 10–15 September: the Mac was off, and nothing said so.

`src/monitor/runreport.py` reports every run: the verdict, per-stage exit codes
and timings, what each feed collected *during this run*, the error text on any
failed fetch, and current staleness. It answers the failure-class question
before the detail, because that is what decides whether the operator acts now
(rolling feed, recoverable only until the file turns over) or tomorrow.

It reads `logs/last_run.tsv`, written by the same `note` call that prints the
log line. `digest.py` had been recovering stage results by regexing `stage=code`
out of the log's prose and had already needed a dedupe when a stage echoed twice
and read as two failures. Timing and exit codes are now data.

## 3. The digest was scheduled on a clock. It should have been scheduled on a day.

It went out from `if [ "$(date +%H)" -lt 12 ]` — the 08:30 slot, and only it.

That is a clock pretending to be a policy, and it drops the report on exactly
the days it is most wanted. If the Mac sleeps through the morning, launchd
replays the run on wake, the replay lands after noon, and **the day gets no
digest at all** — the same day that needs one most, because a missed morning
slot is what a missed session looks like.

The question is not *is it morning* but *has today been reported*.
`digest.due()` compares a one-line stamp against today's date in **IST** (the
reader's calendar, not UTC), so the first run of any day delivers at whatever
hour it happens — 08:30 if the Mac was awake, 20:30 if it was not, 15:00 on a
day it was opened once in the afternoon — and later runs that day are no-ops.

The stamp is written **only on proven delivery**. Stamping on attempt would make
a day when the network was down a day recorded as reported and never retried,
which is the silent-failure shape of the email leg all over again.

## 4. Commands, and the security model that makes them acceptable

Reporting built in 0070 was one-way. The operator could learn that a rolling
feed had failed and then had nothing to do about it until they were next at the
Mac — which for the September outage was five days, and rolling feeds are
recoverable only until the file turns over.

`src/monitor/bot.py` long-polls Telegram and serves nine commands. This is an
inbound path into the machine, a bot's username is public and unauthenticated,
and this repository is public. Five controls, in order of how much they matter:

1. **One authorized chat.** Every update whose chat id is not `TELEGRAM_CHAT_ID`
   is dropped *without a reply* — answering would confirm the bot is live. The
   check is `telegram.authorized()`, compared as text because Telegram sends ids
   as JSON numbers while the environment holds a string.
2. **An allowlist, not a parser.** `COMMANDS` maps a literal word to a Python
   function. No eval, no shell, no path argument, no way to name a file.
3. **No shell anywhere.** The one command that starts a process passes a fixed
   argv with `shell=False`. The only user-supplied value accepted at all is one
   integer, range-checked to 1–200.
4. **Nothing destructive is exposed.** No command deletes, rewrites, force-pushes
   or touches a governance ledger. The worst an authorized operator can do is
   start the collector — the same job launchd starts twice a day unattended.
5. **`/collect` refuses a concurrent run.** 0059 retired cron precisely because
   two runs seconds apart collided on DuckDB's exclusive write lock and failed
   every slot; a `/collect` sent while the 20:30 job is working would rebuild
   that failure from a phone.

The token is in the URL, which is this API's one genuinely dangerous property —
a bare `urllib` traceback prints what it was fetching. `_scrub` removes it from
every string the module returns or raises, so it cannot reach a log, a message
or a screenshot.

Long-polling, not a webhook: a webhook would mean exposing this laptop to the
internet to read a status report. Polling opens no port, and a sleep kills the
socket in a way the retry loop and launchd's `KeepAlive` already handle.

**Update offsets are persisted.** Telegram redelivers unacknowledged updates, so
a listener starting from zero replays whatever arrived while it was down — and
one of those commands starts the collector.

## 5. Two of my own tests were green and proved nothing

Caught by perturbation, which is the standing rule here:

- `test_nobody_is_authorized_when_no_chat_is_configured` passed with the
  `bool(owner)` guard **removed**. With no owner the comparison is against the
  string `"None"`, so a real chat id and an empty string both fail on their own.
  The case that bites is an update carrying no chat id at all: `"None" ==
  "None"` authorizes a malformed message from anywhere. The assertion was added.
- `test_a_run_that_died_mid_stage_still_parses` used only a short line, which is
  caught by the field count and never reaches the `int()` the "tolerates a
  truncated file" claim is actually about. It stayed green with the `ValueError`
  guard removed. Two more damage shapes were added.

And one real defect the tests found: `read_run(path: Path = RUN_TSV)` binds the
constant at **import** time, so the module-level name stopped being the single
source of truth the moment anything reassigned it. Both it and `digest.due`
now resolve at call time.

## 6. What is not done

- **The bot is not yet configured.** No token exists. `docs/TELEGRAM.md` has the
  setup; until it is done, `telegram.send` returns "not configured" and every
  other channel behaves exactly as before.
- **The listener is a launchd agent that must be installed by hand**, like the
  collector. An uninstalled agent is a bot that never answers.
- **No command writes anything.** `/collect` starts the existing script; nothing
  else has side effects. Widening that is a separate decision.

## What would reverse this

- **A stranger reaching the bot.** If an unauthorized chat is ever served — a
  bug in `authorized`, a Telegram change, a leaked and un-revoked token — the
  listener comes off the machine that day and reporting stays one-way. The
  outbound half does not depend on the inbound half and would survive alone.
- **Telegram becoming unavailable or untrusted** in this jurisdiction, or its
  Bot API changing under us. The fan-out in `health.broadcast` means replacing
  it is one function, not a search through every alert site.
- **The per-run message becoming noise.** Two messages a day is the current
  rate, and the whole channel dies the moment it gets muted — that is exactly
  how the desktop notification stopped being read. If `health` and `backup` keep
  failing for known reasons, they belong in an acknowledged list the way lost
  sessions already do, and the run report should fall back to
  `--only-if-failed`, which is already implemented and unused.
- **`/collect` causing a collision anyway.** The `pgrep` guard is a check, not a
  lock; a run started in the one-second window between the check and the
  `Popen` would still collide. If that is ever observed, the command goes and
  the collector keeps its two scheduled slots.

## Cost accepted

- **A third channel to keep configured**, which is the exact objection 0070
  raised. Paid down by making `health.broadcast` the single fan-out, so the cost
  is one function rather than one edit per alert site — but it is still a token,
  a chat id and a launchd agent that can each go missing silently.
- **An inbound path into this machine where there was none.** Constrained to an
  allowlist with one authorized chat and no shell, but the honest statement is
  that the attack surface went from zero to small, not from zero to zero.
- **A second launchd agent to install by hand and to notice when it dies.**
  Nothing currently watches the watcher: if the bot agent stops, commands go
  unanswered and the only symptom is silence — which is the failure mode this
  whole decision is about. The scheduled run reports still arrive, because they
  are pushed by the collector rather than served by the listener.
- **A token on disk**, at mode 600 outside the repo. Same exposure as the mail
  app password already accepted in 0053, revocable in one message to @BotFather.
- **Two messages a day in a chat**, forever, for a project whose research verdict
  is currently DEAD. That is deliberate: the collection is the part still
  accruing value, and a channel that only speaks on failure cannot tell a
  healthy silence from a dead scheduler.
