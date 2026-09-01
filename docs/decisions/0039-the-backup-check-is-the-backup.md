# 0039 — A backup nobody checks is a backup nobody has

**Date:** 2026-09-01
**Decided by:** Owner supplied the destination; the automation and the check
were mine, and they are a correction of my own conduct.
**Status:** ACTIVE — extends [0037](0037-backup-by-bundle-not-by-remote.md)

## Context

[0037](0037-backup-by-bundle-not-by-remote.md) was written on 2026-08-23. It
chose bundle-plus-tarball over a git remote, shipped `scripts/backup.sh` with a
restore drill that asserts the `f25608d -> c31e128` ancestry survives, and
recorded honestly that the script "**writes nothing until the owner starts one
of them**."

It then wrote nothing for **eight days**, and nothing in the repository was in a
position to say so:

- The destination defaulted to a Google Drive mount that had never been launched.
  The script's own `mkdir -p` would have created the folder path silently had it
  ever run; it did not run.
- `docs/STATUS.md` graded step 1.10 `BLOCKED` from a **hand-written string** —
  "Google Drive app not running; iCloud Drive not writable" — which was a claim,
  not a reading. It would have said the same thing after the obstacle was gone.
- `health.py` alerted on collection staleness and said nothing about backups, so
  the daily job that did exist reported GREEN while every session it collected
  sat on one disk.

Ten sessions were archived in that window. The historical endpoint answers 503,
so each existed in exactly one place on earth.

The error is not that the backup was manual. It is that **the project's own
anti-drift machinery was pointed everywhere except at this**. `status.py`'s
docstring says completion is "computed from ground truth — file existence, row
counts, whether any module outside the definer references the thing." Step 1.10
was the one step exempted from that rule, and it was the one that stayed wrong.

## Decision

Three changes, and the third is the one that matters:

1. **The default destination is the iCloud folder that exists** — the owner's
   `~/Library/Mobile Documents/.../institutional research/backup`. `BACKUP_DEST`
   still overrides; an external SSD is the intended second copy.
2. **`collect_daily.sh` runs the backup after every collection**, so a session
   and its backup are one job rather than two.
3. **`src/monitor/backup_state.py` grades the backup from the destination**,
   parsing that destination *out of `backup.sh`* so the two cannot disagree.
   `health.py` alerts on it and `status.py` derives 1.10 from it. Step 1.10's
   note is now a callable, read at render time.

The measure is **archived sessions sitting outside a backup**, not age. Code is
replaceable and the warehouse rebuilds from MICCV2 in one command; a session
fetched after the last backup is not replaceable at any price. Zero is the only
acceptable value and it is reachable, so a nonzero count means the automation
failed — which is exactly what deserves an alert.

## Why

A restore drill proves the backup *works*. It cannot prove the backup *ran*, and
for eight days those two questions had opposite answers while only the first was
being asked. Plan 3 §6 says "a backup nobody has restored is a hypothesis"; the
sharper form is that a backup nobody has **checked for** is an intention.

Rejected: leaving the backup manual and relying on the owner to run it. That is
the arrangement that just failed, and it failed against an owner who was paying
attention — the script's absence of output was simply not visible anywhere.

Rejected: a test that fails when no backup exists. It would fail on any fresh
clone and on any machine that is not the collecting one, and a test that is red
for a legitimate reason gets muted within a week. Staleness belongs in the daily
alert, which already exists and already runs.

Rejected: keeping `backup.sh`'s refusal to run on a dirty tree. The collector
regenerates `docs/HEALTH.md` every morning, so the tree is almost always dirty,
and a daily backup that refuses on the common case is a backup that never runs.
It now captures `git diff HEAD` as a patch inside the tarball instead.

## What would reverse this

The daily backup becoming a nuisance rather than a safeguard — an 11 MB write
three times a session is cheap, but if the destination is ever metered or the
repo grows an order of magnitude, the right answer is one backup per session
rather than per slot. The per-day retention added here already assumes runs are
frequent and cheap.

If iCloud sync ever proves unreliable in a way that leaves a truncated bundle,
the check as written would not notice: it reads the stamp and the head, not the
integrity of the uploaded copy. A `git bundle verify` against the destination
file would catch it and is not done, because it is a multi-second read of an
11 MB file on a synced volume three times a day.

## Cost accepted

- **The check reads the local copy, not the uploaded one.** If `bird` never
  finishes the upload, `sessions_at_risk` reads zero while the off-machine copy
  does not exist. macOS exposes no reliable CLI for per-file iCloud upload
  state — `brctl status` returns "Client zone not found" on this very folder —
  so this is a real hole and the external SSD is the answer to it, not a
  cleverer query.
- **Three generations across three days is still one destination.** Cloud sync
  propagates corruption; it does not version against it.
- **The collector now makes writes outside the repo on a schedule.** It was
  previously read-mostly, appending to an archive and a log. A daily job that
  writes 11 MB into a synced folder is a larger footprint than that.
- **1.10 is graded VERIFIED and that word is doing real work here.** It means a
  test asserts the behaviour against real data. It does not mean the backup has
  ever been restored on a *different machine*, which remains untested.
