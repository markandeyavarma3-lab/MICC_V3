#!/bin/zsh
# backup.sh — get the irreplaceable 23 MB off this machine. Phase 1 step 1.10.
#
# WHAT IS ACTUALLY IRREPLACEABLE, MEASURED 2026-08-23. The repo holds ~5 GB and
# almost none of it matters:
#
#   .git                22 MB   41 commits, all code, 36 decision records
#   db/                1.5 MB   exp_001, its frozen spec, write-once results
#   data/raw/archive    60 KB   the 17-21 Aug sessions. The endpoint answers 503,
#                               so these exist NOWHERE else and never will again
#   logs/                4 KB   the publication-time evidence available_from rests on
#   --------------------------
#   total              ~23 MB
#
# Everything else — the 1.2 GB seed, the increments, the spines, the char panel —
# was described here until 2026-09-17 as "either still in MICCV2 or rebuilt by
# one command". HALF OF THAT STOPPED BEING TRUE ON 2026-09-01, when MICCV2 was
# deleted (0042). The spines and the char panel ARE rebuilt by one command.
# data/raw/v1_export (1.2 GB), v1_increments (1.1 GB) and salvaged (6.8 GB)
# are not: NSE does not serve that history and the repos it came from are
# gone. For sixteen days their only copy was this disk, and this comment said
# otherwise. They are now the STATIC LEG below — one verified copy per
# destination, kept in sync, never rotated. Decision 0075.
#
# WHY NOT GIT ALONE. `.gitignore` correctly excludes /data/ and /db/, because a
# tracked live database is audit defect #9 and drifts. So a git remote protects
# the code and leaves exp_001's governance store and the unrecoverable sessions
# behind. This takes both.
#
# WHY A BUNDLE RATHER THAN A COPY OF .git. `git bundle` writes the entire history
# to ONE file that `git clone` reads directly. It is verifiable (`git bundle
# verify`), it cannot be half-copied, and restoring is a clone rather than an
# archaeology exercise.
#
# THE RESTORE DRILL IS NOT OPTIONAL. Plan 3 §6: "A backup nobody has restored is
# a hypothesis." This script restores what it just wrote, into a scratch
# directory, and fails loudly if the restored history does not match.

set -eu

REPO="${0:A:h:h}"
cd "$REPO"

# ONE BACKUP AT A TIME. cron and launchd BOTH run collect_daily.sh — deliberately,
# because the collector dedupes on sha256 so a duplicate fetch is a free no-op.
# The backup is not that. On 2026-09-01 08:00 they fired two seconds apart, wrote
# two 37 MB generations, interleaved their output into one log, and both hit a
# destination listing that had not caught up with their own writes. mkdir is
# atomic on every filesystem that matters, which mkfifo/flock are not portably.
LOCK="${TMPDIR:-/tmp}/institutional-research-backup.lock"
if ! mkdir "$LOCK" 2>/dev/null; then
  # A lock older than an hour outlived any real run and is a crash leftover.
  if [ -n "$(find "$LOCK" -maxdepth 0 -mmin +60 2>/dev/null)" ]; then
    echo "  clearing a stale lock (>60 min): $LOCK"
    rmdir "$LOCK" 2>/dev/null || true
    mkdir "$LOCK" 2>/dev/null || { echo "BACKUP: SKIPPED (locked)"; exit 0; }
  else
    echo "BACKUP: SKIPPED — another backup holds $LOCK"
    exit 0
  fi
fi
trap 'rmdir "$LOCK" 2>/dev/null || true' EXIT

# Default: the iCloud Drive folder the owner created for this. Overridable —
# an external SSD is the intended second destination:
#   BACKUP_DEST=/Volumes/<ssd>/institutional-research-backup ./scripts/backup.sh
DEST="${BACKUP_DEST:-$HOME/Library/Mobile Documents/com~apple~CloudDocs/institutional research/backup}"
STAMP="$(date +%Y%m%d-%H%M%S)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"; rmdir "$LOCK" 2>/dev/null || true' EXIT

echo "BACKUP  $(date '+%Y-%m-%d %H:%M:%S %Z')"
echo "  from: $REPO"
echo "  to  : $DEST"

# The bundle carries COMMITS, so uncommitted work is silently absent from it.
# This used to REFUSE on a dirty tree. That was wrong once the collector started
# running daily: it regenerates docs/HEALTH.md every morning, so the tree is
# almost always dirty, and a backup that refuses on the common case is a backup
# that never runs. Capture the diff instead — a patch beside the bundle restores
# to the exact working state, and a backup that runs beats one that is correct
# in principle and empty in practice.
DIRTY=""
if [ -n "$(git status --porcelain)" ]; then
  DIRTY="yes"
  echo "  uncommitted changes present — captured as a patch, not refused:"
  git status --short | sed 's/^/    /'
fi

mkdir -p "$DEST"

# 1. history, as one clonable file
git bundle create "$WORK/repo-$STAMP.bundle" --all >/dev/null 2>&1
git bundle verify "$WORK/repo-$STAMP.bundle" >/dev/null 2>&1 || {
  echo "  FAILED: the bundle does not verify"; exit 1; }

# 2. the things git deliberately does not track, plus any uncommitted work
if [ -n "$DIRTY" ]; then
  git diff HEAD > "$WORK/uncommitted.patch"
  git status --porcelain > "$WORK/uncommitted.status"
  tar -czf "$WORK/state-$STAMP.tar.gz" db data/raw/archive logs \
      -C "$WORK" uncommitted.patch uncommitted.status 2>/dev/null
else
  tar -czf "$WORK/state-$STAMP.tar.gz" db data/raw/archive logs 2>/dev/null
fi

# 3. a manifest, so a future reader knows what this is without guessing
{
  echo "institutional-research backup"
  echo "created      : $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
  echo "HEAD         : $(git rev-parse HEAD)"
  echo "commits      : $(git log --oneline | wc -l | tr -d ' ')"
  echo "decisions    : $(ls docs/decisions/[0-9][0-9][0-9][0-9]-*.md | wc -l | tr -d ' ')"
  echo "archived     : $(find data/raw/archive -name '*.gz' | wc -l | tr -d ' ') session files"
  echo
  echo "uncommitted  : ${DIRTY:-no}"
  echo
  echo "RESTORE:"
  echo "  git clone repo-$STAMP.bundle institutional-research"
  echo "  cd institutional-research && tar -xzf ../state-$STAMP.tar.gz"
  if [ -n "$DIRTY" ]; then
  echo "  git apply uncommitted.patch     # the working tree at backup time"
  fi
  echo
  echo "NOT IN THIS TARBALL: data/{dev,prod}/warehouse (rebuilt by:"
  echo "  python -m src.warehouse.seed && python -m src.warehouse.spine)."
  echo "STATIC LEG (0075), beside this tarball under static/ and on the pen drive"
  echo "when mounted: data/raw/v1_export, data/raw/v1_increments, data/raw/salvaged"
  echo "— 9.1 GB that changes never and can be re-fetched from nowhere. Restore by"
  echo "copying static/data/raw/* back under data/raw/. logs/backup_static.txt is"
  echo "the record of every verified sync."
} > "$WORK/MANIFEST-$STAMP.txt"

# 4. THE RESTORE DRILL — watched, not assumed
DRILL="$WORK/drill"
git clone -q "$WORK/repo-$STAMP.bundle" "$DRILL" 2>/dev/null
RESTORED_HEAD="$(git -C "$DRILL" rev-parse HEAD)"
if [ "$RESTORED_HEAD" != "$(git rev-parse HEAD)" ]; then
  echo "  FAILED: restored HEAD $RESTORED_HEAD does not match $(git rev-parse HEAD)"
  exit 1
fi
RESTORED_COMMITS="$(git -C "$DRILL" log --oneline | wc -l | tr -d ' ')"
echo "  restore drill: cloned OK, HEAD matches, $RESTORED_COMMITS commits"

# The ancestry the report cites as evidence must survive a restore, or the
# backup preserves the code and loses the proof.
if git -C "$DRILL" merge-base --is-ancestor f25608d c31e128 2>/dev/null; then
  echo "  restore drill: exp_001 registration-before-result ancestry intact"
else
  echo "  FAILED: the f25608d -> c31e128 ancestry did not survive the restore"
  exit 1
fi

mv "$WORK"/repo-$STAMP.bundle "$WORK"/state-$STAMP.tar.gz "$WORK"/MANIFEST-$STAMP.txt "$DEST/"

# THE GENERATION INDEX. Under launchd this process may not enumerate the
# destination — `~/Library/Mobile Documents` is TCC-protected and readdir comes
# back empty rather than erroring (measured 2026-09-10; see the header of
# prune_generations.zsh). So retention is driven from a local index instead of a
# directory listing, and this is the only line that appends to it.
INDEX="$REPO/logs/backup_generations.txt"
mkdir -p "$REPO/logs"
echo "$STAMP" >> "$INDEX"

"${0:A:h}/lib/prune_generations.zsh" "$DEST" "$STAMP" 3 "$INDEX"

# --- THE STATIC LEG (decision 0075) -------------------------------------------
#
# The directories that never change and cannot be re-fetched. One verified copy
# per destination, driven from a local fingerprint and verified by stat of
# known paths — never by listing the destination, which launchd cannot do under
# TCC (see prune_generations.zsh). iCloud always; the pen drive whenever it is
# mounted. A failed leg makes the RUN report it, but does not block the tarball
# above, which has already been written and drilled.
STATIC_STAMP="$REPO/logs/backup_static.txt"
STATIC_DIRS=(data/raw/v1_export data/raw/v1_increments data/raw/salvaged)
STATIC_RC=0
"${0:A:h}/lib/static_sync.zsh" "$REPO" "$DEST/static" "$STATIC_STAMP" $STATIC_DIRS || STATIC_RC=1
PEN="${BACKUP_PEN_DRIVE:-/Volumes/NO NAME/institutional-research_backup}"
if [ -d "$PEN" ]; then
  "${0:A:h}/lib/static_sync.zsh" "$REPO" "$PEN" "$STATIC_STAMP" $STATIC_DIRS || STATIC_RC=1
else
  echo "  static: pen drive not mounted ($PEN) — iCloud copy only this run"
fi

echo "  wrote: $(du -ch "$DEST"/repo-$STAMP.bundle "$DEST"/state-$STAMP.tar.gz | tail -1 | cut -f1)"
if [ "$STATIC_RC" -ne 0 ]; then
  echo "BACKUP: GREEN for the nightly bundle, STATIC LEG FAILED — the 9.1 GB is not verified at every destination"
  exit 1
fi
echo "BACKUP: GREEN"
