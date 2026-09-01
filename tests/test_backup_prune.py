"""Retention for the backup, and the delete that nearly happened.

On 2026-09-01 the prune logic lived inside backup.sh, ran on every scheduled
collection, and did three things at once:

  - errored on every run (`no matches found`), because in zsh it is the SHELL
    that expands a glob, so `ls ... 2>/dev/null` suppresses nothing;
  - pruned nothing, so same-day generations accumulated;
  - computed an EMPTY keep-list from that failed listing, which marks every
    generation as unkept. The loop that followed would have deleted all of them.

It survived only because the same empty listing also starved the delete loop.
The trigger was not exotic: the destination is an iCloud FileProvider volume,
and a 37 MB file moved into it was not in the very next directory listing.

These tests exist because none of the above was reachable by a test until the
logic was pulled out into `scripts/lib/prune_generations.zsh`.
"""

from __future__ import annotations

import subprocess

import pytest

from src.common.paths import ROOT

pytestmark = pytest.mark.unit

PRUNE = ROOT / "scripts" / "lib" / "prune_generations.zsh"


def _gen(d, stamp: str) -> None:
    (d / f"repo-{stamp}.bundle").write_bytes(b"bundle")
    (d / f"state-{stamp}.tar.gz").write_bytes(b"state")
    (d / f"MANIFEST-{stamp}.txt").write_text("manifest")


def _run(d, stamp: str, keep: int = 3):
    r = subprocess.run([str(PRUNE), str(d), stamp, str(keep)],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return r.stdout


def _stamps(d) -> set[str]:
    return {p.name[len("repo-"):-len(".bundle")] for p in d.glob("repo-*.bundle")}


def test_an_empty_listing_never_authorises_a_delete(tmp_path):
    """THE ONE THAT MATTERS.

    An empty keep-list marked every generation as unkept. If the listing had
    been stale rather than empty — one file visible out of four — the loop would
    have deleted the three it could see.
    """
    for s in ("20260830-200000", "20260831-200000", "20260901-080000"):
        _gen(tmp_path, s)
    # The generation just written is NOT in the listing: exactly the iCloud case.
    out = _run(tmp_path, "20260901-080028")

    assert "SKIPPED" in out, "a listing that cannot see its own write must delete nothing"
    assert len(_stamps(tmp_path)) == 3, "an untrusted listing deleted generations"


def test_a_glob_that_matches_nothing_is_not_an_error(tmp_path):
    """`ls -1 dir/*.bundle 2>/dev/null` does not silence zsh's `no matches
    found` — the shell raises it before ls runs. It printed to the collector
    log on every scheduled run."""
    out = _run(tmp_path, "20260901-080000")
    assert "no matches found" not in out
    assert "skipped" in out.lower()


def test_the_newest_run_of_each_kept_day_survives(tmp_path):
    """Retention is per DAY, not per run: collect_daily.sh fires three times a
    session, so keeping three runs would keep three copies made inside fourteen
    hours — one corruption, three infected generations."""
    for s in ("20260830-200000", "20260831-200000",
              "20260901-073451", "20260901-080000", "20260901-080028"):
        _gen(tmp_path, s)
    _run(tmp_path, "20260901-080028")

    assert _stamps(tmp_path) == {
        "20260830-200000", "20260831-200000", "20260901-080028"
    }, "expected the newest run of each of the three most recent days"


def test_older_days_fall_out_of_the_window(tmp_path):
    for s in ("20260828-200000", "20260829-200000", "20260830-200000",
              "20260831-200000", "20260901-080028"):
        _gen(tmp_path, s)
    _run(tmp_path, "20260901-080028")
    assert _stamps(tmp_path) == {
        "20260830-200000", "20260831-200000", "20260901-080028"
    }


def test_every_file_of_a_pruned_generation_goes(tmp_path):
    """A bundle removed while its tarball stays leaves 25 MB of orphaned state
    that no manifest describes."""
    for s in ("20260901-070000", "20260901-080028"):
        _gen(tmp_path, s)
    _run(tmp_path, "20260901-080028")
    assert not list(tmp_path.glob("*20260901-070000*")), "orphaned files left behind"
    assert len(list(tmp_path.glob("*20260901-080028*"))) == 3


def test_the_generation_just_written_is_never_pruned(tmp_path):
    """Belt and braces. keep=1 with an older same-day run must still leave the
    new one; deleting what you just wrote is the one unrecoverable outcome."""
    for s in ("20260901-070000", "20260901-080028"):
        _gen(tmp_path, s)
    _run(tmp_path, "20260901-080028", keep=1)
    assert (tmp_path / "repo-20260901-080028.bundle").exists()


def test_a_single_day_is_not_an_empty_keep_window(tmp_path):
    """`keep_days[-3,-1]` on a one-element array returns EMPTY in zsh — it does
    not clamp. That produced the delete-everything keep-list from perfectly
    healthy input: one day held, three requested. The guard caught it, but the
    arithmetic reached production."""
    _gen(tmp_path, "20260901-070000")
    _gen(tmp_path, "20260901-080028")
    out = _run(tmp_path, "20260901-080028", keep=3)

    assert "no day survived" not in out, (
        "one day of backups must not read as an empty keep window"
    )
    assert _stamps(tmp_path) == {"20260901-080028"}
