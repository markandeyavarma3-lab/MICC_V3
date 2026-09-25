"""digest.py — one screen that answers "what is going on". Decision 0070.

THREE THINGS ALREADY REPORT, AND NONE OF THEM IS THE ANSWER.

  docs/HEALTH.md          is the data stale?
  docs/STATUS.md          which plan steps are built?
  docs/DATA_INVENTORY.md  what is on disk, and is it wired?

Each is correct and each answers a question nobody asks at 9am. The question is
"did last night work, and is anything rotting?" — which needs one line from each
plus the thing none of them tracks: whether the pipeline RAN.

Written to be read in ten seconds from a terminal, and cheap enough to mail
daily without becoming noise. It does not fetch, compute or write anything.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from src.common.paths import ARCHIVE, DOCS, LOGS, ROOT
from src.monitor import backup_state, health

#: The digest's day is the OWNER's day. Under UTC the 20:30 IST run
#: falls on 15:00 UTC the same date, but a late-evening run after
#: 05:30 IST-equivalent rollover would stamp tomorrow and silently
#: skip a day. The reader lives in IST; the calendar should too.
IST = ZoneInfo("Asia/Kolkata")


def _runs(days: int = 3) -> list[tuple[str, list[str]]]:
    """Recent collector runs and the stages each reported non-zero.

    Read from the log rather than a status file, because the log is what exists
    when the run dies before writing anything else.
    """
    logs = sorted(Path(ROOT / "logs").glob("collect_*.log"))
    if not logs:
        return []
    text = logs[-1].read_text(errors="ignore").splitlines()
    out: list[tuple[str, list[str]]] = []
    stamp, failed = None, []
    for line in text:
        if line.startswith("--- "):
            if stamp:
                out.append((stamp, failed))
            stamp, failed = line[4:].split(" pid=")[0], []
        m = re.match(r"^([a-z_]+)=(\d+)$", line)
        if m and m.group(2) != "0":
            # Deduped: a stage can echo more than once in a run when an inner
            # script re-reports it, and "mart, mart" reads like two failures.
            # Canonical: pre-2026-09-17 logs say `exit` for the deal fetch.
            from src.monitor.stage_alert import canonical
            name = canonical(m.group(1))
            if name not in failed:
                failed.append(name)
    if stamp:
        out.append((stamp, failed))
    return out[-days * 3:]


#: Sources whose `session_date` is NOT a trading session. An SHP XBRL row's
#: session_date is the filing's quarter-end, so "sessions held in the last 7
#: days" read "1 session, newest 2026-09-23" on 2026-09-25 — an off-cycle
#: filing's period end, with thousands of files fetched that week unseen.
NOT_SESSION_DATED = frozenset({"nse_shp_xbrl"})


def _sessions_held(since_days: int = 7) -> dict[str, tuple[int, str]]:
    """Sessions each scheduled feed actually holds, and its newest."""
    man = ARCHIVE / "manifest.jsonl"
    if not man.exists():
        return {}
    cut = (datetime.now(UTC).date() - timedelta(days=since_days)).isoformat()
    held: dict[str, set[str]] = defaultdict(set)
    for line in man.read_text().splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        sd = r.get("session_date")
        if r.get("source_id") in NOT_SESSION_DATED:
            continue
        if (r.get("status") in {"STORED", "DUPLICATE", "EMPTY_DAY"}
                and sd and sd >= cut):
            held[r.get("source_id", "?")].add(sd)
    return {k: (len(v), max(v)) for k, v in sorted(held.items())}


#: Records the date the digest was last delivered. One line, one date.
STAMP = LOGS / ".digest_sent"


def due(today: date | None = None, stamp: Path | None = None) -> bool:
    """Has today's digest gone out yet?

    WHY THIS REPLACED A CLOCK CHECK. Until 2026-09-16 the collector sent the
    digest from `if [ "$(date +%H)" -lt 12 ]` — the 08:30 slot, and only it.
    That is a schedule masquerading as a policy, and it fails in exactly the
    case the digest exists for: if the Mac is asleep through the morning slot,
    launchd replays the run on wake, the replay lands after noon, and the day
    that most needed a report is the one day that gets none.

    The question is not "is it morning" but "has today been reported". Asking
    the second one means the digest goes out on the first run of the day at
    whatever hour that turns out to be, and still exactly once.

    A missing or unreadable stamp means DUE. Erring toward a duplicate digest
    costs one message; erring the other way costs the day's only report.
    """
    today = today or datetime.now(IST).date()
    stamp = stamp or STAMP  # resolved here, not in the signature — see read_run
    try:
        return stamp.read_text().strip() != today.isoformat()
    except OSError:
        return True


def mark(today: date | None = None, stamp: Path | None = None) -> None:
    """Record delivery. Never raises — a digest that was SENT must not be
    reported as failed because a stamp file could not be written."""
    stamp = stamp or STAMP
    try:
        stamp.parent.mkdir(parents=True, exist_ok=True)
        stamp.write_text((today or datetime.now(IST).date()).isoformat())
    except OSError:
        pass


def render() -> str:
    today = datetime.now(IST).date()
    out = [f"📊 INSTITUTIONAL RESEARCH — {today.isoformat()}", ""]

    out.append("LAST RUNS")
    runs = _runs()
    if not runs:
        out.append("  no collector log found")
    for when, failed in runs[-4:]:
        flag = "ok  " if not failed else "FAIL"
        detail = "all stages clean" if not failed else f"failed: {', '.join(failed)}"
        out.append(f"  {flag}  {when:<28} {detail}")
    out.append("")

    out.append("FEEDS — sessions held in the last 7 days")
    held = _sessions_held()
    # Width from the data, not a constant: `niftymicrocap250_constituents` is
    # 29 characters and broke a 22-wide column into a ragged edge.
    w = max((len(k) for k in held), default=0)
    for sid, (n, last) in held.items():
        out.append(f"  {sid:<{w}}  {n:>2} session(s), newest {last}")
    out.append("")

    out.append("STALENESS")
    try:
        # `render()` emits a MARKDOWN TABLE ROW for HEALTH.md. A digest read in a
        # terminal needs the same facts in prose, so they are formatted here
        # rather than by reusing a method whose output is shaped for a file.
        for r in health.read():
            last = r.last_session.isoformat() if r.last_session else "never"
            bits = [f"{r.sessions_stale} session(s) stale"]
            if r.open_gaps:
                bits.append(f"{len(r.open_gaps)} MISSING")
            elif r.gaps:
                bits.append(f"{len(r.gaps)} lost (acknowledged)")
            flag = "STALE  " if r.alerting else "ok     "
            out.append(f"  {flag}{r.source_id:<22} last {last}  {', '.join(bits)}")
    except Exception as exc:  # noqa: BLE001 - a digest must not die on one section
        out.append(f"  unavailable: {type(exc).__name__}")
    try:
        b = backup_state.read()
        out.append(f"  {'AT RISK' if b.alerting else 'ok     '} backup  {b.summary}")
    except Exception as exc:  # noqa: BLE001
        out.append(f"  backup unavailable: {type(exc).__name__}")
    out.append("")

    out.append("WHERE TO LOOK")
    out.append(f"  health     {DOCS / 'HEALTH.md'}")
    out.append(f"  status     {DOCS / 'STATUS.md'}")
    out.append(f"  inventory  {DOCS / 'DATA_INVENTORY.md'}")
    out.append(f"  verdict    {DOCS / 'reports' / 'VERDICT.md'}")
    return "\n".join(out)


def main() -> int:
    """`--once-daily` makes the caller's schedule irrelevant.

    The collector calls this on EVERY run. The first run of any given day
    delivers and stamps; every later run that day is a no-op. So the digest
    follows the machine rather than the clock — 08:30 if the Mac was awake,
    20:30 if it was not, 15:00 on a day it was opened once at three in the
    afternoon — and never twice.
    """
    import sys

    once = "--once-daily" in sys.argv
    if once and not due():
        print("digest: already delivered today; nothing sent")
        return 0

    text = render()
    print(text)
    subject = f"institutional-research digest {datetime.now(IST).date().isoformat()}"
    delivered = False
    if "--email" in sys.argv:
        result = health.notify_email(subject, text)
        print("\n  " + result)
        delivered |= result.startswith("email sent")
    if "--telegram" in sys.argv:
        from src.monitor import telegram
        result = telegram.send(text)
        print("  " + result)
        delivered |= result.startswith("telegram sent")
    # STAMP ONLY ON PROVEN DELIVERY. Stamping on attempt would mean a day when
    # the network was down is a day that is recorded as reported and never
    # retried — the same shape as the email leg that failed silently for weeks.
    if once and delivered:
        mark()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
