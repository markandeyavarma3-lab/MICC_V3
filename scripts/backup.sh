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
# is either still in MICCV2 or rebuilt by one command. It is bulk, not value.
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

DEST="${BACKUP_DEST:-$HOME/Library/CloudStorage/GoogleDrive-markandeya0397@gmail.com/My Drive/institutional-research-backup}"
STAMP="$(date +%Y%m%d-%H%M%S)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

echo "BACKUP  $(date '+%Y-%m-%d %H:%M:%S %Z')"
echo "  from: $REPO"
echo "  to  : $DEST"

# Refuse to back up a repo with uncommitted work: the bundle carries COMMITS, so
# anything uncommitted is silently not in it. Better to stop than to write a
# backup that quietly omits today's work.
if [ -n "$(git status --porcelain)" ]; then
  echo "  REFUSING: uncommitted changes. The bundle carries commits only, so this"
  echo "  backup would silently omit them. Commit or stash first:"
  git status --short | sed 's/^/    /'
  exit 1
fi

mkdir -p "$DEST"

# 1. history, as one clonable file
git bundle create "$WORK/repo-$STAMP.bundle" --all >/dev/null 2>&1
git bundle verify "$WORK/repo-$STAMP.bundle" >/dev/null 2>&1 || {
  echo "  FAILED: the bundle does not verify"; exit 1; }

# 2. the things git deliberately does not track
tar -czf "$WORK/state-$STAMP.tar.gz" db data/raw/archive logs 2>/dev/null

# 3. a manifest, so a future reader knows what this is without guessing
{
  echo "institutional-research backup"
  echo "created      : $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
  echo "HEAD         : $(git rev-parse HEAD)"
  echo "commits      : $(git log --oneline | wc -l | tr -d ' ')"
  echo "decisions    : $(ls docs/decisions/[0-9][0-9][0-9][0-9]-*.md | wc -l | tr -d ' ')"
  echo "archived     : $(find data/raw/archive -name '*.gz' | wc -l | tr -d ' ') session files"
  echo
  echo "RESTORE:"
  echo "  git clone repo-$STAMP.bundle institutional-research"
  echo "  cd institutional-research && tar -xzf ../state-$STAMP.tar.gz"
  echo
  echo "NOT INCLUDED, and deliberately: data/raw/v1_export, data/raw/v1_increments,"
  echo "data/{dev,prod}/warehouse. ~4.6 GB, all of it either still in MICCV2 or"
  echo "rebuilt by:  python -m src.warehouse.seed && python -m src.warehouse.spine"
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

# Keep the three most recent generations; a backup directory that grows forever
# is one nobody prunes and eventually one nobody trusts.
ls -1t "$DEST"/repo-*.bundle 2>/dev/null | tail -n +4 | while read -r old; do
  s="${old:t:r}"; s="${s#repo-}"
  rm -f "$DEST/repo-$s.bundle" "$DEST/state-$s.tar.gz" "$DEST/MANIFEST-$s.txt"
  echo "  pruned generation $s"
done

echo "  wrote: $(du -ch "$DEST"/repo-$STAMP.bundle "$DEST"/state-$STAMP.tar.gz | tail -1 | cut -f1)"
echo "BACKUP: GREEN"
