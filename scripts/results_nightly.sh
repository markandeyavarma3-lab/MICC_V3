#!/bin/zsh
# results_nightly.sh — the quarterly-results sweep (src/archive/results.py),
# the mutual-fund monthly portfolios (src/archive/mf_portfolios.py), their
# parses, and a site rebuild so the night's filings reach the pages.
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
  # Wait (up to 15 min) for NSE to answer before fetching: a run that starts
  # before the internet is back after sleep fails every stage (owner, 2026-10-28).
  "$REPO/.venv/bin/python" -m src.monitor.netcheck || true
  # Results (NSE) and pre-2021 shareholding (BSE) are different hosts: they run
  # side by side, each at its own polite rate, for up to ten hours (2026-10-18:
  # results widened from the newest 8 quarters to 40, ~5x the files; 2026-10-24: to 90, back to 2005, the pre-XBRL quarters read from NSE's HTML tables). Neither
  # holds the research database; bse_shp reads it read-only for a second.
  # Shareholding filings before NSE's window (2016 - 2021-06), from BSE's static
  # host; resumable, ~35,700 files in all (src/archive/bse_shp.py, 2026-10-16).
  "$REPO/.venv/bin/python" -m src.archive.bse_shp --max-files 40000 --max-minutes 600 &
  BSE_PID=$!
  "$REPO/.venv/bin/python" -m src.archive.results --quarters 90 --max-files 100000 --max-minutes 600
  echo "results=$?"
  wait $BSE_PID
  echo "bse_shp=$?"
  # A long night can run into the next evening's collector: wait it out before
  # anything that writes the database.
  while pgrep -f collect_daily.sh >/dev/null; do sleep 60; done
  "$REPO/.venv/bin/python" -m src.ingest.results
  echo "results_parse=$?"
  # Security-wise delivery position, every session since 2006 (src/archive/delivery.py).
  "$REPO/.venv/bin/python" -m src.archive.delivery --max-minutes 30
  echo "delivery=$?"
  # Fund houses publish by the 10th; a nightly look costs a few page renders
  # and fetches only files not already held.
  "$REPO/.venv/bin/python" -m src.archive.mf_portfolios --months 2 --max-minutes 30
  echo "mf=$?"
  "$REPO/.venv/bin/python" -m src.ingest.mf_portfolios
  echo "mf_parse=$?"
  # Point-in-time industries, extracted from the month-end portfolios (step 3.5).
  "$REPO/.venv/bin/python" -m src.warehouse.sector_history
  echo "sector_history=$?"
  "$REPO/scripts/site_publish.sh"
  echo "site=$?"
} >> "$LOG" 2>&1
exit 0
