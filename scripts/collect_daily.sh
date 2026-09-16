#!/bin/zsh
# collect_daily.sh — cron entrypoint for the stopgap archiver.
#
# Cron gets a near-empty environment: no PATH to the venv, no RESEARCH_ENV, no cwd.
# Every one of those is set explicitly here rather than assumed, because a
# collector that silently does nothing is worse than no collector — it looks like
# a covered day in every downstream count.
#
# Runs twice a day, every day (20:30, 08:30 next morning — decision 0060; was
# 20:00/22:30/08:00 under 0059 and earlier). That is not belt-and-braces
# paranoia: NSE publishes around 19:00 IST and does not republish, so at 08:30
# the endpoint is STILL serving the previous session's file. The morning slot
# is therefore a genuine catch-up for a missed evening, not a repeat. sha256
# dedupe makes every extra run a no-op that costs one HTTP request. The only
# trigger is the launchd agent; cron was retired in 0059.

set -u
REPO="$HOME/Workspace/institutional-research"
cd "$REPO" || exit 1

export RESEARCH_ENV=prod

# ALERT CONFIG, AND WHY IT IS SOURCED HERE RATHER THAN SET IN THE PLIST.
#
# Neither scheduler inherits a login shell's environment. launchd starts jobs
# with a near-empty one and cron reads no plist at all, so a password exported
# in ~/.zshrc works perfectly by hand and never once fires from the scheduler —
# which is exactly when nobody is at the machine to see the desktop
# notification. health.py's email leg returns "email not configured" without
# raising when the variables are absent, so the failure is silent by design.
#
# This is the ONE place both schedulers pass through, so it is the only place
# the config belongs. Putting it in the plist as well would leave two copies to
# keep in sync, which is the drift this project keeps finding in its own README.
#
# NO CREDENTIAL IS IN THIS REPO, WHICH IS PUBLIC. The file lives in $HOME at
# mode 600 and names a password file; absent, alerting stays desktop-only and
# everything else runs unchanged.
[ -f "$HOME/.micc_alert_env" ] && . "$HOME/.micc_alert_env"
# EXIT CODES PROPAGATE. Until 2026-09-03 every stage's status was echoed into a
# log nobody reads and the script returned 0 unconditionally — so launchd and
# cron could not tell a total failure from a clean run. That is the same
# green-over-broken pattern as the retired-endpoint envelope and the swallowed
# XBRL fetch: the signal existed and nothing carried it.
#
# `note` records a stage and remembers the worst code seen. The script exits
# with it, so a scheduler that checks status finally learns something.
#
# `FAILED_STAGES` was added 2026-09-16 (decision 0070). RC=1 said something
# broke; it never said WHAT. charmatch failed on twenty consecutive scheduled
# runs and the only signal was one line in a file with no reader.
#
# `last_run.tsv` was added 2026-09-16 (decision 0071). digest.py recovered stage
# results by regexing `stage=code` out of this log's prose, which worked and had
# already needed a dedupe when a stage echoed twice and read as two failures.
# Timing and exit codes are now written as DATA next to the line that prints
# them, so the report reads a record instead of reconstructing one.
RC=0
FAILED_STAGES=""
RUN_TSV="$REPO/logs/last_run.tsv"
mkdir -p "$REPO/logs"
# Truncated at the START of each run, not appended: the file describes THIS run.
# A partial file left by a run that died mid-stage is the most useful state it
# can be in — it names the stage that never returned.
printf '# started %s\n' "$(date -u +%Y-%m-%dT%H:%M:%S+00:00)" > "$RUN_TSV"
STAGE_T0=$SECONDS
note() {  # note <stage> <code>
  echo "$1=$2"
  printf '%s\t%s\t%s\n' "$1" "$2" "$(( SECONDS - STAGE_T0 ))" >> "$RUN_TSV"
  STAGE_T0=$SECONDS
  if [ "$2" -ne 0 ]; then
    RC=1
    FAILED_STAGES="$FAILED_STAGES $1"
  fi
  return 0
}

LOG="$REPO/logs/collect_$(date +%Y-%m).log"
mkdir -p "$REPO/logs"

{
  echo "--- $(date '+%Y-%m-%d %H:%M:%S %Z') pid=$$"
  "$REPO/.venv/bin/python" -m src.archive.stopgap
  note "exit" $?
  # ALWAYS run the health check, including after a failed fetch — especially
  # then. On 2026-08-28 all three slots failed on DNS, the collector said "may
  # be permanently lost", exited 1, and nobody saw it for two days. Detection
  # was never the problem; nothing carried it anywhere.
  # PRICES AND CORPORATE ACTIONS, BEFORE THE HEALTH CHECK READS ANYTHING.
  #
  # Both are DATED archives, unlike bulk.csv, so a missed run costs a retry
  # rather than a session — which is why they run after the deal fetch rather
  # than racing it. They are what make a collected deal usable: without prices
  # every one is "no next session in the data", and without corporate actions
  # the adjusted spine refuses to extend past a split.
  "$REPO/.venv/bin/python" -m src.archive.prices
  note "prices" $?
  "$REPO/.venv/bin/python" -m src.ingest.bhavcopy
  note "bhavcopy" $?
  # A 90-day window ending today: actions are announced ahead of their ex-date,
  # so re-reading the recent past is how a revision is picked up at all. sha256
  # dedupe makes an unchanged window a no-op.
  "$REPO/.venv/bin/python" -m src.archive.corporate_actions \
      --start "$(date -v-90d +%Y-%m-%d)"
  note "corpact" $?
  "$REPO/.venv/bin/python" -m src.ingest.corp_actions
  note "corpact_parse" $?
  # INSIDER FILINGS (0046). The best-powered event class measured so far —
  # promoter sells at 1.25x short against consensus's 1.94x — and the only one
  # whose gap closes in years rather than decades. Every session collected is a
  # cohort the study could not otherwise have.
  #
  # A 30-day trailing window: filings are revised and back-dated, so re-reading
  # the recent past is how a revision is picked up. sha256 dedupe makes an
  # unchanged window a no-op.
  # DERIVATIVES, decision 0058. participant-wise OI and the F&O bhavcopy, both
  # unparked when the trigger was superseded. Collection only — nothing parses
  # these into the warehouse and no study reads them, deliberately, so that
  # Workstream 3's deals verdict does not acquire a second open front.
  "$REPO/.venv/bin/python" -m src.archive.derivatives
  note "derivatives" $?
  # LAND WHAT DERIVATIVES JUST ARCHIVED (0066). 0065 landed the history once by
  # hand and the spine was stale again the next morning: archiving without a
  # land step is the 0058 boundary wearing a new hat. --append rewrites only
  # the year partition the new sessions fall in (not a 175M-row rebuild),
  # refuses if it would leave a hole or a duplicate key, and re-registers the
  # spine. participant_oi rows land in the same call with their own source.
  "$REPO/.venv/bin/python" -m src.ingest.fno --append
  note "fno_land" $?
  "$REPO/.venv/bin/python" -m src.archive.insider --start "$(date -v-30d +%Y-%m-%d)"
  note "insider" $?
  "$REPO/.venv/bin/python" -m src.ingest.insider
  note "insider_parse" $?
  # REBUILD THE SPINE, WITHOUT WHICH ALL OF THE ABOVE IS INERT.
  #
  # Found 2026-09-01 by test_the_price_spine_reconciles_exactly_with_its_inputs,
  # hours after it was written: the 20:22 run had collected and parsed
  # 2026-09-01 and the spine still ended 2026-08-31. Collection was working
  # perfectly and every downstream measurement was reading yesterday.
  #
  # price_spine and price_spine_adj only. fno_spine is 174M rows and nothing
  # collects F&O yet, so rebuilding it daily would burn minutes to reproduce an
  # identical file.
  "$REPO/.venv/bin/python" -c "
from src.warehouse import spine
import duckdb
c = duckdb.connect()
print(' ', spine.build(spine.PRICE, env='prod', con=c).render())
print(' ', spine.build_adjusted(env='prod', con=c).render())
"
  note "spine" $?
  # THE RELATIONAL HALF, WHICH WAS NOT IN THIS SCRIPT AND SHOULD HAVE BEEN.
  #
  # land -> master -> clean is the only path collected DEALS take into the
  # database. None of it ran here. On 2026-09-01 `land` broke on an unhandled
  # _csv.Error and nothing noticed for a day: the collectors reported success,
  # health stayed green, the gate stayed 20/20, and no deal reached the mart
  # after 08-28. An external audit found it, not this project.
  #
  # A pipeline stage that only ever runs by hand is a stage whose failure is
  # silent by construction. Running it here makes a break loud on the next
  # session instead of on the next audit.
  "$REPO/.venv/bin/python" -m src.ingest.land
  note "land" $?
  "$REPO/.venv/bin/python" -m src.identity.master
  note "identity" $?
  "$REPO/.venv/bin/python" -m src.mart.clean
  note "mart" $?
  # OUTCOMES MUST FOLLOW THE MART, EVERY TIME.
  #
  # deal_forward_outcomes holds a foreign key to institutional_deals_clean, so a
  # mart rebuild deletes every outcome row — see the cascade in src/mart/clean.py
  # and decision 0055. Without this stage the table would sit EMPTY between the
  # nightly mart rebuild and the next manual run, which is the worse failure:
  # step 6.3 would report BUILT while every study reading it got nothing back.
  # 97 seconds against a mart rebuild that already costs more than that.
  # CHAR_PANEL BEFORE OUTCOMES, AND IT WAS NEVER HERE AT ALL.
  #
  # The panel carries the size/momentum/volatility buckets CHAR_MATCHED matches
  # on, and benchmarks.yml calls CHAR_MATCHED the primary measure of participant
  # skill. Nothing rebuilt it: the spine advanced daily, outcomes rebuilt daily,
  # and the panel sat frozen at 2026-08-14 for 27 days while every event after
  # that date was matched against characteristics from the last rebalance it had.
  #
  # Not a correctness bug — the ASOF join still takes the most recent rebalance
  # at or before each event, so the match stays point-in-time. It is a quality
  # bug that degrades a little every day and reports nothing, which is worse:
  # a wrong number argues with you, a slowly staler one does not.
  # Found 2026-09-10 by giving DATA_INVENTORY.md an age column.
  "$REPO/.venv/bin/python" -m src.research.charmatch
  note "charpanel" $?
  "$REPO/.venv/bin/python" -m src.research.outcomes
  note "outcomes" $?
  "$REPO/.venv/bin/python" -m src.monitor.health
  note "health" $?
  # THE DAILY DIGEST. One screen answering "did last night work, and is anything
  # rotting" — the question HEALTH.md, STATUS.md and DATA_INVENTORY.md each
  # answer a piece of and none answers whole.
  #
  # ONCE A DAY, NOT AT A TIME (0071). This was `if [ "$(date +%H)" -lt 12 ]` —
  # the 08:30 slot and only it. That is a clock pretending to be a policy, and
  # it drops the report on precisely the days it is most wanted: if the Mac
  # sleeps through the morning, launchd replays the run on wake, the replay
  # lands after noon, and the day gets no digest at all. `--once-daily` asks
  # "has today been reported" instead, so the first run of the day delivers
  # whenever it happens and later runs are no-ops.
  "$REPO/.venv/bin/python" -m src.monitor.digest --once-daily --email --telegram || true
  # Back up AFTER collecting, every day. 0037 left this manual and it went eight
  # days without running once; a session archived but not backed up sits on one
  # disk, and the endpoint that could re-serve it answers 503. The script is a
  # no-op-ish 11 MB write and prunes itself to three generations.
  "$REPO/scripts/backup.sh"
  note "backup" $?
} >> "$LOG" 2>&1

# THE RUN REPORT, ON EVERY RUN INCLUDING THE CLEAN ONES.
#
# Outside the redirection block on purpose: it reads the log and the manifest
# this run just wrote, so it must run after the block closes.
#
# A clean run used to produce no output anywhere a person looks, which sounds
# efficient and is the failure this project keeps rediscovering: an operator who
# only hears from a system when it breaks cannot tell a healthy silence from a
# dead scheduler. Both real losses — 19 Aug and 10-15 Sep — looked exactly like
# a quiet, working collector.
"$REPO/.venv/bin/python" -m src.monitor.runreport --telegram >> "$LOG" 2>&1 || true

# The whole point: a failed stage makes the RUN fail.
if [ "$RC" -ne 0 ]; then
  echo "COLLECT: FAILED stages:$FAILED_STAGES — see $LOG" >&2
  # Carry it to where somebody looks. Reuses health.py's already-configured
  # desktop and email channels; never raises, so a broken alerter cannot turn a
  # useful failure into a stack trace.
  "$REPO/.venv/bin/python" -m src.monitor.stage_alert "$LOG" $FAILED_STAGES \
    >> "$LOG" 2>&1 || true
fi
exit "$RC"
