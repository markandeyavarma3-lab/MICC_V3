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

import pathlib
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
    """Retention over the generations present in `d`.

    Since 2026-09-10 the script is driven by an index file rather than a
    directory listing, so the helper writes one describing the fixture. Without
    it these calls would fall back to the REPOSITORY's real index, find none of
    their own stamps in it, and skip — passing for the wrong reason.
    """
    index = pathlib.Path(d) / "_index.txt"
    found = sorted(p.name[len("repo-"):-len(".bundle")]
                   for p in pathlib.Path(d).glob("repo-*.bundle"))
    index.write_text("\n".join(found) + ("\n" if found else ""))
    return _run_idx(d, stamp, str(index), keep)


def _run_idx(d, stamp: str, index: str, keep: int = 3) -> str:
    r = subprocess.run([str(PRUNE), str(d), stamp, str(keep), index],
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


# --- the listing that was never readable -------------------------------------
#
# The tests above run against a local tmp_path where a directory can be listed.
# That is why they passed for nine days while retention never ran once in
# production: under launchd the destination CANNOT BE ENUMERATED. Measured
# 2026-09-10, same script, same path, same minute — interactive saw 26 bundles
# and 78 entries; launchd saw 0 and 1, while stat on a known path worked in both.
#
# `~/Library/Mobile Documents` is TCC-protected. Decision 0053 misread the empty
# listing as an iCloud lag and added a retry loop; retrying a permission denial
# produces more denials, and the backup grew from 11 generations to 26 (2.5 GB)
# while the log reported the fix was in.


def _index(d, stamps) -> str:
    p = d / "index.txt"
    p.write_text("\n".join(stamps) + "\n")
    return str(p)


def test_retention_works_when_the_directory_cannot_be_listed(tmp_path):
    """THE ONE THAT MATTERS NOW.

    `chmod 300` is the faithful reproduction of what launchd sees: traverse and
    write are permitted, listing is not. `chmod 100` is NOT — it also denies
    unlink, which made the first version of this test report a false failure.

    Retention must complete here using only the index and explicit paths.
    """
    dest = tmp_path / "dest"
    dest.mkdir()
    stamps = ["20260901-100000", "20260902-100000", "20260903-100000",
              "20260904-100000", "20260905-100000"]
    for st in stamps:
        _gen(dest, st)
    idx = _index(tmp_path, stamps)

    dest.chmod(0o300)
    try:
        out = _run_idx(dest, "20260905-100000", idx)
    finally:
        dest.chmod(0o700)

    assert "pruned generation 20260901-100000" in out
    assert _stamps(dest) == {"20260903-100000", "20260904-100000", "20260905-100000"}


def test_the_script_never_enumerates_the_destination_to_decide(tmp_path):
    """An empty listing and a forbidden listing are indistinguishable, so an
    empty one may never be read as "nothing to keep"."""
    src = PRUNE.read_text()
    assert "no generation index" in src, "the index is not the source of truth"
    # The one glob that remains is a RECONCILIATION, and it must be guarded by a
    # count check rather than used directly as the keep-list.
    assert "if (( ${#seen} > 0 )); then" in src


def test_a_missing_index_prunes_nothing(tmp_path):
    dest = tmp_path / "dest"
    dest.mkdir()
    for st in ("20260901-100000", "20260902-100000"):
        _gen(dest, st)
    out = _run_idx(dest, "20260902-100000", str(tmp_path / "absent.txt"))
    assert "skipped" in out
    assert len(_stamps(dest)) == 2


def test_a_stamp_absent_from_the_index_refuses_to_delete(tmp_path):
    """Same trust condition as before; only the source of the listing changed.
    If the index does not describe this run, it cannot authorise deletes."""
    dest = tmp_path / "dest"
    dest.mkdir()
    stamps = ["20260901-100000", "20260902-100000", "20260903-100000",
              "20260904-100000"]
    for st in stamps:
        _gen(dest, st)
    idx = _index(tmp_path, stamps)
    out = _run_idx(dest, "29990101-000000", idx)
    assert "SKIPPED" in out
    assert len(_stamps(dest)) == 4


def test_the_index_is_reconciled_when_listing_is_possible(tmp_path):
    """A stale index must heal rather than delete the wrong set. Where the
    directory CAN be read, reality wins over the index."""
    dest = tmp_path / "dest"
    dest.mkdir()
    for st in ("20260903-100000", "20260904-100000", "20260905-100000"):
        _gen(dest, st)
    # index claims a generation that no longer exists, and misses two that do
    idx = _index(tmp_path, ["20260101-000000", "20260905-100000"])
    _run_idx(dest, "20260905-100000", idx)
    assert "20260101-000000" not in pathlib.Path(idx).read_text()
