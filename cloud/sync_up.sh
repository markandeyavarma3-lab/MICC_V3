#!/bin/zsh
# sync_up.sh: copy the laptop's data, databases and website to the cloud server.
# Run ON the laptop. Safe to rerun: rsync sends only what changed, and resumes a
# file cut off half way.
#
#     cloud/sync_up.sh            # to the server named micc_server in ~/.ssh/config
#     cloud/sync_up.sh --check    # list what would be sent, send nothing
#
# It refuses while the collector runs or while anything has the database open: a
# DuckDB file copied mid-write is a broken copy that still looks like a database.
#
# Nothing is deleted on either side. Removing a file on the server stays a
# deliberate, separate step.

set -u

REPO="${MICC_REPO:-${0:A:h:h}}"
DEST="${MICC_DEST:-micc_server:micc}"   # MICC_DEST=/some/local/folder for a dry run on the laptop
WEB=""
for w in "${REPO:h}/research website" "${REPO:h}/research-website"; do
  [[ -d "$w" ]] && { WEB="$w"; break; }
done

CHECK=()
[[ "${1:-}" == "--check" ]] && CHECK=(--dry-run --itemize-changes)

if pgrep -f '[c]ollect_daily.sh' >/dev/null; then
  echo "  sync: the collector is running; try again when it has finished"; exit 1
fi
for db in "$REPO"/db/*.duckdb(N); do
  if [[ -e "$db.wal" ]]; then
    echo "  sync: ${db:t} has unsaved changes (${db:t}.wal); close whatever is writing to it first"; exit 1
  fi
  if lsof -t "$db" >/dev/null 2>&1; then
    echo "  sync: ${db:t} is open in another program; close it first"; exit 1
  fi
done

send() {  # send <from> <to> [rsync options...]
  local from="$1" to="$2"; shift 2
  echo "  sync: ${from} -> ${to}"
  rsync -a --partial "${CHECK[@]}" "$@" "$from" "$to" || { echo "  sync: FAILED on $from"; exit 1; }
}

[[ "$DEST" == *:* ]] || mkdir -p "$DEST/research" "$DEST/website"
send "$REPO/data/" "$DEST/research/data/" --exclude '*.partial' --exclude '.DS_Store'
send "$REPO/db/" "$DEST/research/db/" --exclude '*.wal' --exclude '.DS_Store'
if [[ -n "$WEB" ]]; then
  send "$WEB/" "$DEST/website/" --exclude node_modules --exclude dist --exclude .astro --exclude '.DS_Store'
else
  echo "  sync: no website folder found beside the repo; skipped"
fi
echo "  sync: done${CHECK:+ (check only, nothing sent)}"
