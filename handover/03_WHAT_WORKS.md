# 03 — What works

Based on `docs/STATUS.md` (derived at commit `472dfa8`, 5 commits behind HEAD
`45fe5b0` — the most recent self-generated, code-derived status the project
has produced), `docs/reports/VERDICT.md` (2026-09-10), and the last 3 commit
messages. `STATUS.md` uses three levels: **VERIFIED** (a test asserts it
against real data), **WIRED** (something downstream consumes it), **BUILT**
(exists, nothing reads it). Counts at that snapshot: VERIFIED 32, WIRED 11,
BUILT 9, SPECIFIED (not started) 19, IMPOSSIBLE 2, BLOCKED 0.

**Caveat carried over from the 2026-09-02 external audit**: `status.py`
historically had self-referential predicates that inflated several grades
(most notoriously, Romano-Wolf read VERIFIED when the string existed only in
`status.py` itself). The `STATUS.md` snapshot used here is 10 days newer than
that audit and its Phase 6 notes now cite specific decision records (0056) and
real row counts for the steps the audit flagged — this reads as fixed, but was
not independently re-verified for this handover.

## Fully working end-to-end (VERIFIED, with real-data tests)

1. **Seed carry → hash verification → provenance registration.** The 2.5 GB
   predecessor warehouse is copied in with a sha256 check on every file,
   registered into the content-addressed DAG. Idempotent, tested against real
   data.
2. **Price spine rebuild → 20/20 reconciliation gate** (for the MICCV2-scoped
   portion). `price_spine_adj` reaches 2026-09-10 per the latest STATUS.md.
3. **Trading calendar** — OBSERVED, never generated. 5,358 real sessions incl.
   3 Saturdays a generated calendar would have dropped.
4. **Deal collection** (bulk, block, FII/DII cash) — archive → hash → dedupe →
   parse → land, all VERIFIED with real-data tests.
5. **Identity resolution** — `security_master` + `symbol_history` built and
   tested; unresolved-symbol rate is 4.14%, under the <5% gate (step 3.4).
6. **Clean mart, zero silent drops** — `institutional_deals_clean`:
   `raw == clean` row count enforced by a test; every row carries a resolved
   status or an explicit `ineligibility_reason`.
7. **Backup + restore drill** — bundle + tarball, watched restore (clone, HEAD
   match, ancestry check), automatic prune. Runs after every collection cycle.
8. **Power analysis before any fit** — `src/research/power.py`: MDE computed
   before an effect is estimated, monthly-cohort collapse as the *primary*
   estimator (not a robustness afterthought), Bartlett-kernel serial-inflation
   correction with a label-overlap-aware lag, Gumbel-limit best-of-N noise
   bars with a degrees-of-freedom correction. **This is the strongest code in
   the repository** — it killed 3 of 4 pre-registered studies, including the
   project's own original headline finding, and that against-self-interest
   result is what makes the rest of the project's negative findings credible.
9. **Governance write-guards** — SQLite triggers genuinely refuse UPDATE/DELETE
   on `artefact`, `experiment_registry`, `study_result`, `trial_counter`,
   `family_charge`; the 2026-09-12 commit closed a real `INSERT OR REPLACE`
   bypass of the frozen-specification guarantee (migration 0003 sqlite +
   `src/governance/ledger.py`), verified with 12 new tests including the
   bypass watched failing against the unpatched schema first.
10. **Null calibration** (`nullcal.py`, step 6.9) — permuting participant
    labels within date and re-running the identical procedure gives a 1.8%
    false-positive rate at nominal 5%, which is the evidence the project's
    "no" findings aren't manufactured from noise.
11. **Romano-Wolf stepdown** (step 6.8, per the current STATUS.md) — built for
    step 6.9 and genuinely exercised against the real (tiny) participant
    leaderboard per decision 0056.
12. **F&O participant-OI / bhavcopy collection** (decision 0058, 2026-09-11) —
    both routes probed and confirmed (HTTP 200), 73 files collected and
    re-hashed with 0 mismatches against the manifest, schema verified against
    3 sampled sessions. Collection-only, deliberately not wired to any study.

## Partially working / wired but degraded

- **1.10 Off-machine backup** — WIRED, but the latest STATUS.md note flags
  "73 archived session(s) not in it" as of that snapshot — the backup is
  running but lagging.
- **2.1 Archive → parse → land** — VERIFIED, but "parsed parquet is still not
  written; rows go straight to the database" (a documented deviation from
  `sources.yml`'s `also_store_parsed_parquet: true` claim).
- **3.7 Behavioural PROP_HFT classifier** — WIRED (310 participants, 97,249
  deal rows, 41.2% of the corpus classified), but the STATUS.md note flags
  that `ineligibility_reason` under-reports the classifier's reach because
  it's a single-priority-ordered display field, not a membership test
  (decision 0056 amendment 3).
- **5.6 Six benchmarks incl. CHAR_MATCHED** — WIRED, "five of six built" —
  `NIFTY500_TR` is unbuildable (no source table exists for it despite being
  the config's declared broad-market headline).
- **6.3 `deal_forward_outcomes`** — VERIFIED, 52,365 outcomes computed against
  five of six benchmarks (not six).

## Not built (SPECIFIED only, per STATUS.md's `—` rows)

Sector history, participant alias merging, promoter-entity collection, manual
fund-house mapping, duplicate deal grouping (NSE/BSE cross-listing),
internal-transfer / promoter-related flags, three-scheme walk-forward
(anchored+rolling+CPCV), PBO from CPCV, the entire Track S scan machinery
(folds, nulls, procedure test), seasonality cell computation (100,000-cell
sample, near-duplicate grouping, permutation testing) — **though this last
category is now moot**: Engine 2 (seasonality) was independently killed on
pure power arithmetic on 2026-09-12, before any of that machinery was needed
to run against real data (see `docs/reports/SEASONALITY_POWER.md`).

## The research verdict itself (what the whole project was built to answer)

**Closed, 2026-09-10, `docs/reports/VERDICT.md`.** "No answer is available
from this data, and that is the finding." Specifically:
- 0 of 15 (population, horizon) pairs reach their pre-registered detection
  bound — the closest (12-month) is still 1.92× short.
- The one effect that looked real (sells, −22.7%/yr at 12 months) fails the
  liquidity confound (strongest in the least-tradeable third of the market)
  and the survivorship confound (31% of events sit on names that later
  stopped trading).
- No participant is rankable with statistical validity: only 7 participants
  in the whole 20-year dataset have ≥12 months of activity; the one
  "significant" result (p=0.0039) is a passive ETF measured over 2 months,
  and the procedure's own false-positive rate at that horizon is 11.3%.
- The instrument that produced these negatives is self-calibrated (1.8% false
  positive rate under label permutation against a nominal 5%), which is why
  the "no" is trusted rather than merely asserted.
