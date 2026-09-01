# 0042 — What was salvaged from MICC and MICCV2 before deleting them

**Date:** 2026-09-01
**Decided by:** Owner asked for both predecessor repos to be cleaned off the
machine, keeping what is useful. The file-by-file audit is mine.
**Status:** ACTIVE — extends [0027](0027-carry-the-warehouse-increments.md)

## Context

`~/Workspace/MICC` (50 GB) and `~/Workspace/MICCV2` (5.6 GB) were the two
predecessors. [0027](0027-carry-the-warehouse-increments.md) carried three
directories out of MICCV2 when the question was *"what does the warehouse
need"*. This record answers a different question — *"what dies if these two
repos are deleted"* — and it has a different answer.

The audit ran the owner's protocol: read the file, find its use, check whether
it is still useful, check what is wired to it, reconfirm, only then delete.

**The protocol stopped the first two candidates.**

## What the audit found

**1. `market.db` (19 GB) is fully superseded — verified, not assumed.**
It holds 126 tables and `data/raw/v1_export` holds 126 parquet files. The only
difference is `sqlite_sequence` and `sqlite_stat1`, which are SQLite internals.
Row counts were compared across twelve tables including the largest:

| table | market.db | v1_export |
|---|---:|---:|
| stock_data_adj | 7,654,136 | 7,654,136 |
| stock_delivery | 7,685,343 | 7,685,343 |
| shp_institutional_summary | 3,565,899 | 3,565,899 |
| shp_promoter_group | 2,526,543 | 2,526,543 |
| pit_universe | 359,047 | 359,047 |

Zero mismatches. **I had already extracted 21 "reference" tables to parquet
before checking this, and deleted that extraction as redundant.** Checking
supersession before copying would have saved the step.

**2. The seasonality atlas is carried by nothing and Phase 7 needs it.**
`MICCV2/data/v3/prod/seasonality/seasonality_atlas` holds **31,893,556 rows** —
the "31.9M cells" the plans cite. [0026](0026-validate-the-atlas-not-rebuild-it.md)
set `rebuild_mode: validate_existing_atlas` and Phase 7.1 recomputes a 100,000
cell sample against it with *exact match required*. `v1_export` holds
`symbol_seasonality` at 63,937 rows, a different object entirely. Deleting
MICCV2 without carrying the atlas would have silently made Phase 7 impossible
as designed and forced the three-week rebuild 0026 rejected.

**3. Raw source files predate what NSE will now serve.** The price collector
measured NSE's bhavcopy archive reaching back only to 2024-01-01. MICC holds:

| archive | span | note |
|---|---|---|
| `bhavcopy/legacy` | 2005-04 → 2019-10 | 3,700 files, unfetchable |
| `bhavcopy/secfull` | 2020-01 → 2026-03 | 1,680 files, covers the dead zone |
| `bhavcopy/mto` | 2005 → 2019 | delivery data, absent from UDiFF |
| `NSE_FO` | 2005 → | 5,290 daily F&O zips |
| `ca/` | 2007 → 2026 | corporate actions, 24 yearly files |
| `shp/` | — | 592,554 files across 4,899 companies |

Their parsed forms are all in `v1_export`, so nothing downstream breaks without
them. They are kept because a parsing defect found later is repairable only from
originals, and these originals cannot be re-fetched.

## Decision

Salvage into `data/raw/salvaged/`, then delete both predecessor repos.

| what | from | size |
|---|---|---|
| `seasonality/` | MICCV2 | 2.0 GB |
| `v1_raw/shp.tar.gz` | MICC | 592,554 files compressed |
| `v1_raw/bhavcopy/`, `nse_fo/`, `ca/` | MICC | 3.2 GB |
| `predecessor_repos/*.bundle` | both | code and full history |
| `miccv2_state/` | MICCV2 | 329 MB |

`data/raw/salvaged/` is deliberately **not** merged into `v1_export`. The seed is
what 0027 chose; this is what a deletion audit found. Merging them would let a
later reader believe 0027 had considered material it never saw.

## What would reverse this

A parsing defect in `v1_export` traced to something only the raw files answer —
in which case the salvaged archives are the repair path, which is why they are
kept rather than deleted alongside the 19 GB that duplicates them.

## Cost accepted

- **`git bundle --all` failed on MICC** and the reason is worth recording: two
  refs literally named `main (1)` point at the null SHA, the signature of a
  duplicated file from a Windows copy. The bundle names the two valid refs
  explicitly instead, so **any other broken ref would be silently omitted**.
  `git fsck` reports them and nothing else structural.
- **120 uncommitted files in MICC and 28 in MICCV2** are captured as patches
  beside the bundles, not as commits. Restoring them is `git apply`, and nobody
  has tested that these apply cleanly.
- **The first `shp.tar.gz` was truncated at 10% and reported exit 0**, because
  `nohup ... &` inside a tool call was killed when the call returned. It was
  caught by comparing file counts — 61,867 against 592,554 — and had that check
  been skipped, 25 GB would have been deleted against a 126 MB archive holding
  a tenth of it. **Every salvaged item here is verified by count or row count,
  and that is the only reason this record can be trusted.**
- **`secrets/kite_access_token.json` is deliberately NOT salvaged.** It expired
  2026-08-14 and Zerodha tokens are daily, so it is inert — but a credential
  belongs in no repository, least of all one that is public.
- The salvaged tree adds ~8 GB to a repo whose backup deliberately excludes
  bulk data. It is bulk, it is now the only copy, and `backup.sh` does not
  carry it.
