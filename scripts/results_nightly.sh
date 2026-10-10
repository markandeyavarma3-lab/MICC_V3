#!/bin/zsh
# results_nightly.sh — the quarterly-results sweep (src/archive/results.py),
# its parse, and a site rebuild so the night's results reach the pages.
# 21:20 daily (com.institutional-research.results.plist): after the 21:00
# collector has released the research database (2026-10-09: a reader during
# the collector failed seven stages). Resumable: each night continues where
# the last stopped, never refetching a file.
set -u
REPO="$HOME/Workspace/institutional-research"
cd "$REPO" || exit 1
export RESEARCH_ENV=prod
[ -f "$HOME/.micc_alert_env" ] && . "$HOME/.micc_alert_env"
LOG="$REPO/logs/results_$(date +%Y-%m).log"
mkdir -p "$REPO/logs"
{
  echo "--- $(date '+%Y-%m-%d %H:%M:%S %Z') pid=$$"
  # Never while the collector holds the database.
  while pgrep -f collect_daily.sh >/dev/null; do sleep 60; done
  "$REPO/.venv/bin/python" -m src.archive.results --max-files 3000 --max-minutes 90
  RC=$?
  echo "results=$RC"
  "$REPO/.venv/bin/python" -m src.ingest.results
  echo "results_parse=$?"
  "$REPO/scripts/site_publish.sh"
  echo "site=$?"
} >> "$LOG" 2>&1
exit 0
