# 0093 — Backups go to the pen drive only

**Date:** 2026-10-30
**Decided by:** Owner: "from now we will backup only in pendrive, no icloud or onecloud".
**Status:** ACTIVE
**Related:** 0075 (the static leg), `scripts/backup.sh`, `src/monitor/backup_state.py`.

## What changed

- The nightly bundle (git history, state, manifest) goes to
  `/Volumes/NO NAME/institutional-research_backup/nightly`. It no longer goes to iCloud.
- The static 9.1 GB leg stays at the pen drive's root, where it already was.
  It is no longer copied to iCloud.
- If the pen drive is not plugged in, the backup stage fails at once with a
  plain message, and the health check reports the backup at risk. With one
  destination, a missing drive is a missing backup, and it is said so.

## Why

The owner's choice: one physical copy under their control, and no cloud.

## What would reverse this

The owner choosing a cloud or second destination again.

## Cost accepted

- One copy, in one place: a lost or failed pen drive leaves only the working
  disk until the next backup.
- No backup runs while the drive is unplugged. The health check says so every
  run until it is plugged in.
- The old iCloud copies are left in place, not deleted. The owner removes them
  when they choose.
