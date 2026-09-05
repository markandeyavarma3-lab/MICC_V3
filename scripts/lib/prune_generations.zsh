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

# 4. THE LISTING IS TAKEN MICROSECONDS AFTER `mv`, AND IT IS EMPTY EVERY TIME.
#    Defect 3 predicted this and treated it as occasional. It is not: from
#    2026-09-01 to 2026-09-05 the caller logged "destination lists no
#    generations" on EVERY scheduled run while eleven bundles sat in the
#    directory, and the very next line of backup.sh ran `du` on that same
#    directory successfully. So the guard worked exactly as designed and
#    retention never ran once — 11 generations, 772 MB, growing ~75 MB a day.
#
#    Nothing was ever at risk, which is why it went unnoticed for four days: a
#    retention policy that silently does nothing looks identical to one that has
#    nothing to do. The fix is to WAIT for the listing rather than trust the
#    first one, with the freshly-written generation as the readiness signal —
#    the same anchor defect 3 already established as the trust condition.

typeset -a bundles
integer attempt=0
while (( attempt < 10 )); do
  bundles=("$DEST"/repo-*.bundle(N))
  # Ready when the listing contains the generation we just wrote. Anything less
  # is a listing that has not caught up, not a destination that is empty.
  # `(Ie)` yields the index or 0 and never trips `set -u`; the `(r)` reverse
  # form raises "parameter not set" on a miss, which crashed this guard on the
  # exact path it exists to protect. Same idiom as the keep-day test below.
  (( ${bundles[(Ie)$DEST/repo-$STAMP.bundle]} )) && break
  # PRE-increment, deliberately. `(( attempt++ ))` yields the value BEFORE the
  # increment, so on the first pass it evaluates to 0, which zsh treats as a
  # failed command, and `set -e` kills the script — silently, exit 1, no
  # message, nothing pruned. Both the skip and the refuse branches below became
  # unreachable. Found by running the two of them.
  (( ++attempt ))
  sleep 0.5
done

if (( ${#bundles} == 0 )); then
  echo "  prune: skipped — destination lists no generations after ${attempt} attempt(s)"
  exit 0
fi

# The trust check, unchanged in meaning: if after waiting the listing still does
# not contain what we just wrote, it is not a listing we may delete on.
if (( ! ${bundles[(Ie)$DEST/repo-$STAMP.bundle]} )); then
  echo "  prune: SKIPPED — the generation just written ($STAMP) is not in the"
  echo "  listing after ${attempt} attempt(s), so the listing cannot be trusted"
  echo "  to say what is safe to delete."
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
