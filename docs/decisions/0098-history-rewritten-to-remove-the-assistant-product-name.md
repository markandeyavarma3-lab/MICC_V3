# 0098 — History rewritten to remove the assistant's product name

**Date:** 2026-11-08
**Decided by:** Owner. Asked for the AI tool's name to be removed from commits,
folders and documents, and chose to rewrite all history and force-push.
**Status:** ACTIVE
**Related:** 0002 (pre-registration), 0039 (the backup check), `scripts/backup.sh`,
`docs/history/commit-map-2026-11-08.csv`.

## What changed

All 317 commits were rewritten. Co-author and session trailers naming the tool
came out of every commit message. The 4 commits authored under the tool's name
now carry the owner's name. In every past and present version of 33 files, the
name was replaced with "AI assistant". That covers the decision records'
"Decided by" lines, the plan's author line, the `created_by` text in the
registration scripts, and two branch names in old notes. No other file content
changed: the old and new trees differ by those 29 lines alone. The two remote
branches named after the tool were deleted.

## Cost accepted

Every commit ID changed. IDs quoted in the current files (47 places in 23 files,
including the backup check's `--is-ancestor` pair) now carry the new IDs. Records
outside git still cite the old ones: `code_commit_hash` in the 8 frozen
registrations, and `code_commit` in provenance, study and procedure results.
Those rows are frozen and are not edited. `docs/history/commit-map-2026-11-08.csv`
maps every old ID to its new one, so each record can still be traced to its code.

The full old history is kept as a git bundle outside the repo:
`~/Workspace/history-backup-2026-11-08/`. GitHub may serve the old commits by ID
until it purges them.

From now on, commits carry no line naming the tool.

## What would reverse this

The old history is in the bundle. Restoring it means force-pushing that bundle's
`main` and reverting the ID updates, which would bring the tool's name back. Only
the owner can ask for that.
