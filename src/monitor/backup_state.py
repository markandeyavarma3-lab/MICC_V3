"""backup_state.py — is there a current off-machine backup, and what is missing from it?

WHY THIS IS A MODULE AND NOT A GLANCE AT THE FOLDER.

[0037](../../docs/decisions/0037-backup-by-bundle-not-by-remote.md) shipped
`scripts/backup.sh` and closed nothing, because the script's default destination
was a cloud mount that had never been launched. For eight days the repository
contained a working backup tool, a passing restore drill, and zero backups. The
gap between "the artefact exists" and "the step is done" is the same gap
`status.py` was written to close, and it reopened here.

So the destination is read FROM THE SCRIPT, never restated. If the two ever
disagree, the one that actually writes files wins, and this module follows it.

WHAT STALENESS MEANS HERE, AND IT IS NOT DAYS.

The bundle carries commits; the tarball carries `db/`, `logs/` and the archived
sessions. Only one of those is irreplaceable. Code can be rewritten and the
warehouse rebuilds from MICCV2 in one command, but a trading session archived
after the last backup exists in exactly one place on earth, because the
historical endpoint answers 503 and the working route serves only the current
day. 19 August is already gone that way.

So the measure is **sessions at risk**: archived sessions fetched after the most
recent backup ran. Zero is the only acceptable number, and it is reachable —
`collect_daily.sh` backs up straight after collecting, so a nonzero count means
the automation itself failed, which is exactly what deserves an alert.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from src.common.paths import ARCHIVE, ROOT

SCRIPT = ROOT / "scripts" / "backup.sh"
MANIFEST = ARCHIVE / "manifest.jsonl"

#: `repo-YYYYmmdd-HHMMSS.bundle`, written by backup.sh step 1.
STAMP_RE = re.compile(r"repo-(\d{8}-\d{6})\.bundle$")


def destination() -> Path | None:
    """Where backup.sh actually writes, parsed from backup.sh.

    BACKUP_DEST wins, exactly as it does in the script — otherwise a run against
    an external SSD would be invisible to the very check meant to notice it.
    """
    if env := os.environ.get("BACKUP_DEST"):
        return Path(env).expanduser()
    if not SCRIPT.exists():
        return None
    m = re.search(r'^DEST="\$\{BACKUP_DEST:-(.+?)\}"$', SCRIPT.read_text(), re.M)
    if not m:
        return None
    return Path(m.group(1).replace("$HOME", str(Path.home())))


@dataclass(frozen=True, slots=True)
class BackupState:
    destination: Path | None
    #: Newest generation's bundle, or None if the destination holds none.
    bundle: Path | None
    taken_at: datetime | None
    #: Commits on HEAD that no backup carries. Recoverable in principle; listed
    #: because it is the cheapest signal that a run was skipped.
    commits_behind: int
    #: Archived sessions fetched after the newest backup. NOT recoverable.
    sessions_at_risk: int
    generations: int

    @property
    def alerting(self) -> bool:
        """No backup at all, or an irreplaceable session sitting outside one."""
        return self.bundle is None or self.sessions_at_risk > 0

    @property
    def summary(self) -> str:
        if self.destination is None:
            return "no destination configured"
        if self.bundle is None:
            return f"NO BACKUP in {self.destination}"
        when = self.taken_at.strftime("%Y-%m-%d %H:%M") if self.taken_at else "unknown"
        return (f"newest {when} UTC, {self.generations} generation(s), "
                f"{self.commits_behind} commit(s) and "
                f"{self.sessions_at_risk} archived session(s) not in it")


def _sessions_after(cut: datetime) -> int:
    """Distinct archived sessions whose bytes arrived after `cut`.

    Keyed on `fetched_at`, not `session_date`: a session recovered by hand days
    late — as 28 August was — is at risk from the moment it lands, not from the
    date it belongs to.
    """
    if not MANIFEST.exists():
        return 0
    at_risk: set[str] = set()
    for line in MANIFEST.read_text().splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if r.get("status") not in {"STORED", "EMPTY_DAY"}:
            continue  # DUPLICATE adds no bytes, so it puts nothing at risk
        got, sess = r.get("fetched_at"), r.get("session_date")
        if not (got and sess):
            continue
        when = datetime.fromisoformat(got)
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        if when > cut:
            at_risk.add(f"{r.get('source_id')}:{sess[:10]}")
    return len(at_risk)


def _commits_behind(bundle: Path) -> int:
    """Commits on local HEAD that the bundle does not carry.

    The bundle was made from this repo, so its tip is an object we already hold
    and `rev-list` can answer directly without unpacking anything.
    """
    try:
        heads = subprocess.run(["git", "bundle", "list-heads", str(bundle)],
                               capture_output=True, text=True, timeout=60, cwd=ROOT)
        tip = next((ln.split()[0] for ln in heads.stdout.splitlines()
                    if ln.endswith("refs/heads/main")), None)
        if tip is None:
            return -1
        out = subprocess.run(["git", "rev-list", "--count", f"{tip}..HEAD"],
                             capture_output=True, text=True, timeout=60, cwd=ROOT)
        return int(out.stdout.strip()) if out.returncode == 0 else -1
    except (OSError, subprocess.SubprocessError, ValueError):
        return -1


def read() -> BackupState:
    """Read-only. Never writes, never runs a backup."""
    dest = destination()
    if dest is None or not dest.is_dir():
        return BackupState(dest, None, None, -1, _sessions_after(datetime.min.replace(tzinfo=UTC)), 0)

    stamped = sorted(
        ((m.group(1), p) for p in dest.glob("repo-*.bundle") if (m := STAMP_RE.search(p.name))),
    )
    if not stamped:
        return BackupState(dest, None, None, -1,
                           _sessions_after(datetime.min.replace(tzinfo=UTC)), 0)

    stamp, newest = stamped[-1]
    # The stamp is local time (backup.sh uses `date +...`); compare in UTC.
    taken = datetime.strptime(stamp, "%Y%m%d-%H%M%S").astimezone().astimezone(UTC)
    return BackupState(dest, newest, taken, _commits_behind(newest),
                       _sessions_after(taken), len(stamped))
