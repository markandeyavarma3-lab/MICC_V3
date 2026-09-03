# Decision records

Promised in Plan 1 §4.2. Did not exist until 2026-08-17, by which point roughly
two dozen decisions had been made and the only record of them was commit messages
and chat prose. This directory is the fix.

## Why this exists

MICCV2's README described a cron schedule that had drifted from the actual
crontab, and nobody could say when or why it changed. The failure was not the
drift — it was that no artefact existed whose job was to say *why* the schedule
was what it was, so the README was left carrying a claim it could not defend.

A decision record is that artefact. It is not documentation of the code; the code
documents itself. It is documentation of the **choice**, which the code cannot
express because the code only contains the option that won.

## The field that matters

Every record carries **"What would reverse this"**. Without it a decision
calcifies: six months on nobody remembers whether a constraint was load-bearing
or arbitrary, so everyone treats it as load-bearing. Naming the reversal condition
up front means a decision can be revisited on evidence instead of on nerve.

## Format

`NNNN-kebab-case-title.md`, numbered in the order decided. One decision per file.
Never edited after the fact — a superseded decision gets a new record that names
the one it replaces, and the old file gains a one-line `**Superseded by:**`
pointer at the top. The history is the point.

```markdown
# NNNN — Title

**Date:** YYYY-MM-DD
**Decided by:** who actually chose
**Status:** ACTIVE | SUPERSEDED by NNNN

## Context
What made a decision necessary. Include measurements, not impressions.

## Decision
What was chosen, stated in one or two sentences.

## Why
The reasoning. Include the options rejected and why they lost.

## What would reverse this
The specific evidence or condition that would make this the wrong call.

## Cost accepted
What this decision gives up. Every real decision gives something up; a record
that lists only benefits is a advertisement, not a decision record.
```

## Attribution is not decoration

"Decided by" distinguishes an owner's judgement call from a default I picked
while building. Several decisions in this project were mine by omission and only
became visible as choices when challenged — the plausible effect bound of
0.5%/month sat in a config for a day looking like a measurement before anyone
asked where it came from. Recording who chose makes that visible immediately.

## Index

| # | Decision | Date | Status |
|---|---|---|---|
| [0001](0001-full-teardown-and-new-repo.md) | Abandon MICCV2, rebuild in a new repo | 2026-08-16 | ACTIVE |
| [0002](0002-preregistration-before-results.md) | Pre-registration with spec freezing | 2026-08-16 | ACTIVE |
| [0003](0003-portfolio-gate-required.md) | Every study needs a portfolio gate, not just an event gate | 2026-08-16 | ACTIVE |
| [0004](0004-horizons-in-sessions-not-months.md) | Primary horizons in sessions; monthly grid demoted | 2026-08-16 | **SUPERSEDED by 0034** |
| [0005](0005-room-2b-six-slices-not-crossed-grid.md) | Six pre-declared slices instead of 54,000 cells | 2026-08-16 | ACTIVE |
| [0006](0006-seasonality-full-rebuild.md) | Full 31.9M-cell rescan rather than validating the atlas | 2026-08-16 | **SUPERSEDED by 0026** |
| [0007](0007-stopgap-collector-first.md) | Ship a stopgap archiver before anything else | 2026-08-17 | ACTIVE |
| [0008](0008-three-way-split.md) | Three-way EXPLORE/SELECT/CONFIRM partition | 2026-08-17 | ACTIVE |
| [0009](0009-split-key-is-isin.md) | Partition on ISIN, never on symbol | 2026-08-17 | ACTIVE |
| [0010](0010-project-kill-criterion.md) | The thesis can be abandoned: 3-of-4 or 2027-02-28 | 2026-08-17 | ACTIVE |
| [0011](0011-plausible-effect-bound.md) | Plausible effect bound stays 0.5%/month | 2026-08-17 | ACTIVE |
| [0012](0012-seasonality-dual-split.md) | Seasonality cells must survive a time AND an index split | 2026-08-17 | ACTIVE |
| [0013](0013-rerun-exp001-reproducibly.md) | Re-run exp_001 under the DAG rather than annotate it | 2026-08-17 | ACTIVE |
| [0014](0014-no-remote-yet.md) | No git remote; Risk 8 accepted with zero backup | 2026-08-17 | **SUPERSEDED by 0036** |
| [0015](0015-rights-entitlements-excluded.md) | `-RE` and `DVR` instruments leave the universe | 2026-08-17 | ACTIVE |
| [0016](0016-era-balance-breach-accepted.md) | Split era-balance breach disclosed, not re-drawn | 2026-08-17 | ACTIVE |
| [0017](0017-serial-not-cross-sectional-correction.md) | The MDE correction is serial, not cross-sectional | 2026-08-17 | ACTIVE |
| [0018](0018-plausible-bound-not-horizon-scaled.md) | The plausible bound is not horizon-scaled | 2026-08-17 | **SUPERSEDED by 0028** |
| [0019](0019-two-track-programme.md) | The project is two parallel tracks, not one with a side-quest | 2026-08-18 | ACTIVE |
| [0020](0020-market-relative-is-mandatory.md) | Pooled scans must use market-relative returns | 2026-08-18 | ACTIVE* |
| [0021](0021-pooled-average-is-undefined.md) | **The pooled market-relative average is undefined** — 0020's reasoning corrected | 2026-08-18 | ACTIVE |
| [0022](0022-multiplicity-had-three-errors.md) | **The multiplicity bar was wrong three ways, all anti-conservative** | 2026-08-18 | ACTIVE |
| [0023](0023-trial-families-and-track-s-wiring.md) | Trial families; the three gaps between the two tracks | 2026-08-18 | ACTIVE |
| [0024](0024-design-gate-bypassed-its-own-machinery.md) | **The design gate bypassed the machinery built to set its bars** | 2026-08-18 | ACTIVE |
| [0025](0025-critical-path-schedule.md) | Schedule becomes a critical path with a pre-declared cut order | 2026-08-18 | ACTIVE |
| [0026](0026-validate-the-atlas-not-rebuild-it.md) | Validate the seasonality atlas instead of rebuilding it | 2026-08-18 | ACTIVE |
| [0027](0027-carry-the-warehouse-increments.md) | **The seed is `v1_export` plus the warehouse increments** — the Phase 1 gate was unpassable | 2026-08-21 | ACTIVE |
| [0028](0028-plausible-bound-scales-with-horizon.md) | **The plausible bound scales with horizon (rate view)** — every horizon becomes UNDERPOWERED | 2026-08-21 | ACTIVE |
| [0029](0029-fno-gate-figure-was-a-double-count.md) | **The F&O gate figure was a double-count** — 174,616,363 → 174,272,768 | 2026-08-21 | ACTIVE |
| [0030](0030-derived-tables-addressed-by-data-not-bytes.md) | **Derived tables are addressed by data, not bytes** — parquet writes are not byte-deterministic | 2026-08-22 | ACTIVE |
| [0031](0031-consensus-is-the-critical-path-study.md) | **Consensus is the single critical-path study**; selling leads the extensions | 2026-08-23 | ACTIVE |
| [0032](0032-uncovered-symbols-leave-the-universe.md) | **Symbols with no price coverage leave the universe** — Plan 1 Finding D falsified | 2026-08-23 | ACTIVE |
| [0033](0033-serial-lag-must-cover-the-label-overlap.md) | **The serial lag must cover the label overlap** — the NW rule under-corrected fivefold | 2026-08-23 | ACTIVE |
| [0034](0034-twelve-month-becomes-the-primary-horizon.md) | 12 months becomes the primary horizon, reversing 0004 | 2026-08-23 | **SUPERSEDED by 0038** |
| [0035](0035-power-may-use-the-full-universe-effects-may-not.md) | Power analysis may use the full universe; effect estimates may not | 2026-08-23 | ACTIVE |
| [0036](0036-private-remote-reversing-no-remote.md) | A private remote, reversing 0014 | 2026-08-23 | **SUPERSEDED by 0037 — never executed** |
| [0037](0037-backup-by-bundle-not-by-remote.md) | **Backup by bundle to cloud, not by remote** — the irreplaceable material is 23 MB, not 2.5 GB | 2026-08-23 | ACTIVE |
| [0038](0038-no-horizon-survives-a-participation-cap.md) | **No horizon survives any defensible participation cap** — the POWERED verdict needed no ceiling at all | 2026-08-30 | ACTIVE |
| [0039](0039-the-backup-check-is-the-backup.md) | **A backup nobody checks is a backup nobody has** — 0037 shipped a script that wrote nothing for eight days | 2026-09-01 | ACTIVE |
| [0040](0040-etf-units-leave-the-universe.md) | **ETF and fund units leave the universe** — seven unadjustable splits, zero eligible events | 2026-09-01 | ACTIVE |
| [0041](0041-the-adjusted-spine-was-carrying-unadjusted-splits.md) | **The adjusted spine was carrying unadjusted splits** — its guard read a table that ended four days past the boundary | 2026-09-01 | ACTIVE |
| [0042](0042-salvage-before-deleting-the-predecessors.md) | **What was salvaged before deleting MICC and MICCV2** — the atlas was carried by nothing; market.db was a verified duplicate | 2026-09-01 | ACTIVE |
| [0043](0043-consensus-is-not-registrable-either.md) | **Consensus is not registrable either** — best case 1.94x short; this is NOT the kill criterion | 2026-09-01 | ACTIVE |
| [0044](0044-selling-is-underpowered-but-the-bound-is-now-the-question.md) | **Selling is underpowered too — but the observed effect is 4x the bound, so the bound is now the question** | 2026-09-01 | ACTIVE |
| [0045](0045-the-spine-is-eq-only-and-nothing-said-so.md) | **The spine is EQ-only and nothing said so** — found by validating against the exchange's own files; the collector disagreed with the seed | 2026-09-01 | ACTIVE |
| [0046](0046-the-data-we-already-have-is-better-powered.md) | **The best-powered event class was already on disk** — 109 of 119 seed tables unread; promoter sells is 1.25x short, and the source is live | 2026-09-01 | ACTIVE |
| [0047](0047-the-collector-never-rebuilt-the-spine.md) | **The collector never rebuilt the spine** — and the committed figures moved every time it ran | 2026-09-01 | ACTIVE |
| [0048](0048-an-external-audit-found-what-the-machinery-did-not.md) | **An external audit found three defects the machinery was built to catch** — broken pipeline, self-grading status page, effect estimate outside the guard | 2026-09-02 | ACTIVE |
| [0049](0049-concurrent-builds-corrupted-a-partition.md) | **Two spine builds raced and emptied three tables** — the corruption was invisible to COUNT(*) | 2026-09-02 | ACTIVE |
| [0050](0050-pledge-data-does-not-rescue-the-power-problem.md) | **Pledge disclosures do not rescue the power problem** — worst-powered population measured; 0046 is now reproducible code | 2026-09-03 | ACTIVE |
