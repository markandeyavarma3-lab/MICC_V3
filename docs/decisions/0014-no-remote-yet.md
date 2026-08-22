# 0014 — No git remote; Risk 8 accepted with zero backup

**Date:** 2026-08-17
**Decided by:** Owner, against my recommendation
**Status:** SUPERSEDED by [0036](0036-private-remote-reversing-no-remote.md) — a private remote was created on 2026-08-23, after the exposure grew from 48 KB to 2.47 GB.

## Context
The repo has no remote. There is no pendrive, `restic` is not installed, and no
`/Volumes` mount exists. I recommended a private GitHub remote today purely as
off-machine backup, with the public flip deferred to the first finding.

## Decision
Stay local. No remote for now.

## Why
The owner's call. My objection is recorded rather than argued further.

## What would reverse this
The first result worth showing, or the arrival of the pendrive.

## Cost accepted
**There is currently no backup of any kind.** A single disk failure loses the
repo, the governance database, the decision records, and the archived sessions
from 2026-08-17 onward — which, because the historical endpoint returns 503,
**cannot be re-fetched at any price.** The 1.2 GB seed survives only because a copy
still sits in MICCV2.

This is Risk 8. It is open, it is growing daily, and it stays visible in the
README.
