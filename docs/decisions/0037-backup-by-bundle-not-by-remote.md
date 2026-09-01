# 0037 — Backup by bundle to cloud storage, not by git remote

**Date:** 2026-08-23
**Decided by:** Owner
**Status:** ACTIVE — extended by [0039](0039-the-backup-check-is-the-backup.md), which found this shipped and then wrote nothing for eight days — supersedes [0036](0036-private-remote-reversing-no-remote.md)

## Context

[0036](0036-private-remote-reversing-no-remote.md) was written earlier today and
records a decision that **was never executed**: it says a private GitHub remote
was created and the history pushed. The owner declined the new repository before
any of that happened, so 0036 stands in the record describing a repository that
does not exist. Superseding it rather than editing it, per the format rule — the
history is the point, including the history of a decision reversed within the
hour.

The reason for wanting a remote at all was never the remote. It was Risk 8, open
since 2026-08-17. A measurement changed the shape of that problem:

| item | size | recoverable? |
|---|---:|---|
| `.git` — 41 commits, all code, 36 decision records | 22 MB | **no** |
| `db/` — `exp_001`, frozen spec, write-once results | 1.5 MB | **no** |
| `data/raw/archive` — the 17–21 Aug sessions | 60 KB | **no**, endpoint answers 503 |
| `logs/` — the publication-time evidence | 4 KB | **no** |
| `data/raw/v1_export` + increments | 2.3 GB | yes, copy in MICCV2 |
| `data/{env}/warehouse` — spines, char panel | 2.3 GB | yes, one command |

**The irreplaceable material is 23 MB, not 2.5 GB.** Every previous discussion of
Risk 8 in this project, mine included, described it as a multi-gigabyte problem.
It is not, and that mis-framing is why it stayed open for six days: a 2.5 GB
problem needs a pendrive, and a 23 MB problem needs almost nothing.

## Decision

`scripts/backup.sh` writes three files to cloud storage: a `git bundle` of the
full history, a tarball of `db/`, `data/raw/archive` and `logs/`, and a manifest
naming the restore command. It keeps three generations. **No git remote.**

## Why

A git remote could not have solved this alone. `.gitignore` excludes `/data/` and
`/db/` — correctly, because a tracked live database is audit defect #9 — so a
push protects the code and leaves `exp_001`'s governance store and the five
unrecoverable sessions behind. The bundle takes both.

A `git bundle` rather than a copy of `.git`: it is a single file, `git clone`
reads it directly, `git bundle verify` checks it, and it cannot be half-copied.

**The restore drill runs inside the script**, because Plan 3 §6 says a backup
nobody has restored is a hypothesis. It clones what it just wrote, asserts HEAD
matches, and asserts that `f25608d` is still an ancestor of `c31e128` — the
ancestry proving `exp_001` was registered before it ran. A backup that preserves
the code and loses that proof has lost the thing that makes this project
credible.

## What would reverse this

A confirmed finding, at which point [0001](0001-full-teardown-and-new-repo.md)'s
intent to publish makes a public remote the point rather than the backup.

## Cost accepted

- **It is not yet running.** Measured 2026-08-23: the Google Drive app is not
  launched and its mount times out, and iCloud Drive is present but not
  writable. The script exists, is committed and passes its own drill, and
  **writes nothing until the owner starts one of them.** Risk 8 is therefore
  still open, and the difference from yesterday is that the remedy is now one
  action rather than a purchase.
- Nothing is automatic. There is no launchd trigger, so a backup happens when
  someone runs it — the same class of dependence on memory that this project
  criticises elsewhere.
- Cloud sync is not versioned storage. Three generations is what stands between
  a corrupted repo and a corrupted backup of it.
- The 4.6 GB excluded is recoverable *from MICCV2, on the same disk*. Against
  accidental deletion that is enough; against disk failure it is not, and the
  21-year seed would be gone.
