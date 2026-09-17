#!/bin/zsh
# shp_nightly.sh — the shareholding-pattern sweep, on its own schedule. Decision 0074.
#
# NOT A STAGE IN collect_daily.sh, ON PURPOSE. The first sweep has ~60,000 XBRL
# files behind it — about 33 hours at the 2-second rate limit — and even a
# quarterly top-up is ~2,900 filings. Putting that inside the collector would
# hold the mart rebuild behind it on every run. It runs at 01:00 instead, when
# nothing else in this project touches nseindia, with a budget that ends well
# before the 08:30 slot. After the backlog clears, the manifest marks every
# master fresh and the run costs seconds until a quarter rolls.
#
# Same environment discipline as collect_daily.sh: launchd starts jobs with an
# empty environment, ~/.micc_alert_env is the one file both share.

set -u
REPO="$HOME/Workspace/institutional-research"
cd "$REPO" || exit 1
export RESEARCH_ENV=prod
[ -f "$HOME/.micc_alert_env" ] && . "$HOME/.micc_alert_env"

LOG="$REPO/logs/shp_$(date +%Y-%m).log"
mkdir -p "$REPO/logs"

{
  echo "--- $(date '+%Y-%m-%d %H:%M:%S %Z') pid=$$"
  # 5000 files x 2s ~= 2.8h, plus masters on a top-up night. Ends by ~04:00.
  "$REPO/.venv/bin/python" -m src.archive.shp --max-detail 5000
  RC=$?
  echo "shp=$RC"
} >> "$LOG" 2>&1

if [ "$RC" -ne 0 ]; then
  # Reuses the collector's alert path — desktop, email, Telegram — with the
  # stage name `shp`, which stage_alert classifies as a dated (re-fetchable)
  # collection feed: next night retries, act only if it repeats.
  "$REPO/.venv/bin/python" -m src.monitor.stage_alert "$LOG" shp >> "$LOG" 2>&1 || true
fi
exit "$RC"
