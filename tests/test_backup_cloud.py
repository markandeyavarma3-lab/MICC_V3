"""The Google Drive leg (0096): every run, before the pen drive is looked for.

From 2026-10-31 the pen drive was not plugged in and every run backed up
nothing. These tests hold the two properties that fix rests on: the Drive leg
runs whether or not the pen drive is there, and it never stamps a snapshot that
did not land.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from src.common.paths import ROOT

pytestmark = pytest.mark.unit

CLOUD = ROOT / "scripts" / "lib" / "cloud_backup.zsh"
BACKUP = ROOT / "scripts" / "backup.sh"
RESTIC = Path.home() / ".local" / "bin" / "restic"


def _run(*args, env=None):
    return subprocess.run([str(CLOUD), *map(str, args)], capture_output=True, text=True,
                          env={**os.environ, **(env or {})}, timeout=120)


def test_no_paths_is_a_usage_error(tmp_path):
    assert _run(tmp_path / "stamp").returncode == 2


def test_a_missing_path_is_a_usage_error_not_an_empty_backup(tmp_path):
    r = _run(tmp_path / "stamp", tmp_path / "absent")
    assert r.returncode == 2
    assert not (tmp_path / "stamp").exists()


def test_the_drive_leg_runs_before_the_pen_drive_is_looked_for():
    """Behind the pen check, an unplugged drive would skip Drive too: the
    failure 0096 exists to end."""
    s = BACKUP.read_text()
    assert s.index("lib/cloud_backup.zsh") < s.index('if [ ! -d "${PEN:h}" ]; then')


@pytest.mark.skipif(not RESTIC.exists() or shutil.which("rclone", path=str(RESTIC.parent)) is None,
                    reason="restic/rclone not installed")
def test_a_failed_upload_writes_no_stamp(tmp_path):
    """A stamp is what backup_state.py counts as a backup, so a run that did not
    land must leave none. A local repository that does not exist fails at once,
    with no network."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "f").write_text("x")
    pw = tmp_path / "pw"
    pw.write_text("not-the-real-one")
    r = _run(tmp_path / "logs" / "backup_cloud.txt", tmp_path / "src",
             env={"RESTIC_REPOSITORY": str(tmp_path / "no_repo"), "RESTIC_PASSWORD_FILE": str(pw)})
    assert r.returncode == 1, r.stdout + r.stderr
    assert "FAILED" in r.stdout
    assert not (tmp_path / "logs" / "backup_cloud.txt").exists()
