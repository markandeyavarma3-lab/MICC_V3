# 0065 — Land the collected F&O bhavcopy and participant OI after the spine cutovers

**Date:** 2026-09-16
**Decided by:** Owner. The deals verdict has landed (exp_002), 0062 proved
the parsers on real bytes, and 0064 made the spine register itself on the
nightly path; the land was the remaining step and the owner asked for it.
**Status:** accepted
**Supersedes:** the prod-side half of 0058's collection-only boundary
("nothing parses these bytes into the warehouse"). 0058's other half — no
study reads them — stands.
**Related:** 0058, 0062, 0064, 0004 migration (participant_oi), 0027
(`_collected_part` — collected sources run forward from the increment).

## Context

Two feeds had been archiving since 0058 and landing nowhere: `fno_spine`
ended at 2026-08-14 (the last MICCV2 increment) with 21 archived UDiFF
sessions behind it, and `participant_oi` ended at 2026-06-25 (the seed) with
56 archived sessions behind it. `HEALTH.md` said `fno_spine 28d STALE` on
every run, correctly. 0062's parsers existed but `write_legacy` refused
`data/` by design.

Dry run, 2026-09-16 09:38 IST, `python -m src.ingest.fno --dry-run`:
**21 F&O sessions, 700,261 rows** (2026-08-17 → 2026-09-15, 29,088–36,112
rows each), every file's `TradDt` matching its archive date; **56
participant-OI sessions, 280 rows** (2026-06-29 → 2026-09-15, five
categories each). Zero parse errors.

## Decision

`src/ingest/fno.py` lands both, in the same shape as `bhavcopy.py` lands
prices:

- **F&O:** each archived session strictly after `FNO_CUTOVER = 2026-08-14`
  is parsed by `fo_bhavcopy` and written as
  `data/raw/collected/fno/date=YYYY-MM-DD.parquet` in the 15-column legacy
  shape (legacy instrument codes, futures at `0.0`/`'XX'`, rupees → lakh).
  The directory is registered as one SOURCE artefact, `collected:fno`.
  `spine.FNO` gains `collected_glob="fno/**/*.parquet"` and
  `COLLECTED/fno` as a parent, so `spine.build(FNO)` unions it exactly as
  it unions `collected/prices` into the price spine — with
  `_collected_part`'s refusal if any date overlaps the seed or increment,
  the unique-key check, and (0064) self-registration.
- **Participant OI:** each archived session strictly after `POI_CUTOVER =
  2026-06-25` is parsed and inserted into `participant_oi` with
  `source = 'nse_participant_oi'`, the 14 migration columns only; `TOTAL`
  kept verbatim. `participant_oi.load`'s `DELETE WHERE source = 'v1_export'`
  leaves these rows alone. The archive directory is registered as
  `collected:participant_oi`.
- **The 2026-06-17 → 07-07 stretch is not touched.** It is already in the
  spine from a V1 increment, with raw UDiFF codes and NULL futures fields.
  Landing those ten sessions again from the archive would put two versions
  of each date into the union, and `_collected_part` would (rightly) refuse
  the build. Repairing that stretch means rewriting an increment, and is
  its own decision.

## Why

**Through the spine's machinery, not around it.** The alternative — rewrite
the `_y=2026` partition in place with the new rows — is faster than a
174M-row rebuild and skips the unique-key check, the overlap refusal, and
the registration 0064 just put on the build path. Every one of those exists
because a shortcut once produced a spine nobody could explain.

**Cutovers as constants.** Discovering the cutover from `MAX(date)` of the
current spine would move the boundary every night and make the
increment/collected split depend on what happened to be built. A constant
says which sessions each source owns, and a test can pin it.

**Why now and not with the raw-stretch repair.** The stretch is a defect in
data the project already had; the 21 + 56 sessions are data it did not.
Landing them makes `fno_spine` current and the stale nag true again only
when something actually breaks. The repair is scoped separately so that
this land is one thing.

## What would reverse this

- `_collected_part` refusing the build because a collected date overlaps
  the increment. That means the cutover constant is wrong, not that the
  refusal is.
- A study reading either table. 0058's "no study reads them" still holds;
  the first study that does needs its own record, and Engine E is still
  not researchable per 0056.
- The UDiFF header changing. `parse_udiff_bytes` raises on it and the land
  stage goes red, which is the right way to find out.

## Cost accepted

One full `fno_spine` rebuild (174M rows, minutes) today, and one for each
future land until the spine gains an incremental path — the same cost
`collect_daily.sh` already declines to pay nightly for F&O, which is why
this stage is **not** wired into the collector here. Wiring it (with a
weekly or on-demand cadence) is the next decision.

`participant_oi` now mixes two `source` values. Any consumer that wants the
seed's series alone must filter on `source`, which is what the column is
for.

No trials. Nothing here estimates anything; no module reads either table.
