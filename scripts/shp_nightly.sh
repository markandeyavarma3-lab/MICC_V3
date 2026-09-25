#!/bin/zsh
# shp_nightly.sh — the shareholding-pattern sweep, on its own schedule. Decision 0074.
# Three sessions a day since 0074 amendment 2 (01:00, 10:30, 14:30) — see the plist.
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

# HOLD THE MACHINE AWAKE FOR AS LONG AS THIS SCRIPT RUNS (2026-09-20, 0078).
#
# Both power profiles sleep after ONE idle minute, and launchd starting a job
# does nothing to stop that. Measured from pmset's log against the manifest:
# the 09-20 01:00 SHP session started at 01:03:15 and the Mac slept at
# 01:03:17; the 09-19 14:30 session did eighteen minutes of work in its 150
# and dark-woke for two seconds every quarter hour until the clock ran out.
# What looked like a slow host was a sleeping laptop.
#
# `-i` prevents IDLE sleep and works on battery; it does not and cannot stop a
# closed lid. `-w $$` ties the assertion to this script's lifetime, so a run
# that dies releases it and nothing is left holding the machine up forever.
caffeinate -i -w $$ >/dev/null 2>&1 &
#
# AND WAKE ALL THE WAY UP FIRST (2026-09-25, 0078 amendment 1). A scheduled run
# that finds the Mac asleep starts inside a DARK WAKE — display off, a few
# seconds of power granted — and `-i` does not hold a dark wake: it prevents
# IDLE sleep, and a dark wake ending is not idle sleep. On 09-24 the 20:30 run
# started at 20:41:08 with the lid OPEN and the Mac was back asleep at
# 20:41:10; deals failed. `-u` declares the user active, which is what turns a
# dark wake into a full one — pmset logged exactly that transition at 09:44
# the same day ("DarkWake to FullWake ... due to UserActivity Assertion").
# Cost: the display lights for a few seconds at each slot if the lid is open.
# It cannot help with the lid CLOSED on battery; nothing in software can.
caffeinate -u -t 5 >/dev/null 2>&1 &

LOG="$REPO/logs/shp_$(date +%Y-%m).log"
mkdir -p "$REPO/logs"

{
  echo "--- $(date '+%Y-%m-%d %H:%M:%S %Z') pid=$$"
  # 1500 files: under an hour at the ~1,150/h NSE tolerated on 2026-09-17 before
  # throttling; the 150-minute wall clock ends the run by 03:30 regardless.
  "$REPO/.venv/bin/python" -m src.archive.shp --max-detail 2500 --max-minutes 150
  RC=$?
  echo "shp=$RC"
  # LAND WHAT THE SESSION JUST ARCHIVED (2026-09-18). Re-parses every archived
  # filing into data/raw/collected/shp/shp_holdings.parquet — one row per
  # (ISIN, quarter, category), scale-normalised, joined to broadcast_date on
  # ISIN. Seconds for thousands of files; the table is always the whole
  # archive, never a delta, so a parser fix reaches every row on the next run.
  "$REPO/.venv/bin/python" -m src.ingest.shp
  echo "shp_parse=$?"
} >> "$LOG" 2>&1

if [ "$RC" -ne 0 ]; then
  # Reuses the collector's alert path — desktop, email, Telegram — with the
  # stage name `shp`, which stage_alert classifies as a dated (re-fetchable)
  # collection feed: next night retries, act only if it repeats.
  "$REPO/.venv/bin/python" -m src.monitor.stage_alert "$LOG" shp >> "$LOG" 2>&1 || true
fi
exit "$RC"
