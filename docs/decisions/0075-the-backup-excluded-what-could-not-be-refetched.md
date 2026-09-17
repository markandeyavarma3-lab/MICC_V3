# 0075 — The backup excluded exactly the data that cannot be re-fetched

**Date:** 2026-09-17
**Decided by:** Me, at the owner's "fix all those", after they had first chosen
to defer it; the same afternoon the pen drive — the only second copy — was
unplugged, which made the deferral's cost concrete.
**Status:** accepted
**Related:** 0042 (MICCV2 deleted 2026-09-01, salvage), 0053 (the backup leg
and its TCC lesson), 0037 (backup left manual, went eight days).

## The gap, and how long it was open

`scripts/backup.sh` tars `db/`, `data/raw/archive` and `logs/` nightly and
keeps three generations. It excluded `data/raw/v1_export` (1.2 GB),
`v1_increments` (1.1 GB) and — never mentioned at all — `salvaged` (6.8 GB),
on the recorded grounds that they were *"either still in MICCV2 or rebuilt by
one command."*

MICCV2 was deleted on 2026-09-01 (0042). From that day the only copy of 9.1 GB
that NSE will never serve again was this Mac's disk, and the comment saying
otherwise stayed in the script for sixteen days. `paths.py` called every one
of those directories "irreplaceable" the whole time. Two files in the same
repo disagreed about whether the project's most valuable bytes were backed
up, and nothing compared them.

Found while making a one-off pen-drive copy on 2026-09-17. The owner chose
"the pen drive is enough for now". Hours later the drive was unplugged and the
count of second copies was zero again.

## Decision

A **static leg** in `backup.sh`, after the bundle and its restore drill:
`scripts/lib/static_sync.zsh` pushes the three directories to `$DEST/static`
on iCloud (40 GB of quota free, measured with `brctl quota`) and to the pen
drive whenever it is mounted. One verified copy per destination, never
rotated, re-copied only when the source fingerprint changes or a destination
fails verification.

**It never lists the destination.** 0053 measured that under launchd the
iCloud folder can be written and stat'ed at a known path but not enumerated;
a plain `rsync` would compare against an empty listing and re-copy 9 GB every
night while reporting success. So the source listing (path + size, hashed to
a fingerprint) drives the push (`rsync --files-from`), and verification is a
`stat` of each known destination path with a size compare. The stamp
`logs/backup_static.txt` is written only after that verification passes, and
is never trusted without re-running it — a destination can be wiped or
replaced between runs.

`backup_state.py` reads the stamp. The backup line in HEALTH, the digest and
`/health` now ends with *"static 9.1 GB verified at iCloud 2026-09-17"* — or
*"VERIFIED NOWHERE"*, which is what it would have said every day since
2026-09-01 had it existed. A never-verified static leg alerts.

First sync 2026-09-17 20:26–21:12 IST: **18,220 files, 9,280 MB, verified by
stat on iCloud.** The nightly bundle was GREEN throughout; the leg failing
would have reported it without blocking the bundle.

## What was found writing it

`local dz` inside a zsh loop: on the second iteration, re-declaring an
already-set local *prints* `dz=2` instead of declaring, and that line landed
in the captured failure count as `dz=2\n0` — a math error at the caller.
Found on the second file of the first smoke test; declared once, above the
loop. Six tests pin the leg's behaviour, including that a stamp is never
trusted without re-verification (perturbed: two tests fail).

## What would reverse this

- **iCloud quota running out.** 9.3 GB of 40 GB free today; the archive grows
  ~0.5 GB a quarter with SHP. If the static push starts failing on space, the
  leg reports it and the bundle continues; the fix is a bigger plan or a
  different destination, not removing the leg.
- **The fingerprint changing.** These directories are meant never to change.
  A changed fingerprint is either a deliberate salvage addition (0042-style,
  with a record) or corruption, and either way a full re-push is the right
  response. If it happens without a record, that is the alarm.
- **A launchd run failing verification that an interactive run passes.**
  That would mean `stat` on iCloud paths is also blocked under TCC on some
  macOS version. The remedy is Full Disk Access for the agent, recorded.

## Cost accepted

- **9.3 GB of iCloud**, once, plus the same on the pen drive when present.
- **~18,000 `stat` calls per nightly run** on the iCloud folder — seconds,
  measured — so that "in sync" is a verified statement and not a stamp.
- **A backup that can now fail for a third reason.** The leg's failure is
  reported and exits 1 so the collector's `backup` stage pages it; the
  tarball above it is unaffected. That is the correct order of concerns.
