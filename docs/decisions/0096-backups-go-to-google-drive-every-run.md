# 0096 — Backups go to Google Drive every run; the pen drive is the second copy

**Date:** 2026-11-03
**Decided by:** Owner: "i am having google one ai pro of 5tb free plan for next
four years, so lets get start from that", and, on the nightly automation, "yeah
do that".
**Status:** ACTIVE
**Related:** 0093 (pen drive only, amended here), 0075 (the static leg),
`scripts/backup.sh`, `scripts/lib/cloud_backup.zsh`, `src/monitor/backup_state.py`.

## What changed

- **Every collector run backs up the whole project and the website to Google
  Drive**, before the pen drive is looked for. That's `institutional-research`
  (code, `.git`, the database, all of `data/`, logs) and `research-website`,
  about 20 GB. Only rebuildable things are left out: `.venv`,
  `node_modules`, the site's build output and caches
  (`scripts/lib/cloud_excludes.txt`).
- **restic, through rclone, to the owner's Google One** (folder
  `mv-research-backup`). Drive holds only encrypted chunks. Each run uploads
  only what changed, and every snapshot restores to the exact tree of its run.
- **The pen drive is optional.** When it's plugged in, the bundle and static
  leg still go there as in 0093. When it isn't, the run is GREEN on Drive
  alone and says so.
- **Upkeep is driven by age, not weekday:** old snapshots are pruned weekly
  (keep 7 daily, 4 weekly, 12 monthly), and once a month 5% of the data is
  downloaded and verified.
- **`backup_state.py` counts a Drive snapshot as a backup.** Sessions at
  risk are measured against the newer of the two copies.

## Why

0093 left one destination, and it was usually unplugged. From 2026-10-31,
every run reported FAILED and backed up nothing. Google Drive has 5 TB free to
the owner until about 2030, so one copy now lands every run with no hardware
step. Backblaze was tried first and dropped: its free tier is 10 GB, and
anything more needs a credit card the owner does not have.

## What it rests on, outside the repo

- `~/.micc_restic_pw` (mode 600): the key. Without it the backup cannot be
  opened by anyone, the owner included. The owner keeps it on paper too.
- `~/.config/rclone/rclone.conf` (mode 600): the Drive sign-in, through the
  owner's own Google OAuth client ("rclone backup", scope `drive.file`).
  That client was published to production on 2026-11-03, so the sign-in no
  longer lapses after 7 days. Its home page and privacy policy are at
  `markandeyavarma3-lab.github.io/rclone-backup-info`.
- restic 0.19.1 and rclone 1.75.2 in `~/.local/bin`, checksum-verified.

## How it fails, and how that is seen

No network, a revoked sign-in or a full Drive: restic exits nonzero, the
backup stage fails, and the run report pages it on Telegram. A stamp in
`logs/backup_cloud.txt` is written only after the new snapshot is read back
from the repository. Every restic call has a time limit (90 minutes for the
upload), so a hung upload cannot hold the stages after it.

## Verified

- **2026-11-03 16:56, first snapshot:** 2,43,050 files and 19.5 GB uploaded.
  `restic check` on 5% of the data was clean. The database, a seed file, an
  archive file and decision 0095 were restored and matched byte for byte.
- **19:28, first run through `backup.sh`:** snapshot `eb5db919`, 773 MB new,
  prune and the 5% check both passed. With the pen drive unplugged, the run
  reported GREEN.

## What would reverse this

The owner leaving Google One, or choosing to keep the project off any cloud.

## Cost accepted

- The project's data sits on Google's servers, encrypted with a key only the
  owner holds. Exchange and Kite data are stored there, not published.
- Each run uploads what changed. The database alone changes most nights, at a
  few hundred MB.
- If the password is lost, the backup is lost.
