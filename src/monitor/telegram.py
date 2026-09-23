"""telegram.py — the channel a person actually reads. Decision 0071.

WHY A THIRD CHANNEL, AFTER 0070 SAID NOT TO ADD ONE.

0070's `stage_alert.py` deliberately reused the existing desktop and email legs
rather than adding a channel, on the grounds that a second path is a second
thing to configure and a second thing to go quietly missing. That reasoning was
right about CONFIGURATION and wrong about DELIVERY, and the same decision
measured why:

  desktop  needs the operator at this Mac, and the collector's whole point is
           that it runs when nobody is.
  email    had never once succeeded. Port 465 was blocked on this network and
           every alert since the leg was added died in the socket.

Neither is a channel that reaches a person who is away from the machine, which
is every scheduled run. Telegram is: the message is pushed to a phone, it waits
if the phone is off, and the history is the log.

WHAT MAKES THIS DIFFERENT FROM THE EMAIL LEG. The email leg reported success as
a bare boolean and its one real failure mode was indistinguishable from a wrong
password. Every function here returns a sentence saying what happened, including
which HTTP status came back, so "not configured", "chat not found" and "network
down" are three different strings rather than one silent False.

NO CREDENTIAL LIVES IN THIS REPO, WHICH IS PUBLIC. The bot token is read from
`TELEGRAM_BOT_TOKEN`, or from a file named by `TELEGRAM_BOT_TOKEN_FILE` at mode
600 outside the repo — the same shape `ALERT_EMAIL_PASSWORD_FILE` already uses,
because a second shape is a second thing to get wrong.

THE TOKEN IS IN THE URL, which is the one genuinely dangerous property of this
API: a bare `urllib` traceback prints the URL it was fetching. `_scrub` removes
the token from every string this module returns or raises, so a token cannot
reach a log, a Telegram message, or a terminal the operator screenshots.

STDLIB ONLY. `pyproject.toml` records that `requests` was declared and never
imported, and removed on the grounds that an unused dependency is a
supply-chain surface. Adding it back for four HTTP calls would undo that.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API_ROOT = "https://api.telegram.org"

#: Telegram rejects a message body over 4096 characters. Chunks are cut below
#: that with headroom for the <pre> wrapper and a continuation marker.
MAX_CHARS = 3500


class TelegramError(RuntimeError):
    """A call reached Telegram and Telegram said no, or never reached it.

    Raised only by `call`. Every caller in this package catches it and returns a
    sentence, because an alerter that raises is an alerter that turns a reported
    failure into an unreported one.
    """


def token() -> str | None:
    """The bot token, or None. NEVER logged, NEVER returned to a caller that
    prints. Read fresh each call so a rotated token takes effect without a
    restart of the long-running poller."""
    tok = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not tok and (tf := os.environ.get("TELEGRAM_BOT_TOKEN_FILE")):
        p = Path(tf).expanduser()
        tok = p.read_text().strip() if p.is_file() else None
    return tok or None


def chat_id() -> str | None:
    """The ONE chat this bot talks to.

    This is the authorization boundary, not a convenience. A Telegram bot's
    username is public and anyone who finds it can message it; without this
    check, `/collect` would be a stranger's button. Every inbound update from
    any other chat is dropped.
    """
    return os.environ.get("TELEGRAM_CHAT_ID") or None


def authorized(incoming: object) -> bool:
    """Is this chat the owner's?

    THE SECURITY CONTROL OF THIS WHOLE FEATURE, GIVEN ITS OWN FUNCTION so that
    it can be tested directly rather than only through a network loop. Compared
    as text because Telegram sends chat ids as JSON numbers and the environment
    holds a string, and `12345 != "12345"` would lock the owner out — while a
    looser comparison would let `""`, `None` or `0` through.
    """
    owner = chat_id()
    return bool(owner) and str(incoming) == str(owner)


def configured() -> bool:
    return bool(token() and chat_id())


def _scrub(text: str) -> str:
    """Remove the bot token from a string bound for a log or a message."""
    tok = token()
    return text.replace(tok, "<token>") if tok else text


def call(method: str, params: dict | None = None, timeout: int = 20) -> dict:
    """One Bot API call. Raises TelegramError with the token scrubbed out."""
    tok = token()
    if not tok:
        raise TelegramError("no bot token (set TELEGRAM_BOT_TOKEN[_FILE])")
    url = f"{API_ROOT}/bot{tok}/{method}"
    data = urllib.parse.urlencode(params or {}).encode()
    try:
        with urllib.request.urlopen(url, data=data, timeout=timeout) as r:
            payload = json.loads(r.read().decode())
    except urllib.error.HTTPError as exc:
        # Telegram puts the real reason in the BODY of a 4xx — "chat not found",
        # "bot was blocked by the user". The status line alone says only 400,
        # which would send the operator hunting for a network problem.
        try:
            body = json.loads(exc.read().decode()).get("description", "")
        except Exception:  # noqa: BLE001 - we are already in the error path
            body = ""
        raise TelegramError(_scrub(f"HTTP {exc.code}: {body or exc.reason}")) from None
    except Exception as exc:  # noqa: BLE001 - urllib raises a wide family
        raise TelegramError(_scrub(f"{type(exc).__name__}: {exc}")) from None
    if not payload.get("ok"):
        raise TelegramError(_scrub(f"api: {payload.get('description', payload)}"))
    return payload.get("result", {})


def _escape(text: str) -> str:
    """HTML-escape for parse_mode=HTML.

    Only three characters matter to Telegram's HTML parser. Escaping is not
    cosmetic: an unescaped `<` in a stage name or an exception message makes
    Telegram reject the WHOLE message with "can't parse entities", so the alert
    that mattered most is the one that fails to arrive.
    """
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def format_report(text: str) -> str:
    """Plain text in, Telegram HTML out — bold section titles, boxed tables.

    ADDED 2026-09-23, AFTER EVERY REPORT ARRIVED AS ONE FLAT SLAB. Every
    `render()` in this project (runreport, digest, stage_alert, cmd_health)
    already writes to one convention because it is how a person writes a
    readable plain-text report: a section title flush against the left
    margin, everything under it indented two spaces. `send()` used to ignore
    that shape completely and wrap the WHOLE message in one `<pre>` block, so
    "ALL CLEAN", "COLLECTION FAILED: deals" and a 20-row staleness table all
    arrived in the same undifferentiated monospace slab — legible, but nothing
    on the screen said which line was the answer.

    This reads the existing convention rather than asking every caller to
    restate it: a line that starts at column zero becomes a bold headline.
    A line that is indented or blank is buffered and, once a header ends the
    run, boxed together in one `<pre>` block — Telegram's fixed-width font,
    which is what keeps a column-aligned table aligned. The result is a
    message that is mostly the same bytes it always was, arranged so the
    headline reads before the table does.

    NOTHING UPSTREAM CHANGES SHAPE FOR THIS. A `render()` function still
    returns one plain string that prints correctly in a terminal; this is
    the one place — inside `send()` — where that string is additionally
    given the structure Telegram can display. A render that wants a line
    treated as data rather than a headline needs only indent it, which is
    already the convention every one of them follows for its tables.
    """
    out: list[str] = []
    buf: list[str] = []

    def flush() -> None:
        if buf:
            body = "\n".join(buf).strip("\n")
            if body:
                out.append(f"<pre>{_escape(body)}</pre>")
            buf.clear()

    for line in text.split("\n"):
        if line and not line[0].isspace():
            flush()
            out.append(f"<b>{_escape(line)}</b>")
        else:
            buf.append(line)
    flush()
    return "\n".join(out)


def chunks(text: str, limit: int = MAX_CHARS) -> list[str]:
    """Split on line boundaries, never mid-line.

    These messages are fixed-width tables. Cutting at an arbitrary character
    would break a column in half, and the reader would be reading a misaligned
    table rather than a status report. A single line longer than the limit is
    hard-cut, because the alternative is dropping it.
    """
    out: list[str] = []
    buf: list[str] = []
    size = 0
    for line in text.split("\n"):
        while len(line) > limit:
            if buf:
                out.append("\n".join(buf))
                buf, size = [], 0
            out.append(line[:limit])
            line = line[limit:]
        if size + len(line) + 1 > limit and buf:
            out.append("\n".join(buf))
            buf, size = [], 0
        buf.append(line)
        size += len(line) + 1
    if buf:
        out.append("\n".join(buf))
    return out or [""]


def send(text: str, to: str | None = None, raw: bool = False) -> str:
    """Send to the configured chat. Returns a sentence. NEVER RAISES.

    `raw` wraps each chunk whole in one `<pre>` block instead of running it
    through `format_report` — for text that does NOT follow the header/indent
    convention, such as a raw log tail or a markdown file's own headings,
    where guessing at structure would bold every line rather than none.
    Everything else — every render() this project writes — takes the default
    and gets the section-title-plus-boxed-table treatment.

    THE EMPTY-CHUNK GUARD. `format_report` of an all-blank chunk (possible
    only at a chunk boundary chunks() introduces) returns "", and Telegram
    rejects an empty message outright — so a chunk that formats to nothing
    falls back to the plain wrap rather than being dropped or failing send.
    """
    target = to or chat_id()
    if not token():
        return "telegram not configured (no TELEGRAM_BOT_TOKEN[_FILE])"
    if not target:
        return "telegram not configured (no TELEGRAM_CHAT_ID)"
    parts = chunks(text)
    sent = 0
    for part in parts:
        if raw:
            body = f"<pre>{_escape(part)}</pre>"
        else:
            body = format_report(part) or f"<pre>{_escape(part)}</pre>"
        try:
            call("sendMessage", {
                "chat_id": target,
                "text": body,
                "parse_mode": "HTML",
                "disable_web_page_preview": "true",
            })
            sent += 1
        except TelegramError as exc:
            return f"telegram FAILED after {sent}/{len(parts)} part(s): {exc}"
    return f"telegram sent to {target} ({sent} message(s))"


def get_updates(offset: int | None = None, timeout: int = 50) -> list[dict]:
    """Long-poll for inbound messages. Raises TelegramError.

    LONG-POLLING, NOT A WEBHOOK. A webhook needs a public HTTPS endpoint, which
    means exposing this laptop to the internet to read a status report. Polling
    opens no port, and when the Mac sleeps the socket simply dies and the next
    wake reconnects — the same failure mode launchd already handles for the
    collector.
    """
    return call("getUpdates", {
        "offset": offset or 0,
        "timeout": timeout,
        "allowed_updates": json.dumps(["message"]),
    }, timeout=timeout + 15)  # HTTP timeout must exceed the long-poll timeout


def whoami() -> str:
    """Print the chat id of whoever has messaged this bot.

    EXISTS SO THE TOKEN NEVER TOUCHES A SHELL. The documented way to find a
    chat id is to curl getUpdates with the token in the URL, which puts a live
    credential into shell history, into the terminal scrollback, and into any
    screenshot of it. This reads the token from the same file everything else
    does and prints only the id.
    """
    if not token():
        return "no bot token (set TELEGRAM_BOT_TOKEN[_FILE])"
    try:
        updates = call("getUpdates", {"timeout": 0}, timeout=20)
    except TelegramError as exc:
        return f"getUpdates failed: {exc}"
    seen: dict[str, str] = {}
    for u in updates:
        chat = ((u.get("message") or {}).get("chat") or {})
        if chat.get("id") is not None:
            name = chat.get("username") or chat.get("first_name") or chat.get("type", "?")
            seen[str(chat["id"])] = str(name)
    if not seen:
        return ("No messages yet. Open Telegram, send your bot any message, "
                "then run this again.")
    return "\n".join(f"  TELEGRAM_CHAT_ID={cid}   ({name})"
                      for cid, name in seen.items())


def main() -> int:
    """`python -m src.monitor.telegram [text]` — a configuration check that
    proves delivery rather than asserting it."""
    import sys

    if "--whoami" in sys.argv:
        print(whoami())
        return 0
    if not configured():
        print("telegram NOT configured.")
        print("  TELEGRAM_BOT_TOKEN[_FILE]  ", "set" if token() else "MISSING")
        print("  TELEGRAM_CHAT_ID           ", chat_id() or "MISSING")
        return 1
    try:
        me = call("getMe")
        print(f"bot: @{me.get('username')} ({me.get('first_name')})")
    except TelegramError as exc:
        print(f"getMe FAILED: {exc}")
        return 1
    text = " ".join(sys.argv[1:]) or "institutional-research: channel test."
    print(" ", send(text))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
