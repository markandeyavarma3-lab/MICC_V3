# 0064 — The spine checksum is registered on the path the collector actually calls

**Date:** 2026-09-16
**Decided by:** Owner, on two consecutive `charpanel=1` runs (2026-09-15
20:31, 2026-09-16 08:30) diagnosed in `handover_delta5/11_CHARPANEL.md`.
**Status:** accepted
**Related:** 0030 (artefacts addressed by data checksum, not bytes), 0055
(`land → identity → mart` and the spine rebuild joined `collect_daily.sh`),
step 1.9 ("every table written registers its artefact and edges").

## Context

`scripts/collect_daily.sh:111-117` rebuilds the price spines every run with
an inline `spine.build(spine.PRICE, …)` and `spine.build_adjusted(…)`. Both
functions built and returned; neither registered. Registration lived only in
`spine.build_all()` — the by-hand Phase 1 rebuild — as a loop body that
computed the data checksum, edged to the carried sources, and called
`prov.register`. The nightly path never went through it.

That was invisible while the spine did not change: `charmatch.build_panel`
computes the *current* spine checksum and edges `char_panel` to it, and on
09-10 the rebuild produced the same 7,792,286 rows → the same checksum →
the artefact registered by hand on 09-10 14:47 UTC. On 09-15 the spine grew
to 7,796,873 rows (sessions 09-11 and 09-15 landed), the checksum changed,
no row existed for it, and `artefact_edge`'s foreign key raised:

```
sqlite3.IntegrityError: FOREIGN KEY constraint failed
src.governance.provenance.ProvenanceError: warehouse:char_panel: … an edge
points at an input that was never registered
charpanel=1
```

The panel parquet had already been written; `outcomes` ran green against
it. What was missing was the lineage — exactly the "330,861 rows and
registered nothing for two days" condition `charmatch.py:199-202` was
written to prevent, reproduced one node up the graph.

Measured before the change (read-only): the three parents the spine edges
to — `seed:v1_export`, `seed:prices`, `collected:prices` — were all
registered (the last one nightly, by `bhavcopy.register`); only the spine
checksums `ab8e323b…` (price) and `22b486ca…` (adjusted) were absent.

## Decision

`spine.register_spine(spec, result, env, con)` is the one registration
routine. `build()` and `build_adjusted()` call it after building, **under
the same exclusive lock**, by default (`register=True`). `build_all()` no
longer carries its own copy of the block; it just builds. The parent-dir
mapping (`_parent_dirs`) keeps the per-spine edges 0030 insisted on —
`price_spine` never edges to `seed:fno`.

`collect_daily.sh` is untouched: the fix is that the functions it already
calls now do what `build_all` did.

Tests (`tests/test_spine_registration.py`, six, watched failing 5/6 against
the unpatched module) pin: the registered hash is the data checksum
charmatch computes; a child can parent to it; an unregistered parent still
fails loudly; re-registering unchanged data adds no row; both entry points
default to registering; the script calls exactly those entry points; and
`build_all` has no second copy of the logic.

## Why

**Register where the build happens, not where someone remembers to.** Two
copies of "build then register" — one in the function, one in a wrapper —
is how the wrapper became the only one that registered. One routine, called
by the thing that produced the artefact, cannot be skipped by calling the
producer directly.

**Under the lock.** The checksum is of the files just written; registering
after the lock is released would let a concurrent rebuild change the files
between build and register. No such concurrency exists today (0059 removed
cron), but the guarantee should not depend on that.

**Loud on a missing parent.** The alternative — drop unregistered parents
and register anyway — would have made *tonight* green and left `char_panel`
edged to a spine with no lineage of its own. The foreign key is the
guarantee; the fix is to satisfy it, not to route around it.

**Not a one-off registration of today's spine.** Tonight's run rebuilds the
spine (09-16 prices land) and registers whatever it produces, changed or
not. Registering `ab8e323b…` by hand now would be a second write path.

## What would reverse this

- `build()` growing a caller that must not write to the ledger (a dry-run
  or a test harness building into a temp warehouse against the prod ledger).
  `register=False` exists for that; the default stays `True`.
- The FK failing on a *parent* rather than the spine — `collected:prices`
  registered under a different hash than `hash_dataset` computes, say. That
  is a `bhavcopy.register` bug, surfaces as `spine=1`, and is the right
  place for it to surface.

## Cost accepted

`build()` now takes ~1 s longer (three `hash_dataset` calls and one
`data_checksum` over the spine) and writes one row to the governance store
per rebuild of changed data. `charpanel` should be `=0` from 2026-09-16
20:30; the two red runs stay in the log as they happened.

No trials. Nothing here touches an estimate.
