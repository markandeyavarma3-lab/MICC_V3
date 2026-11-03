#!/bin/zsh
# cloud_backup.zsh — the whole project, encrypted, to Google Drive. Decision 0096.
#
# usage: cloud_backup.zsh <stamp-file> <path> [path ...]
#   exit 0  snapshot written and found in the repository; stamp appended
#   exit 1  the backup, its confirmation or the maintenance due tonight failed
#   exit 2  usage, or restic / rclone / the password file missing
#
# =============================================================================
# WHY THIS EXISTS
# =============================================================================
#
# 0093 made the pen drive the only destination. On 2026-10-31 it was not
# plugged in, and every run from then reported FAILED and backed up nothing:
# one destination that is usually absent is no destination. The owner has 5 TB
# of Google One until 2030, so the project goes there every run, and the pen
# drive becomes the second copy when it happens to be plugged in.
#
# restic, not a plain copy: Drive sees only encrypted chunks (the repo is
# public, and the data is personal-use only), each run uploads only what
# changed, and every snapshot restores to the exact tree of that run. The key
# is ~/.micc_restic_pw, never in the repo. Without it the backup cannot be
# opened by anyone, the owner included; it is kept on paper too.
#
# =============================================================================
# WHAT FAILS, AND HOW IT IS SEEN
# =============================================================================
#
# No network, an expired Google sign-in, a full Drive: restic exits nonzero,
# this exits 1, the backup stage fails, and runreport pages it on Telegram.
# The stamp is written only after the new snapshot is read back from the
# repository, so backup_state.py never counts a run that did not land.
#
# A hung upload must not hold the collector's remaining stages (health, site,
# digest) hostage, so every restic call is capped. macOS has no `timeout`;
# perl's alarm survives exec and kills restic with SIGALRM. The repository lock
# it leaves is stale, and the `unlock` at the start of the next run clears it
# (unlock removes only stale locks, never a live one).

set -u

STAMP="${1:-}"
shift 2>/dev/null || { echo "usage: cloud_backup.zsh <stamp-file> <path> [path ...]"; exit 2; }
PATHS=("$@")
[[ -z "$STAMP" || ${#PATHS} -eq 0 ]] && { echo "usage: cloud_backup.zsh <stamp-file> <path> [path ...]"; exit 2; }
for p in $PATHS; do [[ -d "$p" ]] || { echo "  cloud: $p missing"; exit 2; }; done

# launchd's PATH does not reach ~/.local/bin, where restic and rclone live.
export PATH="$HOME/.local/bin:$PATH"
export RESTIC_REPOSITORY="${RESTIC_REPOSITORY:-rclone:gdrive:mv-research-backup}"
export RESTIC_PASSWORD_FILE="${RESTIC_PASSWORD_FILE:-$HOME/.micc_restic_pw}"
command -v restic >/dev/null && command -v rclone >/dev/null \
  || { echo "  cloud: restic or rclone not installed in ~/.local/bin"; exit 2; }
[[ -r "$RESTIC_PASSWORD_FILE" ]] || { echo "  cloud: no password file at $RESTIC_PASSWORD_FILE"; exit 2; }

EXCLUDES="${0:A:h}/cloud_excludes.txt"
MAINT="${STAMP:r}_maint.txt"
capped() { local secs=$1; shift; perl -e 'alarm shift; exec @ARGV or die "exec: $!"' "$secs" "$@"; }

restic unlock -q 2>/dev/null

OUT="$(mktemp)"
trap 'rm -f "$OUT"' EXIT
capped 5400 restic backup -q --json --exclude-file "$EXCLUDES" $PATHS > "$OUT" 2>&1
RC=$?
SUMMARY="$(grep '"message_type":"summary"' "$OUT" | tail -1)"
SNAP="$(print -r -- "$SUMMARY" | sed -n 's/.*"snapshot_id":"\([0-9a-f]*\)".*/\1/p')"
if [[ $RC -ne 0 || -z "$SNAP" ]]; then
  echo "  cloud: FAILED (restic exit $RC) — nothing new in Google Drive"
  grep -v '"message_type"' "$OUT" | tail -5 | sed 's/^/    restic: /'
  exit 1
fi
# Confirm the snapshot is in the repository before saying so anywhere.
capped 600 restic snapshots -q "$SNAP" >/dev/null 2>&1 \
  || { echo "  cloud: FAILED — snapshot $SNAP not found after the upload"; exit 1; }

FILES="$(print -r -- "$SUMMARY" | sed -n 's/.*"total_files_processed":\([0-9]*\).*/\1/p')"
BYTES="$(print -r -- "$SUMMARY" | sed -n 's/.*"total_bytes_processed":\([0-9]*\).*/\1/p')"
ADDED="$(print -r -- "$SUMMARY" | sed -n 's/.*"data_added":\([0-9]*\).*/\1/p')"
mkdir -p "${STAMP:h}"
printf '%s\t%s\t%s\t%s\t%s\n' "${SNAP:0:8}" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$FILES" "$BYTES" "$RESTIC_REPOSITORY" >> "$STAMP"
echo "  cloud: snapshot ${SNAP:0:8} in Google Drive — ${FILES} files, $(( ${BYTES:-0} / 1048576 )) MB, $(( ${ADDED:-0} / 1048576 )) MB new"

# --- maintenance, by age of its own stamp, not by weekday ---------------------
# A weekday rule skips a whole cycle whenever the Mac is off that day; an age
# rule runs at the first run after it falls due.
due() {  # due <kind> <days>
  local last
  last="$(grep "^$1	" "$MAINT" 2>/dev/null | tail -1 | cut -f2)"
  [[ -z "$last" ]] && return 0
  (( $(date -u +%s) - $(date -j -u -f '%Y-%m-%dT%H:%M:%SZ' "$last" +%s 2>/dev/null || echo 0) > $2 * 86400 ))
}
MRC=0
if due prune 7; then
  if capped 3600 restic forget -q --keep-daily 7 --keep-weekly 4 --keep-monthly 12 --prune >/dev/null 2>&1; then
    printf 'prune\t%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$MAINT"
    echo "  cloud: old snapshots pruned (keep 7 daily, 4 weekly, 12 monthly)"
  else
    echo "  cloud: prune FAILED — retried next run"; MRC=1
  fi
fi
# The monthly check downloads and verifies 5% of the data: a backup nobody has
# read back is a hypothesis (backup.sh's restore drill, same rule).
if due check 30; then
  if capped 3600 restic check -q --read-data-subset=5% >/dev/null 2>&1; then
    printf 'check\t%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$MAINT"
    echo "  cloud: integrity check of 5% of the data passed"
  else
    echo "  cloud: integrity check FAILED — the repository needs a look (restic check)"; MRC=1
  fi
fi
exit $MRC
