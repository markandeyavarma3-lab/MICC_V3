"""health.py — notice when collection stops, because twice now nobody did.

WHY THIS EXISTS, WITH DATES.

  19 Aug  cron never fired. Three slots missed. The session is gone forever —
          the historical endpoint answers 503 and the working route serves only
          the current day.
  28 Aug  all three slots failed with "nodename nor servname provided": no
          network. The collector detected it, logged "This session's bytes may
          be permanently lost. Investigate today." and exited 1.

The second one was recovered on 30 August, two days later, and only because a
human happened to look. **The detection was never the problem.** The collector
has always known when it failed and has always said so, in a log nobody reads.

WHAT AN ALERT HAS TO SURVIVE. The 28 August failure was a NETWORK failure. An
alert that needs the network to report that the network is down is not an alert.
So the local channel is primary — a desktop notification and a status file that
are written with no dependency on anything outside this machine — and email is a
best-effort second channel for when nobody is at the machine.

NO CREDENTIAL LIVES IN THIS REPO. The email leg reads its password from
`ALERT_EMAIL_PASSWORD` in the environment, or from a file named by
`ALERT_EMAIL_PASSWORD_FILE`, and does nothing at all if neither is set. The
repository is public and is bundled to cloud storage nightly; a stored app
password would be a credential in both.

STALENESS IS MEASURED IN SESSIONS, NOT DAYS. A weekend is not a missed session,
and reporting Saturday as two days stale would train the reader to ignore it.

THE BACKUP IS CHECKED HERE TOO, and for the same reason the collector is: it
is a daily job whose failure is silent and whose loss is permanent. See
`backup_state.py` for why the measure is sessions-at-risk rather than age.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from src.common.paths import ARCHIVE, DOCS, ROOT
from src.monitor import backup_state

MANIFEST = ARCHIVE / "manifest.jsonl"
HEALTH_PATH = DOCS / "HEALTH.md"

#: Alert after this many missed trading sessions. One is noise — a source can
#: legitimately publish late. Two consecutive is a pattern, and both real losses
#: so far would have tripped it on the following morning.
STALE_SESSIONS = 2

#: The sources the collector is required to capture. FII/DII is not required —
#: sources.yml marks it optional — but its silence is still worth reporting.
REQUIRED = ("nse_bulk_deals", "nse_block_deals")
OPTIONAL = ("fii_dii_cash",)


@dataclass(frozen=True, slots=True)
class SourceHealth:
    source_id: str
    last_session: date | None
    last_success: datetime | None
    sessions_stale: int
    required: bool

    @property
    def alerting(self) -> bool:
        return self.required and (
            self.last_session is None or self.sessions_stale >= STALE_SESSIONS
        )

    def render(self) -> str:
        mark = "STALE" if self.alerting else "ok"
        last = self.last_session.isoformat() if self.last_session else "never"
        return (f"| `{self.source_id}` | {last} | {self.sessions_stale} | "
                f"{'yes' if self.required else 'no'} | {mark} |")


def _weekday_sessions_between(a: date, b: date) -> int:
    """Trading sessions between two dates, approximated by weekdays.

    The observed calendar in `src/common/calendar.py` is the real answer, but it
    stops at the last price we hold — 2026-08-14 — which is BEFORE every session
    this function is asked about. Using it here would report every live session
    as unmeasurable. Weekdays over-count by the handful of holidays in any short
    window, which biases toward *under*-alerting by at most a day, and that is
    the safe direction for a threshold of two.
    """
    if b <= a:
        return 0
    days = (b - a).days
    return sum(1 for i in range(1, days + 1)
               if (a + timedelta(days=i)).weekday() < 5)


def read() -> list[SourceHealth]:
    """Per-source health from the archive manifest. Read-only."""
    if not MANIFEST.exists():
        return [SourceHealth(s, None, None, 999, s in REQUIRED)
                for s in (*REQUIRED, *OPTIONAL)]

    latest: dict[str, tuple[date, datetime]] = {}
    for line in MANIFEST.read_text().splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("status") not in {"STORED", "DUPLICATE", "EMPTY_DAY"}:
            continue
        sid, sess = r.get("source_id"), r.get("session_date")
        if not sid or not sess:
            continue
        d = date.fromisoformat(sess[:10])
        got = datetime.fromisoformat(r["fetched_at"])
        if sid not in latest or d > latest[sid][0]:
            latest[sid] = (d, got)

    today = datetime.now(UTC).date()
    out = []
    for sid in (*REQUIRED, *OPTIONAL):
        if sid in latest:
            d, got = latest[sid]
            out.append(SourceHealth(sid, d, got,
                                    _weekday_sessions_between(d, today), sid in REQUIRED))
        else:
            out.append(SourceHealth(sid, None, None, 999, sid in REQUIRED))
    return out


def render(rows: list[SourceHealth], backup: backup_state.BackupState | None = None) -> str:
    alerting = [r for r in rows if r.alerting]
    if backup is not None and backup.alerting:
        alerting = [*alerting, backup]
    lines = [
        "# Collection health",
        "",
        "**Generated by `src/monitor/health.py`. Do not edit.**",
        "",
        f"Status at {datetime.now(UTC).strftime('%Y-%m-%d %H:%M')} UTC: "
        + ("**"+str(len(alerting))+" SOURCE(S) STALE**" if alerting else "all sources current"),
        "",
        "Every missed session is permanent: the historical endpoint answers 503 and",
        "the working route serves only the current day. 19 August was lost this way.",
        "28 August was nearly lost and recovered two days late, by hand.",
        "",
        "| source | last session | sessions stale | required | status |",
        "|---|---|---:|---|---|",
        *[r.render() for r in rows],
        "",
        f"Alert threshold: {STALE_SESSIONS} missed trading sessions.",
    ]
    if backup is not None:
        lines += [
            "",
            "## Off-machine backup",
            "",
            f"{'**AT RISK**' if backup.alerting else 'current'} — {backup.summary}",
            "",
            "Sessions archived after the last backup exist on one disk only: the",
            "historical endpoint answers 503, so they cannot be re-fetched at any",
            "price. Run `./scripts/backup.sh` to bring this to zero.",
        ]
    return "\n".join(lines) + "\n"


# --- channels -----------------------------------------------------------------


def notify_desktop(title: str, message: str) -> bool:
    """macOS notification. Needs no network, which is the point.

    The 28 August failure was a network failure, so the primary channel must not
    depend on one.
    """
    try:
        safe = message.replace('"', "'")[:240]
        subprocess.run(
            ["osascript", "-e",
             f'display notification "{safe}" with title "{title}"'],
            capture_output=True, timeout=10, check=False,
        )
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def notify_email(subject: str, body: str) -> str:
    """Best-effort email. Returns what happened, and never raises.

    Reads the password from ALERT_EMAIL_PASSWORD, or from the file named by
    ALERT_EMAIL_PASSWORD_FILE. No credential is stored in this repository, which
    has no backup and may become a public remote.
    """
    to = os.environ.get("ALERT_EMAIL_TO")
    sender = os.environ.get("ALERT_EMAIL_FROM", to)
    pw = os.environ.get("ALERT_EMAIL_PASSWORD")
    if not pw and (pf := os.environ.get("ALERT_EMAIL_PASSWORD_FILE")):
        p = Path(pf).expanduser()
        pw = p.read_text().strip() if p.is_file() else None
    if not (to and sender and pw):
        return "email not configured (set ALERT_EMAIL_TO/FROM and a password source)"

    import smtplib
    from email.message import EmailMessage

    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, sender, to
    msg.set_content(body)
    host = os.environ.get("ALERT_SMTP_HOST", "smtp.gmail.com")
    try:
        with smtplib.SMTP_SSL(host, 465, timeout=20) as s:
            s.login(sender, pw)
            s.send_message(msg)
        return f"email sent to {to}"
    except Exception as exc:  # noqa: BLE001 - an alert must never crash the caller
        return f"email FAILED: {type(exc).__name__}: {exc}"


def check(write_file: bool = True, send: bool = True) -> list[SourceHealth]:
    rows = read()
    backup = backup_state.read()
    if write_file:
        HEALTH_PATH.parent.mkdir(parents=True, exist_ok=True)
        HEALTH_PATH.write_text(render(rows, backup))
    if backup.alerting and send:
        # Separate from the collection alert on purpose. They fail for unrelated
        # reasons and need unrelated fixes, and a combined message trains the
        # reader to skim the one that is actually novel.
        notify_desktop("institutional-research: BACKUP AT RISK", backup.summary)
        notify_email(
            "institutional-research: backup is stale",
            f"{backup.summary}\n\nArchived sessions outside a backup cannot be "
            f"re-fetched — the historical endpoint answers 503.\n\nFix with:\n"
            f"  cd {ROOT} && ./scripts/backup.sh\n",
        )
    alerting = [r for r in rows if r.alerting]
    if alerting and send:
        detail = ", ".join(
            f"{r.source_id} last {r.last_session or 'never'} ({r.sessions_stale} sessions)"
            for r in alerting
        )
        notify_desktop("institutional-research: COLLECTION STALE", detail)
        notify_email(
            "institutional-research: collection is stale",
            f"{detail}\n\nEvery missed session is permanent — the historical "
            f"endpoint answers 503.\n\nRecover with:\n"
            f"  cd {ROOT} && ./scripts/collect_daily.sh\n\n"
            f"The endpoint serves the last trading session until the next one "
            f"publishes, so a same-day or next-morning run usually still gets it.",
        )
    return rows


def main() -> int:
    rows = check()
    print("COLLECTION HEALTH")
    for r in rows:
        flag = "STALE" if r.alerting else "ok   "
        last = r.last_session.isoformat() if r.last_session else "never"
        print(f"  {flag}  {r.source_id:<18} last {last}  {r.sessions_stale} session(s) stale")
    b = backup_state.read()
    print(f"  {'AT RISK' if b.alerting else 'ok   '}  {'off-machine backup':<18} {b.summary}")
    alerting = [r for r in rows if r.alerting]
    print(f"\n  {HEALTH_PATH.relative_to(ROOT)} written")
    if b.alerting:
        print("  ALERTED on backup")
    if alerting:
        print(f"  ALERTED on {len(alerting)} source(s)")
        print(f"  email: {notify_email.__doc__.splitlines()[0]}")
    return 1 if (alerting or b.alerting) else 0


if __name__ == "__main__":
    raise SystemExit(main())
