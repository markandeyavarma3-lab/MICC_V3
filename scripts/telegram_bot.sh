#!/bin/zsh
# telegram_bot.sh — launchd entrypoint for the command listener. Decision 0071.
#
# The same reasoning as collect_daily.sh: launchd starts jobs with a near-empty
# environment, so a token exported in ~/.zshrc works by hand and never once
# works from the scheduler. ~/.micc_alert_env is the ONE path both jobs share
# and the only place the config lives.
#
# NO CREDENTIAL IS IN THIS REPO, WHICH IS PUBLIC. That file is mode 600 in $HOME
# and names a token file; absent, the listener prints "not configured" and exits
# non-zero, and launchd's ThrottleInterval keeps the retry cheap.

set -u
REPO="$HOME/Workspace/institutional-research"
cd "$REPO" || exit 1
export RESEARCH_ENV=prod
[ -f "$HOME/.micc_alert_env" ] && . "$HOME/.micc_alert_env"

# exec, not a subshell: launchd tracks the pid it started, and a wrapper that
# outlives its child would report the job as alive after the listener died.
exec "$REPO/.venv/bin/python" -m src.monitor.bot
