# Telegram — setup, commands, and what arrives when

Decision 0071. Until this is configured, nothing here is running: `telegram.send`
returns *"not configured"*, and desktop and email alerting behave exactly as
before.

## Why this channel

| channel | reaches you when a scheduled run fails? |
|---|---|
| desktop notification | only while you are sitting at this Mac |
| email | not until 0070 fixed the blocked port; it is a second inbox |
| **Telegram** | **pushed to your phone, waits if it is off, keeps its history** |

Every scheduled run happens when nobody is at the machine. That is the point of
scheduling it, and it is why the first two channels have never actually told you
anything.

---

## Setup — about five minutes

### 1. Create the bot

In Telegram, open a chat with **@BotFather** and send:

```
/newbot
```

It asks for a display name, then a username ending in `bot`. It replies with a
token that looks like `8123456789:AAH...`.

### 2. Put the token in a file, not in a chat and not in this repo

**This repository is public.** Do not paste the token into a message to anyone,
including an assistant, and do not put it in any file under this repo.

```sh
# Paste the token when prompted; it is not echoed and not stored in history.
read -rs TOKEN && printf '%s' "$TOKEN" > ~/.micc_telegram_token && unset TOKEN
chmod 600 ~/.micc_telegram_token
```

### 3. Tell the collector where it is

Append to `~/.micc_alert_env` — the one file both launchd jobs source, because
neither inherits a login shell's environment:

```sh
cat >> ~/.micc_alert_env <<'ENV'
export TELEGRAM_BOT_TOKEN_FILE="$HOME/.micc_telegram_token"
ENV
```

### 4. Find your chat id

Open your new bot in Telegram and send it any message — `hi` will do. Then:

```sh
cd ~/Workspace/institutional-research
set -a; . ~/.micc_alert_env; set +a
RESEARCH_ENV=prod .venv/bin/python -m src.monitor.telegram --whoami
```

It prints the line to add. `--whoami` exists so the token never reaches a shell:
the documented way to find a chat id curls `getUpdates` with the token in the
URL, which puts a live credential into your shell history and into any
screenshot of the terminal.

```sh
cat >> ~/.micc_alert_env <<'ENV'
export TELEGRAM_CHAT_ID=<the number it printed>
ENV
```

### 5. Prove it works

```sh
set -a; . ~/.micc_alert_env; set +a
RESEARCH_ENV=prod .venv/bin/python -m src.monitor.telegram "setup check"
```

You should see `bot: @yourbot` and a message on your phone. If it says
`telegram FAILED`, the reason is in the string — `chat not found` means the id is
wrong, `Unauthorized` means the token is.

### 6. Install the listener

The bot answers commands only while this agent is running. Like the collector's,
it must be installed by hand:

```sh
cp scripts/com.institutional-research.bot.plist ~/Library/LaunchAgents/
launchctl bootout   gui/$UID/com.institutional-research.bot 2>/dev/null
launchctl bootstrap gui/$UID ~/Library/LaunchAgents/com.institutional-research.bot.plist
launchctl print gui/$UID/com.institutional-research.bot | head -5
```

Send `/help` to your bot. If nothing comes back, look in `logs/bot.err`.

---

## Commands

| command | what it does |
|---|---|
| `/status` | what the last collector run did, stage by stage, with timings |
| `/digest` | standing state — runs, feeds, staleness, backup |
| `/health` | staleness per source and which sessions are missing |
| `/feeds` | sessions each feed holds over the last 7 days |
| `/collect` | run the collector now; refuses if one is already running |
| `/log [n]` | last n lines of the collector log (default 40, max 200) |
| `/verdict` | the research result as it currently stands |
| `/help` | the list |

## What arrives without you asking

| when | what |
|---|---|
| after **every** collector run | the run report — stages, timings, what each feed collected, errors, staleness |
| **once a day**, on the first run of that day | the digest |
| whenever a stage fails | the stage alert, on all three channels |
| whenever a source goes stale or the backup is at risk | the health alert, on all three channels |

The digest is **not** tied to a clock hour. It used to go out only from the 08:30
slot, which meant a morning the Mac slept through produced no digest at all —
the day that most needed one. It now asks *has today been reported* rather than
*is it morning*, in IST, so it lands on the first run of the day whatever hour
that is, and exactly once.

---

## Security

A bot's username is public and anyone who finds it can message it. Five controls:

1. **One authorized chat.** Anything from a chat other than `TELEGRAM_CHAT_ID` is
   dropped with no reply — a reply would confirm the bot is live.
2. **An allowlist, not a parser.** A command not in `bot.COMMANDS` does not run.
   No eval, no shell, no path argument.
3. **No shell anywhere.** `/collect` passes a fixed argv with `shell=False`. The
   only user-supplied value accepted is one integer, clamped to 1–200.
4. **Nothing destructive is exposed.** No command deletes, rewrites,
   force-pushes, or touches a governance ledger.
5. **`/collect` refuses a concurrent run** — two collector runs collide on
   DuckDB's exclusive write lock, which is why cron was retired in 0059.

The token never appears in a reply or a log: it lives in the request URL, and
`telegram._scrub` strips it from every string the module returns or raises.

### If the token leaks

Message **@BotFather**, `/revoke`, pick the bot. The old token dies immediately.
Write the new one to `~/.micc_telegram_token`; nothing else changes, and the
listener picks it up on its next restart (`launchctl kickstart -k
gui/$UID/com.institutional-research.bot`).

---

## Turning it off

Remove `TELEGRAM_CHAT_ID` from `~/.micc_alert_env` and everything degrades to
"not configured" with no other behaviour change. To stop the listener too:

```sh
launchctl bootout gui/$UID/com.institutional-research.bot
```
