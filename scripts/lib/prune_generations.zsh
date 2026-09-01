#!/bin/zsh
# prune_generations.zsh — retention for backup.sh, extracted so it can be TESTED.
#
# WHY THIS IS ITS OWN FILE. It lived inside backup.sh for five hours on
# 2026-09-01 and in that time it (a) errored on every scheduled run, (b) pruned
# nothing, and (c) came within one directory listing of deleting every backup
# generation on the machine. None of that was visible to a test, because there
# was nothing a test could call.
#
# usage: prune_generations.zsh <dest> <stamp-just-written> [keep-days]
#
# THE THREE DEFECTS THIS ENCODES, ALL MEASURED.
#
# 1. `ls -1 "$DEST"/repo-*.bundle 2>/dev/null` DOES NOT FAIL QUIETLY IN ZSH.
#    The redirect belongs to `ls`, but it is zsh that expands the glob, and zsh
#    raises `no matches found` before `ls` ever runs. Every empty destination
#    printed an error to the collector log. Globs here carry (N).
#
# 2. AN EMPTY LISTING MUST NEVER AUTHORISE A DELETE. With no matches the
#    keep-list came out empty, and an empty keep-list marks every generation as
#    unkept. The loop that followed would have removed all of them. A retention
#    policy that deletes everything when it cannot see anything is worse than no
#    retention policy.
#
# 3. THE DESTINATION IS AN ICLOUD FileProvider VOLUME, AND IT LIES BRIEFLY.
#    A file moved in is not necessarily in the next directory listing. That is
#    how condition 2 arose in production: the listing was empty microseconds
#    after `mv` put 37 MB into it. So the guard is concrete rather than
#    defensive — **if the generation we just wrote is not in the listing, the
#    listing is not trustworthy, and nothing may be deleted on its authority.**

set -eu

DEST="${1:?dest required}"
STAMP="${2:?stamp just written required}"
KEEP="${3:-3}"

bundles=("$DEST"/repo-*.bundle(N))
if (( ${#bundles} == 0 )); then
  echo "  prune: skipped — destination lists no generations"
  exit 0
fi

# The trust check. Not a sanity assertion: this exact condition occurred.
if [[ ! -e "$DEST/repo-$STAMP.bundle" ]]; then
  echo "  prune: SKIPPED — the generation just written ($STAMP) is not in the"
  echo "  listing, so the listing cannot be trusted to say what is safe to delete."
  exit 0
fi

# Newest generation of each of the most recent $KEEP days. Per DAY, not per run:
# collect_daily.sh fires three times a session, so a flat "keep 3" would leave
# all three copies inside fourteen hours of each other and a corruption noticed
# the next morning would already be in every one.
typeset -a days
for b in $bundles; do
  s="${b:t:r}"; s="${s#repo-}"
  days+=("${s%%-*}")
done
keep_days=(${(u)days})           # unique
keep_days=(${(on)keep_days})     # ascending
# The last KEEP days, or all of them if there are fewer. NOT `[-KEEP,-1]`:
# zsh does not clamp an out-of-range negative range, it returns EMPTY. With
# one day held and KEEP=3 that yielded an empty keep-list, which is the
# delete-everything condition this file exists to prevent. The guard below
# caught it; the arithmetic should not have needed catching.
integer n=${#keep_days}
integer start=$(( n > KEEP ? n - KEEP + 1 : 1 ))
keep_days=(${keep_days[start,-1]})

if (( ${#keep_days} == 0 )); then
  echo "  prune: skipped — no day survived the keep window"
  exit 0
fi

for b in $bundles; do
  st="${b:t:r}"; st="${st#repo-}"; day="${st%%-*}"
  if (( ${keep_days[(Ie)$day]} )); then
    of_day=("$DEST"/repo-$day-*.bundle(N))
    [[ "$b" == "${of_day[-1]}" ]] && continue   # newest run of a kept day
  fi
  # Never remove the generation just written, whatever the arithmetic says.
  [[ "$st" == "$STAMP" ]] && continue
  rm -f "$DEST/repo-$st.bundle" "$DEST/state-$st.tar.gz" "$DEST/MANIFEST-$st.txt"
  echo "  pruned generation $st"
done
