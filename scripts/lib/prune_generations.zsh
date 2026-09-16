#!/bin/zsh
# prune_generations.zsh — retention for backup.sh, extracted so it can be TESTED.
#
# usage: prune_generations.zsh <dest> <stamp-just-written> [keep-days] [index]
#
# =============================================================================
# WHY THIS DOES NOT LIST THE DESTINATION DIRECTORY
# =============================================================================
#
# It used to, and under launchd it always got back nothing. Measured 2026-09-10,
# same script, same path, same minute:
#
#     context           glob   ls entries   stat a known file
#     interactive        26        78            OK
#     launchd             0         1            OK
#
# `~/Library/Mobile Documents` is a TCC-protected location on macOS. A launchd
# job without Full Disk Access may **stat a path it already knows** but may not
# **enumerate the directory**. Denial is silent: readdir returns empty, not an
# error. That is why `mv` into the destination and `du` on explicit paths both
# succeed on the two lines either side of a prune that believes the directory
# is empty.
#
# Decision 0053 misread this as an iCloud FileProvider lag and added a retry
# loop. Retrying a permission denial ten times produces ten denials, and the
# backup went from 11 generations to 26 (2.5 GB) while the log said the fix was
# in. The retry is gone; the lesson it encodes is not.
#
# THE INDEX. backup.sh appends every generation it writes to a local index file
# under logs/, which is on ordinary disk and always readable. Pruning reads that
# index and deletes by EXPLICIT PATH, which TCC permits. No enumeration anywhere.
#
# The index is an optimisation, never the record of truth: the destination is
# self-describing by filename, so losing the index costs a prune, not a backup.
# When enumeration DOES work — an interactive run, or a machine with Full Disk
# Access granted — the index is reconciled against reality first, so a stale or
# missing index heals itself rather than silently pruning the wrong set.

set -eu

DEST="${1:?dest required}"
STAMP="${2:?stamp just written required}"
KEEP="${3:-3}"
INDEX="${4:-${0:A:h}/../../logs/backup_generations.txt}"

if [[ ! -f "$INDEX" ]]; then
  echo "  prune: skipped — no generation index at $INDEX"
  exit 0
fi

# The generation just written must be in the index, or the index is not
# describing this run and must not authorise deletes. Same trust condition as
# before; only the source of the listing has changed.
if ! grep -qx "$STAMP" "$INDEX"; then
  echo "  prune: SKIPPED — the generation just written ($STAMP) is not in the"
  echo "  index, so the index cannot be trusted to say what is safe to delete."
  exit 0
fi

# RECONCILE WHERE WE CAN. `(N)` yields an empty array rather than an error when
# the glob matches nothing, which under launchd is indistinguishable from an
# empty directory — so an empty result is treated as "cannot see", never as
# "nothing there".
typeset -a seen
seen=("$DEST"/repo-*.bundle(N))
if (( ${#seen} > 0 )); then
  typeset -a real
  for b in $seen; do
    s="${b:t:r}"; real+=("${s#repo-}")
  done
  print -l -- ${(on)${(u)real}} > "$INDEX"
fi

typeset -a stamps
stamps=(${(f)"$(<$INDEX)"})
if (( ${#stamps} == 0 )); then
  echo "  prune: skipped — the index lists no generations"
  exit 0
fi

# Newest generation of each of the most recent $KEEP days. Per DAY, not per run:
# collect_daily.sh fires three times a session, so a flat "keep 3" would leave
# all three copies inside fourteen hours of each other and a corruption noticed
# the next morning would already be in every one.
typeset -a days
for s in $stamps; do days+=("${s%%-*}"); done
keep_days=(${(on)${(u)days}})
# The last KEEP days, or all of them if there are fewer. NOT `[-KEEP,-1]`: zsh
# does not clamp an out-of-range negative range, it returns EMPTY, and an empty
# keep-list marks every generation as unkept.
integer n=${#keep_days}
integer start=$(( n > KEEP ? n - KEEP + 1 : 1 ))
keep_days=(${keep_days[start,-1]})
if (( ${#keep_days} == 0 )); then
  echo "  prune: skipped — no day survived the keep window"
  exit 0
fi

typeset -a kept
for s in $stamps; do
  day="${s%%-*}"
  if (( ${keep_days[(Ie)$day]} )); then
    # newest run of a kept day survives
    typeset -a of_day
    of_day=()
    for t in $stamps; do [[ "${t%%-*}" == "$day" ]] && of_day+=("$t"); done
    of_day=(${(on)of_day})
    if [[ "$s" == "${of_day[-1]}" ]]; then kept+=("$s"); continue; fi
  fi
  # Never remove the generation just written, whatever the arithmetic says.
  if [[ "$s" == "$STAMP" ]]; then kept+=("$s"); continue; fi
  # ONE DENIED rm MUST NOT ABORT RETENTION. On 2026-09-16 the fifth delete of
  # a run returned "Operation not permitted" — an iCloud file the launchd
  # context could stat but not unlink — and `set -e` ended the script there,
  # leaving four pruned, twenty-three untouched, and the index five entries
  # ahead of the disk. rm is allowed to fail per file; what decides the index
  # is whether the file is STILL THERE afterwards, which stat can answer under
  # TCC even when unlink cannot.
  rm -f "$DEST/repo-$s.bundle" "$DEST/state-$s.tar.gz" "$DEST/MANIFEST-$s.txt" 2>/dev/null || true
  if [[ -e "$DEST/repo-$s.bundle" ]]; then
    echo "  prune: could NOT remove $s (still present) — kept in index, retry next run"
    kept+=("$s")
  else
    echo "  pruned generation $s"
  fi
done

print -l -- ${(on)kept} > "$INDEX"
echo "  prune: ${#kept} generation(s) kept across ${#keep_days} day(s)"
