#!/bin/zsh
# collect_daily.sh — cron entrypoint for the stopgap archiver.
#
# Cron gets a near-empty environment: no PATH to the venv, no RESEARCH_ENV, no cwd.
# Every one of those is set explicitly here rather than assumed, because a
# collector that silently does nothing is worse than no collector — it looks like
# a covered day in every downstream count.
#
# Runs three times a session (20:00, 22:30, 08:00 next morning). That is not
# belt-and-braces paranoia: NSE publishes around 19:00 IST and does not republish,
# so at 08:00 the endpoint is STILL serving the previous session's file. The
# morning slot is therefore a genuine catch-up for a missed evening, not a repeat.
# sha256 dedupe makes every extra run a no-op that costs one HTTP request.

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
LOG="$REPO/logs/collect_$(date +%Y-%m).log"
mkdir -p "$REPO/logs"

{
  echo "--- $(date '+%Y-%m-%d %H:%M:%S %Z') pid=$$"
  "$REPO/.venv/bin/python" -m src.archive.stopgap
  echo "exit=$?"
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
  echo "prices=$?"
  "$REPO/.venv/bin/python" -m src.ingest.bhavcopy
  echo "bhavcopy=$?"
  # A 90-day window ending today: actions are announced ahead of their ex-date,
  # so re-reading the recent past is how a revision is picked up at all. sha256
  # dedupe makes an unchanged window a no-op.
  "$REPO/.venv/bin/python" -m src.archive.corporate_actions \
      --start "$(date -v-90d +%Y-%m-%d)"
  echo "corpact=$?"
  "$REPO/.venv/bin/python" -m src.ingest.corp_actions
  echo "corpact_parse=$?"
  # INSIDER FILINGS (0046). The best-powered event class measured so far —
  # promoter sells at 1.25x short against consensus's 1.94x — and the only one
  # whose gap closes in years rather than decades. Every session collected is a
  # cohort the study could not otherwise have.
  #
  # A 30-day trailing window: filings are revised and back-dated, so re-reading
  # the recent past is how a revision is picked up. sha256 dedupe makes an
  # unchanged window a no-op.
  "$REPO/.venv/bin/python" -m src.archive.insider --start "$(date -v-30d +%Y-%m-%d)"
  echo "insider=$?"
  "$REPO/.venv/bin/python" -m src.ingest.insider
  echo "insider_parse=$?"
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
  echo "spine=$?"
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
  echo "land=$?"
  "$REPO/.venv/bin/python" -m src.identity.master
  echo "identity=$?"
  "$REPO/.venv/bin/python" -m src.mart.clean
  echo "mart=$?"
  "$REPO/.venv/bin/python" -m src.monitor.health
  echo "health=$?"
  # Back up AFTER collecting, every day. 0037 left this manual and it went eight
  # days without running once; a session archived but not backed up sits on one
  # disk, and the endpoint that could re-serve it answers 503. The script is a
  # no-op-ish 11 MB write and prunes itself to three generations.
  "$REPO/scripts/backup.sh"
  echo "backup=$?"
} >> "$LOG" 2>&1
