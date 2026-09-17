#!/bin/zsh
# static_sync.zsh — one verified copy of the data that never changes. Decision 0075.
#
# usage: static_sync.zsh <repo> <dest> <stamp-file> [dir ...]
#   exit 0  in sync (verified), stamp updated
#   exit 1  not in sync after attempting (some file missing or wrong size at dest)
#   exit 2  usage / source missing
#
# =============================================================================
# WHAT THIS PROTECTS, AND WHY THE NIGHTLY BUNDLE NEVER DID
# =============================================================================
#
# backup.sh tars db/, data/raw/archive and logs/ every night and keeps three
# generations. It EXCLUDES data/raw/v1_export, v1_increments and salvaged on
# the recorded grounds that they are "either still in MICCV2 or rebuilt by one
# command". MICCV2 was deleted on 2026-09-01. Since that day the only copy of
# 9.1 GB that NSE will never serve again has been this Mac's disk, and the
# comment saying otherwise stayed in the script for sixteen days.
#
# These directories never change. Bundling 9 GB into a rotating tarball every
# night would be the wrong shape twice over: wasteful, and rotated out. The
# right shape is ONE copy per destination, verified file by file, re-copied only
# when the source fingerprint changes (it should not) or a destination fails
# verification.
#
# =============================================================================
# WHY IT NEVER LISTS THE DESTINATION
# =============================================================================
#
# Same lesson as prune_generations.zsh, measured 2026-09-10: under launchd the
# iCloud folder can be written and stat'ed at a known path but NOT enumerated —
# readdir comes back empty, silently. A plain `rsync -a src dest` compares
# against a listing of dest, sees nothing, and re-copies 9 GB every night while
# reporting success. So the SOURCE listing drives everything: files are pushed
# with --files-from, and verification is a stat of each known destination path
# with a size compare. No step here asks the destination what it contains.

set -u
setopt NO_NOMATCH

REPO="${1:-}"; DEST="${2:-}"; STAMP="${3:-}"
shift 3 2>/dev/null || { echo "usage: static_sync.zsh <repo> <dest> <stamp> [dir ...]"; exit 2; }
DIRS=("$@")
[[ -z "$REPO" || -z "$DEST" || -z "$STAMP" || ${#DIRS} -eq 0 ]] && { echo "usage: static_sync.zsh <repo> <dest> <stamp> [dir ...]"; exit 2; }
cd "$REPO" || exit 2
for d in $DIRS; do [[ -d "$d" ]] || { echo "  static: source $d missing under $REPO"; exit 2; }; done

# 1. The source listing: path and size for every file, sorted, on ordinary disk.
#    Its hash is the fingerprint. Unchanged fingerprint + verified dest = nothing to do.
LIST="$(mktemp)"
trap 'rm -f "$LIST" "$LIST.paths"' EXIT
for d in $DIRS; do
  find "$d" -type f -not -name '.DS_Store' -exec stat -f '%N%t%z' {} + 2>/dev/null
done | LC_ALL=C sort > "$LIST"
FILES=$(wc -l < "$LIST" | tr -d ' ')
BYTES=$(awk -F'\t' '{s+=$2} END{print s+0}' "$LIST")
FP=$(shasum -a 256 "$LIST" | cut -c1-16)
cut -f1 "$LIST" > "$LIST.paths"

verify() {  # stat every known path at the destination; size must match
  # `local dz` is declared ONCE, above the loop: in zsh a second `local` of an
  # already-set variable PRINTS "dz=<value>" instead of declaring, and that
  # line landed in the captured count as "dz=2\n0" — a math error at the
  # caller. Found on the second file of the first smoke test.
  local bad=0 n=0 dz
  while IFS=$'\t' read -r p sz; do
    n=$((n+1))
    dz=$(stat -f '%z' "$DEST/$p" 2>/dev/null) || { bad=$((bad+1)); continue; }
    [[ "$dz" == "$sz" ]] || bad=$((bad+1))
  done < "$LIST"
  echo "$bad"
}

# 2. Already verified for THIS fingerprint at THIS destination? Cheap re-verify
#    (stat only) and done. A stamp is never trusted without the re-verify: a
#    destination can be wiped, unmounted and replaced, or half-restored.
prior=$(grep -F "	$DEST	" "$STAMP" 2>/dev/null | tail -1 | cut -f1)
if [[ "$prior" == "$FP" ]]; then
  bad=$(verify)
  if [[ "$bad" -eq 0 ]]; then
    echo "  static: in sync at $DEST — $FILES files, $(( BYTES / 1048576 )) MB, fingerprint $FP (verified by stat)"
    exit 0
  fi
  echo "  static: stamp says in sync but $bad file(s) fail verification at $DEST — re-syncing"
fi

# 3. Push from the source listing. -a keeps mtimes (the cheap change detector on
#    the next pass); no --delete, a backup never deletes; --files-from so
#    nothing here depends on listing the destination.
mkdir -p "$DEST" 2>/dev/null || { echo "  static: cannot create $DEST"; exit 1; }
if ! rsync -a --files-from="$LIST.paths" "$REPO/" "$DEST/" 2>&1 | sed 's/^/    rsync: /'; then
  echo "  static: rsync reported errors at $DEST (see above); verifying what landed"
fi

# 4. Verify by stat, then stamp. The stamp is one line per (fingerprint, dest).
bad=$(verify)
if [[ "$bad" -ne 0 ]]; then
  echo "  static: NOT in sync at $DEST — $bad of $FILES file(s) missing or wrong size after sync"
  exit 1
fi
mkdir -p "${STAMP:h}"
printf '%s\t%s\t%s\t%s\t%s\n' "$FP" "$DEST" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$FILES" "$BYTES" >> "$STAMP"
echo "  static: SYNCED to $DEST — $FILES files, $(( BYTES / 1048576 )) MB, fingerprint $FP (verified by stat)"
exit 0
