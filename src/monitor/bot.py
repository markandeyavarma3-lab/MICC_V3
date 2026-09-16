"""bot.py — commands, from a phone, into this machine. Decision 0071.

WHAT THIS IS. A long-polling Telegram listener that accepts a FIXED LIST of
read-mostly commands and answers with the same reports `runreport` and `digest`
already produce. It exists because the reporting built in 0070 was one-way: the
operator could learn that a stage failed and then had nothing to do about it
until they were next at the Mac, which for the 2026-09-10 outage was five days.

THE SECURITY MODEL, WHICH IS THE WHOLE DESIGN.

A Telegram bot's username is public and unauthenticated — anyone who learns it
can send it messages, and this repository is public. Four controls, in order of
how much they matter:

  1. ONE AUTHORIZED CHAT. Every update whose chat id is not TELEGRAM_CHAT_ID is
     dropped without a reply. Not "rejected with an error" — replying confirms
     the bot is live and tells a stranger their message was read.
  2. AN ALLOWLIST, NOT A PARSER. `COMMANDS` maps a literal command word to a
     Python function. There is no eval, no shell, no path argument, and no way
     to name a file. A command that is not in the dict does not run.
  3. NO SHELL ANYWHERE. The one command that starts a process passes a fixed
     argv list with shell=False. No text from a message reaches a command line;
     the only user-supplied value accepted at all is one integer, range-checked.
  4. NOTHING DESTRUCTIVE IS EXPOSED. No command deletes, rewrites, force-pushes,
     rebuilds a ledger, or touches the governance database. The worst an
     authorized operator can do from a phone is start the collector, which is
     the same job launchd starts twice a day unattended.

The token itself never appears in a reply: `telegram._scrub` strips it from
every error string, because a bot that pastes its own credential into a chat on
a network error has a worse problem than the network error.

WHY A DAEMON AND NOT A POLLING TIMER. A launchd job that polls every two minutes
would answer /status two minutes later, which is slow enough that the operator
stops using it and goes back to not knowing. One long poll blocks for 50 seconds
on Telegram's side and returns the instant a message arrives, so replies are
immediate and the process is idle otherwise. When the Mac sleeps the socket
dies, the poll raises, and the loop reconnects — launchd's KeepAlive covers the
case where the process dies outright.
"""

from __future__ import annotations

import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

from src.common.paths import LOGS, ROOT
from src.monitor import digest, runreport, telegram

OFFSET = LOGS / ".telegram_offset"
COLLECT = ROOT / "scripts" / "collect_daily.sh"

#: Back-off after a failed poll. Long enough that a night of no network is a
#: handful of log lines rather than thousands, short enough that a wake from
#: sleep reconnects while the operator is still looking at the phone.
RETRY_SECONDS = 20


def _running() -> bool:
    """Is a collector run already in flight?

    THIS GUARD IS NOT OPTIONAL. Decision 0059 retired cron because two runs
    starting seconds apart collided on DuckDB's exclusive write lock and failed
    every slot. A /collect issued while the 20:30 job is still working would
    recreate that exact failure, from the phone, with no way to see it.

    `pgrep` over a pid file on purpose: a pid file left behind by a killed run
    lies, and nothing would clear it.
    """
    r = subprocess.run(["pgrep", "-f", str(COLLECT)],
                       capture_output=True, text=True, check=False)
    return bool(r.stdout.strip())


def cmd_help(_: list[str]) -> str:
    return "\n".join([
        "institutional-research",
        "",
        "  /status    what the last collector run did, stage by stage",
        "  /digest    standing state — runs, feeds, staleness, backup",
        "  /health    staleness per source, and what is missing",
        "  /feeds     sessions each feed holds over the last 7 days",
        "  /collect   run the collector NOW (refuses if one is running)",
        "  /log [n]   last n lines of the collector log (default 40, max 200)",
        "  /verdict   the research result as it currently stands",
        "  /help      this",
        "",
        "The collector reports here after every run it fails, and once a day",
        "with the digest — on the first run of the day, whatever hour that is.",
    ])


def cmd_status(_: list[str]) -> str:
    return runreport.render()


def cmd_digest(_: list[str]) -> str:
    return digest.render()


def cmd_health(_: list[str]) -> str:
    from src.monitor import backup_state, health

    out = ["STALENESS"]
    for r in health.read():
        last = r.last_session.isoformat() if r.last_session else "never"
        mark = "STALE " if r.alerting else "ok    "
        bits = [f"{r.sessions_stale} session(s) stale"]
        if r.open_gaps:
            bits.append(f"MISSING: {', '.join(d.isoformat() for d in r.open_gaps[:5])}")
        elif r.gaps:
            bits.append(f"{len(r.gaps)} lost (acknowledged)")
        out.append(f"  {mark}{r.source_id:<22} last {last}  {', '.join(bits)}")
    b = backup_state.read()
    out += ["", f"  {'AT RISK' if b.alerting else 'ok    '} backup  {b.summary}"]
    return "\n".join(out)


def cmd_feeds(_: list[str]) -> str:
    rows = digest._sessions_held()
    if not rows:
        return "no manifest rows in the last 7 days"
    out = ["SESSIONS HELD — last 7 days"]
    out += [f"  {sid:<22} {n:>2}  newest {last}" for sid, (n, last) in rows.items()]
    return "\n".join(out)


def cmd_collect(_: list[str]) -> str:
    if _running():
        return ("A collector run is already in flight. Refusing to start a\n"
                "second one — they collide on the database write lock.\n"
                "Send /status when it finishes.")
    if not COLLECT.exists():
        return f"collector script not found at {COLLECT}"
    # Detached, because the run takes minutes and the poll loop must stay
    # responsive. The script reports its own result here when it finishes, so
    # there is nothing to wait for.
    subprocess.Popen(  # noqa: S603 - fixed argv, no shell, no user input
        [str(COLLECT)], cwd=str(ROOT),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
    )
    return ("Collector started. It takes a few minutes and will report here\n"
            "when it finishes. /status any time.")


def cmd_log(args: list[str]) -> str:
    n = 40
    if args:
        # THE ONLY USER-SUPPLIED VALUE THIS BOT ACCEPTS, and it is validated as
        # an integer and clamped before it is used for anything. It never
        # reaches a shell or a path.
        try:
            n = max(1, min(200, int(args[0])))
        except ValueError:
            return f"'{args[0][:20]}' is not a number. Usage: /log [1-200]"
    logs = sorted(Path(LOGS).glob("collect_*.log"))
    if not logs:
        return "no collector log found"
    lines = logs[-1].read_text(errors="ignore").splitlines()[-n:]
    return f"{logs[-1].name} — last {len(lines)} line(s)\n\n" + "\n".join(lines)


def cmd_verdict(_: list[str]) -> str:
    from src.common.paths import DOCS

    p = DOCS / "reports" / "VERDICT.md"
    if not p.exists():
        return "no verdict report yet"
    # The headline only. The full report is a document, not a phone message,
    # and truncating it mid-table would misrepresent a result.
    body = [ln for ln in p.read_text().splitlines() if ln.strip()][:30]
    return "\n".join(body)


#: The allowlist. A command not in this dict does not run. Adding one is a
#: deliberate act with a code review, which is the point.
COMMANDS = {
    "/start": cmd_help,
    "/help": cmd_help,
    "/status": cmd_status,
    "/digest": cmd_digest,
    "/health": cmd_health,
    "/feeds": cmd_feeds,
    "/collect": cmd_collect,
    "/log": cmd_log,
    "/verdict": cmd_verdict,
}


def handle(text: str) -> str:
    """Text in, reply out. Pure enough to test without a network.

    Never raises: a handler that dies must answer with the reason, because a
    silent bot is indistinguishable from a bot whose machine is off — which is
    the exact ambiguity this whole channel exists to remove.
    """
    word, _, rest = text.strip().partition(" ")
    # Telegram appends @botname when a command is sent in a group.
    word = word.split("@", 1)[0].lower()
    fn = COMMANDS.get(word)
    if fn is None:
        return f"unknown command: {word[:32]}\n\n" + cmd_help([])
    try:
        return fn(rest.split())
    except Exception as exc:  # noqa: BLE001 - the reply IS the error report
        return f"{word} failed: {type(exc).__name__}: {exc}"


def _read_offset() -> int:
    """The last update id consumed.

    PERSISTED ON PURPOSE. Telegram redelivers unacknowledged updates, so a
    listener that starts from zero replays whatever arrived while it was down —
    and one of those commands starts the collector. A restart must not re-run
    yesterday's /collect.
    """
    try:
        return int(OFFSET.read_text().strip())
    except (OSError, ValueError):
        return 0


def _write_offset(n: int) -> None:
    try:
        OFFSET.parent.mkdir(parents=True, exist_ok=True)
        OFFSET.write_text(str(n))
    except OSError:
        pass


def serve(once: bool = False) -> int:
    """The poll loop. Runs until killed."""
    if not telegram.configured():
        print("telegram not configured; nothing to serve.")
        return 1
    me = telegram.call("getMe")
    owner = telegram.chat_id()
    print(f"listening as @{me.get('username')} for chat {owner}")
    offset = _read_offset()
    while True:
        try:
            updates = telegram.get_updates(offset)
        except telegram.TelegramError as exc:
            print(f"{datetime.now(UTC).isoformat()} poll failed: {exc}")
            if once:
                return 1
            time.sleep(RETRY_SECONDS)
            continue
        for u in updates:
            offset = max(offset, u.get("update_id", 0) + 1)
            _write_offset(offset)
            msg = u.get("message") or {}
            chat = (msg.get("chat") or {}).get("id", "")
            text = msg.get("text") or ""
            if not telegram.authorized(chat):
                # Logged, not answered. Silence tells a stranger nothing.
                print(f"dropped message from unauthorized chat {chat}")
                continue
            if not text.startswith("/"):
                continue
            print(f"{datetime.now(UTC).isoformat()} {text.split()[0]}")
            telegram.send(handle(text))
        if once:
            return 0


def main() -> int:
    import sys

    try:
        return serve(once="--once" in sys.argv)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
