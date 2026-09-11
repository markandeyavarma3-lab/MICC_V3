# 0058 — Firing the derivatives trigger, collection only

**Date:** 2026-09-11
**Decided by:** Owner, on an outside reviewer's recommendation, executed as
Workstream 2. The supersession rationale is the owner's; the collection-only
boundary is the reviewer's and I have held to it.
**Status:** accepted
**Supersedes:** the trigger condition on `fno_institutional_positioning` in
`configs/sources.yml`. The deferral entry is kept and marked `FIRED`, not deleted.

## 1. Why the trigger's own condition was retired

`sources.yml` parked `participant_oi` and the F&O feed behind:

> "FII/DII cash history reaches 24 months, making Engine E researchable"

That condition was written when the deals track was still expected to deliver
entity-level attribution. [0056](0056-the-participant-study-cannot-be-run-and-the-machine-does-not-invent-findings.md)
measured otherwise: under the §6.3 specification only **7 participants** reach
twelve months of activity, and five of ten at the short horizons appear in
exactly one month. The population that survives is ETFs, ODI issuers and bank
execution arms — vehicles, not decision-makers.

That changes what participant-wise OI *is*. It is **named FII/DII derivatives
positioning, daily, with a decade of history** — the best entity-attributable
flow series in the warehouse, rather than a supplement to a study that turned
out not to exist. Waiting for a 24-month cash history to make "Engine E"
researchable is waiting on a condition that no longer decides anything.

**Collection resumes. Analysis does not.** Nothing parses these bytes into the
warehouse and no study reads them, deliberately: Workstream 3 is the deals
verdict, and a second open front would split the governance attention that makes
either verdict worth anything.

## 2. Both routes answer, which was not guaranteed

Two of this project's sources are permanently dead — `/api/historical/bulk-deals`
answers 503 and Plan 3 steps 2.4/2.5 are graded IMPOSSIBLE because of it. So the
routes were probed before anything was built:

| feed | route | probe |
|---|---|---|
| `nse_participant_oi` | `nsccl/fao_participant_oi_{DDMMYYYY}.csv` | **HTTP 200**, 975 bytes |
| `nse_fo_bhavcopy` | `fo/BhavCopy_NSE_FO_0_0_0_{YYYYMMDD}_F_0000.csv.zip` | **HTTP 200**, 1.04 MB |

## 3. Validation report

**Manifest, by feed and status**

| feed | STORED | NO_SESSION | PENDING |
|---|---:|---:|---:|
| `nse_participant_oi` | **54** | 1 | 1 |
| `nse_fo_bhavcopy` | **19** | 0 | 1 |

`NO_SESSION` is a 404 on a past date — a holiday, recorded once so the collector
never re-probes it. `PENDING` is today, not yet published.

**Coverage**

| feed | first stored | last stored |
|---|---|---|
| `nse_participant_oi` | 2026-06-29 | 2026-09-10 |
| `nse_fo_bhavcopy` | 2026-08-17 | 2026-09-10 |

Each resumes exactly where its existing table stops — `participant_oi` at
2026-06-25, `fno_spine` at 2026-08-14 — so there is no gap and no overlap.

**Byte integrity.** All **73 stored files re-read from disk and re-hashed
against the manifest: 0 mismatches.**

**Schema against spec.** `sources.yml` declares
`categories: [FII, DII, Pro, Client, TOTAL]`. Three randomly sampled sessions
(2026-07-30, 2026-08-20, 2026-09-08) each carry 15 columns and exactly the
categories `[Client, DII, FII, Pro, TOTAL]`, header beginning
`Client Type, Future Index Long, Future Index Short, Future Stock Long, …`.

The F&O bhavcopy is **UDiFF, 34 columns**, 35,299 data rows on 2026-08-17,
beginning `TradDt, BizDt, Sgmt, Src, FinInstrmTp, FinInstrmId, ISIN, TckrSymb, …`.

**A schema difference that Workstream 3 must handle, flagged not fixed.** The
legacy `fno_spine` carries 16 columns named `date, instrument, symbol, expiry,
strike, option_typ, open, high, low, close, settle_pr, contracts, val_inlakh,
open_int, chg_in_oi`. UDiFF names none of these the same way. Resuming the spine
needs an explicit column mapping, and inventing one here would be the parsing
this workstream was told not to do.

## 4. The alert is part of the build, not a follow-up

Both feeds are `REQUIRED` in `src/monitor/health.py`, so staleness pages rather
than waiting to be noticed. A parked feed going stale is honest; a **collecting**
feed going stale silently is the char_panel failure
([0055](0055-the-shared-engine-counted-rows-and-the-prune-could-not-see.md)),
which cost 27 days of quietly degrading CHAR_MATCHED quality.

`inventory.PARKED` is now empty. The consequence is deliberate: `fno_spine`
renders **28d STALE**, because the archive is current to 2026-09-10 while the
table stops at 2026-08-14. **That nag is correct and should persist until a
parse step exists.**

All ten tests in `tests/test_derivatives.py` were written before the module and
watched failing on ImportError.

## 5. Known issue, logged for Workstream 3 and not built

**19 round-trip pairs escape detection** because one entity appears under two
spellings on the same symbol and day, so the client-stock-day aggregation never
groups them — 0.024% under-detection, measured in
[0057](0057-the-classifier-was-fine-and-i-broke-the-report-of-it.md).

This is the first measured cost of Plan 1 step 3.6 (`participant_aliases`) being
unbuilt. **Workstream 3 must normalise entity names before counting, and the
119-entity candidate figure may move when it does.** No build now.

## What would reverse this

Either route going dark, which the health alert would surface within two
sessions. The collection-only boundary lifts when the deals verdict lands — not
before.

## Cost accepted

No trials. Storing bytes estimates nothing.
