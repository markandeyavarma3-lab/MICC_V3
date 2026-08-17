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
LOG="$REPO/logs/collect_$(date +%Y-%m).log"
mkdir -p "$REPO/logs"

{
  echo "--- $(date '+%Y-%m-%d %H:%M:%S %Z') pid=$$"
  "$REPO/.venv/bin/python" -m src.archive.stopgap
  echo "exit=$?"
} >> "$LOG" 2>&1
