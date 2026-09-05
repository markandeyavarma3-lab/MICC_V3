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
    #: Trading sessions this source is MISSING behind its latest one. Each is
    #: permanent: the historical endpoint answers 503.
    gaps: tuple[date, ...] = ()
    #: The subset of `gaps` written down in sources.yml `acknowledged_gaps`.
    #: Still reported; no longer paged. See `acknowledged_gaps()`.
    acknowledged: tuple[date, ...] = ()

    @property
    def open_gaps(self) -> tuple[date, ...]:
        """Gaps nobody has written down yet. These are the ones worth waking for."""
        return tuple(d for d in self.gaps if d not in self.acknowledged)

    @property
    def alerting(self) -> bool:
        # ACKNOWLEDGED GAPS DO NOT PAGE. Until 2026-09-05 this read
        # `or bool(self.gaps)`, so the three permanently-lost sessions alerted
        # by email on every run — three times a session, forever, for something
        # nobody can act on. The terminal even printed "STALE ... 0 session(s)
        # stale", a flag and a number from two different conditions.
        #
        # This project lost 2026-08-19 because a signal reached nothing. The
        # opposite failure — a channel nobody reads because it is always red —
        # ends in the same place.
        return self.required and (
            self.last_session is None
            or self.sessions_stale >= STALE_SESSIONS
            or bool(self.open_gaps)
        )

    def render(self) -> str:
        mark = "STALE" if self.sessions_stale >= STALE_SESSIONS else "ok"
        if self.open_gaps:
            mark = f"**{len(self.open_gaps)} MISSING**"
        elif self.gaps:
            mark = f"{len(self.gaps)} lost (acknowledged)"
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


def observed_sessions() -> set[date]:
    """Sessions NSE actually traded, per the price collector's own manifest.

    WHY NOT WEEKDAYS. A weekday calendar counts Diwali and Republic Day as
    missing, so every real holiday raises a false alarm and the alert is muted
    within a week. `src/archive/prices.py` records STORED for a session that
    published a bhavcopy and NO_SESSION for a 404 on a past date — that IS the
    observed trading calendar for every day this project has collected, and it
    cost nothing extra to record.

    Falls back to an empty set before the price collector has run, in which case
    `read()` reports no gaps rather than inventing them.
    """
    if not MANIFEST.exists():
        return set()
    out: set[date] = set()
    for line in MANIFEST.read_text().splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if r.get("source_id") != "nse_bhavcopy":
            continue
        if r.get("status") in {"STORED", "DUPLICATE"} and r.get("session_date"):
            out.add(date.fromisoformat(r["session_date"][:10]))
    return out


def acknowledged_gaps() -> dict[str, tuple[date, ...]]:
    """Permanently-lost sessions, written down in sources.yml with a reason.

    READ FROM CONFIG, NOT HARDCODED. A literal list in this file would drift
    from the decision records that explain each loss, and the whole point of
    acknowledging a gap is that somebody wrote down why. If sources.yml has no
    such block, nothing is acknowledged and every gap pages — the safe default,
    because forgetting to acknowledge is noisy and forgetting to alert is not.
    """
    import yaml

    from src.common.paths import CONFIGS

    spec = yaml.safe_load((CONFIGS / "sources.yml").read_text()) or {}
    out: dict[str, list[date]] = {}
    for entry in spec.get("acknowledged_gaps") or ():
        sid, sess = entry.get("source_id"), entry.get("session")
        if not sid or not sess:
            continue
        d = sess if isinstance(sess, date) else date.fromisoformat(str(sess)[:10])
        out.setdefault(sid, []).append(d)
    return {k: tuple(sorted(v)) for k, v in out.items()}


def read() -> list[SourceHealth]:
    """Per-source health from the archive manifest. Read-only.

    GAPS, NOT JUST STALENESS. Until 2026-09-03 this kept only the LATEST session
    per source, so it could see that collection had stopped and could not see a
    hole behind it. 2026-08-19 and 2026-08-27 were both lost while HEALTH.md
    said "all sources current" — the alert was structurally incapable of the
    observation.

    Every missed session is permanent: the historical endpoint answers 503.
    """
    if not MANIFEST.exists():
        return [SourceHealth(s, None, None, 999, s in REQUIRED)
                for s in (*REQUIRED, *OPTIONAL)]

    latest: dict[str, tuple[date, datetime]] = {}
    held: dict[str, set[date]] = {}
    # EMPTY_DAY files carry no session date — an empty CSV has no first data row
    # to read one from — so they cannot go in `held`. They are still evidence
    # that we ASKED and the exchange answered "none", which is a different fact
    # from never having asked, and only the second is a loss.
    asked: dict[str, set[date]] = {}
    for line in MANIFEST.read_text().splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("status") not in {"STORED", "DUPLICATE", "EMPTY_DAY"}:
            continue
        sid, sess = r.get("source_id"), r.get("session_date")
        if sid and not sess and r.get("status") == "EMPTY_DAY" and r.get("fetched_at"):
            asked.setdefault(sid, set()).add(
                datetime.fromisoformat(r["fetched_at"]).date())
        if not sid or not sess:
            continue
        d = date.fromisoformat(sess[:10])
        got = datetime.fromisoformat(r["fetched_at"])
        held.setdefault(sid, set()).add(d)
        if sid not in latest or d > latest[sid][0]:
            latest[sid] = (d, got)

    today = datetime.now(UTC).date()
    traded = observed_sessions()
    out = []
    for sid in (*REQUIRED, *OPTIONAL):
        if sid in latest:
            d, got = latest[sid]
            mine = held.get(sid, set())
            # Only sessions inside this source's OWN collected window. A source
            # that started later than another has not "missed" the earlier ones.
            first = min(mine) if mine else d
            # A session is a GAP only if we hold no file for it AND no
            # empty-day answer covering it. The evening slots fetch the same
            # day; the 08:00 slot fetches the previous session. So an EMPTY_DAY
            # covers the trading session on its fetch date or the one before —
            # an ambiguity inherent to an undated file, resolved generously,
            # because a false "LOST" trains the reader to ignore the alert.
            covered = set()
            for f in asked.get(sid, set()):
                covered.add(f)
                prior = [t for t in traded if t < f]
                if prior:
                    covered.add(max(prior))
            gaps = tuple(sorted(
                t for t in traded
                if first < t < d and t not in mine and t not in covered
            ))
            out.append(SourceHealth(sid, d, got,
                                    _weekday_sessions_between(d, today),
                                    sid in REQUIRED, gaps,
                                    acknowledged_gaps().get(sid, ())))
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
    lost = [(r, g) for r in rows for g in r.gaps]
    if lost:
        lines += [
            "",
            "## Permanently missing sessions",
            "",
            "These traded — the price collector archived a bhavcopy for each —",
            "and no deal file was captured. The historical endpoint answers 503,",
            "so they cannot be re-fetched at any price.",
            "",
            "| source | session |",
            "|---|---|",
            *[f"| `{r.source_id}` | {g} |" for r, g in lost],
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
            (f"{r.source_id} MISSING {len(r.gaps)} session(s): "
             f"{', '.join(str(g) for g in r.gaps)}") if r.gaps else
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
        # THE FLAG AND THE NUMBER MUST DESCRIBE THE SAME CONDITION. This
        # printed `STALE ... 0 session(s) stale` for two days, because the flag
        # came from `alerting` (which gaps triggered) and the number from
        # `sessions_stale`. Two facts, one line, no way to tell them apart.
        flag = "STALE" if r.alerting else "ok   "
        last = r.last_session.isoformat() if r.last_session else "never"
        why = f"{r.sessions_stale} session(s) stale"
        if r.open_gaps:
            why += f", {len(r.open_gaps)} MISSING behind it"
        elif r.gaps:
            why += f", {len(r.gaps)} lost and acknowledged"
        print(f"  {flag}  {r.source_id:<18} last {last}  {why}")
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
