# 0036 — A private remote, reversing "stay local"

**Date:** 2026-08-23
**Decided by:** Owner
**Status:** ACTIVE — supersedes [0014](0014-no-remote-yet.md)

## Context

[0014](0014-no-remote-yet.md) chose to stay local with no remote of any kind, on
2026-08-17, against my recommendation. It named its own reversal condition:

> *"The first result worth showing, or the arrival of the pendrive."*

Neither has cleanly arrived. There **is** a first result —
[0034](0034-twelve-month-becomes-the-primary-horizon.md)'s twelve-month horizon
at MDE 5.56% against a 6.00% bound — but it is marginal, its confounds have never
been run, and calling it "worth showing" would be generous. The pendrive has not
appeared.

**What has changed is the exposure, by roughly fifty thousand times.** When 0014
was written the repository held 48 KB of archived sessions. It now holds:

| | |
|---|---|
| carried seed + increments | 2.47 GB, irreplaceable ([0027](0027-carry-the-warehouse-increments.md)) |
| archived sessions 17–21 Aug | unrecoverable — the historical endpoint answers 503 |
| governance store | `exp_001`, its frozen spec, two write-once results |
| decision records | 36 |
| source and tests | 325 tests |

0014's own cost paragraph anticipated this: *"it is open, it is growing daily."*
It grew.

## Decision

A **private** GitHub remote, and `git push`. Full history, unrewritten.

Repo-local `user.email` is set to the owner's GitHub address so future commits
attribute correctly. **Past commits keep their `.local` address and are not
rewritten** — see the cost below.

## Why

The history is evidence, not bookkeeping. The report cites commit hashes as
proof, and the load-bearing one is that `f25608d` ("Register exp_001 BEFORE
running its test") is a git-provable ancestor of `c31e128` ("Finding 001:
REJECTED by its own pre-registered rule"). That ancestry **is** the proof the
spec was frozen before the answer was known; without it the claim reduces to the
author's word, which is precisely what this project refuses to rely on. So the
history goes up intact or not at all.

**Private rather than public**, though [0001](0001-full-teardown-and-new-repo.md)
intends public eventually and the README says findings should appear before they
are safe. The only result in the repository is marginal and its confound
checklist has not been run; publishing it now invites it to be read as firmer
than it is. Public at the first confirmed finding, as a decision rather than a
default.

## What would reverse this

A confirmed finding, which flips visibility to public under 0001. Nothing would
return this project to having no remote.

## Cost accepted

- **This does NOT close Risk 8, and must not be read as closing it.** `.gitignore`
  excludes `/data/` and `/db/`, so the 2.47 GB seed, every archived session, and
  the governance store containing `exp_001` do **not** leave this disk. A push
  protects the code, the decisions and the plans — the harder half to replace —
  and leaves the half that cannot be re-fetched at any price exactly where it
  was. **Only the pendrive closes Risk 8.**
- Commit attribution is split: 40 existing commits carry
  `satya_03@Markandeyas-MacBook-Air.local` and will show as unattributed on
  GitHub. Unifying them would change every hash and destroy the ancestry proof
  above. Cosmetic inconsistency is the correct trade against evidential damage.
- A private repo is one account's credentials away from being no backup at all,
  and nobody else can restore it.
