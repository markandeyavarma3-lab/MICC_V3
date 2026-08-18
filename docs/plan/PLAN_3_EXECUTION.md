# Institutional Research Platform — Plan 3 of 3: Execution

**Companion to Plan 1 (Foundations) and Plan 2 (Methodology)**
**Date:** 2026-08-16 · **Status:** Phase 0 deliverable — awaiting owner approval
**Budget:** 2–3 h/day (owner decision Q5) · **No deadline** (Q4)

<!--TOC-->

---

## 1. Answer to owner question Q2 — is the signal ledger required?

The owner asked me to check whether `institutional_signal_ledger` and
`experiment_registry` are needed given the research-only scope, and to answer
based on what produces a good-quality outcome.

**They are not the same kind of object, and the answer differs.**

### 1.1 `experiment_registry` — REQUIRED, build it first

It records a hypothesis, its pass bar and its kill criteria **before** the data
is looked at. Without it, every number the platform produces is exploratory, and
an exploratory number cannot be distinguished from a number that was tuned until
it looked good.

This matters more here than in most projects for a specific reason: **an
exploratory pass has already been run.** The audit measured the institutional
premise on 2026-08-16 and found *t* ≈ −0.8 at 1 and 3 months. Any subsequent
study is now, strictly speaking, a second look at data whose answer is partly
known. The only way to keep the result credible is to register the full
specification — horizons, cost policy, benchmark, correction method, pass bar —
before re-running, and to record in `exploratory_prior_run` that the earlier
look happened and what it showed.

Without the registry, the honest description of this project's output would be
"we looked at the data many ways and reported what we found." With it, the
description is "we declared what would count as evidence, then measured it."
That distinction *is* the quality of the outcome.

**Verdict: build it in Phase 1, before any research code.**

### 1.2 `institutional_signal_ledger` — NOT required now

Its purpose (original plan §14) is to record **engine decisions**: which engine
approved or rejected which signal, on what date, for what reason. With no
engines, it would be a permanently empty table.

What research actually needs in its place is a **result store** —
`study_result` (Plan 1 §7.4) — recording each stratum's N, effect, corrected
*p*, correction method, family size, bootstrap CI, input hashes and verdict.
That is a different shape entirely: one row per *finding*, not per *decision*.

**Verdict: create the table empty in migration 0001 so engines drop in later
without a schema change (owner decision Q1), but do not populate or maintain it
in v1. `study_result` is what carries the research.**

### 1.3 What this means practically

| Table | Phase | Populated in v1? |
|---|---|---|
| `experiment_registry` | 1 | ✅ Yes — every study |
| `study_result` | 6 | ✅ Yes — every finding |
| `artefact` / `artefact_edge` (provenance DAG) | 1 | ✅ Yes — everything |
| `engine_config` | 1 | ⬜ Created, all rows `DISABLED` |
| `institutional_signal_ledger` | 1 | ⬜ Created, stays empty (test asserts it) |

---

## 1.4 The four registered studies (owner decision, 2026-08-16)

All four are locked and run in Phase 6, in descending order of expected value.
Each is a separate experiment with its own spec hash; registering four means the
multiple-testing correction accounts for four families, raising each bar
slightly. That is the accepted price for four honest answers.

| # | Study | Question | N | Prior look? |
|---|---|---|---:|---|
| 1 | **Consensus** | Do 3+ unrelated institutions buying the same name within 21 sessions predict outperformance? | pooled | No |
| 2 | **Selling** | Do disclosed institutional sales predict underperformance? | 34,270 | No |
| 3 | **Block deals** | Do negotiated blocks (0.7% round-trip) behave differently from bulk? | 12,430 | No |
| 4 | **Bulk buys** | The original premise, run properly | 30,771 | **Yes — must disclose** |

**Why this order.** Consensus is statistically strongest: single-participant
skill is hopeless (SBI Mutual Fund has 80 buys in 20 years — skill and luck are
indistinguishable at that N), but a pooled convergence event needs no individual
institution to be smart. Selling is 34,270 completely unexamined events with a
plausible mechanism — institutions buy for many reasons (inflows, index
tracking, rebalancing) but sell for fewer. Blocks are the cleanest data but only
~620 events/year. Bulk buys already look dead at *t* ≈ −0.8; study 4 exists to
close it honestly rather than leave it informally dismissed.

**Study 4 carries a mandatory disclosure.** Its `exploratory_prior_run` field
records that a pass was run on 2026-08-16 and exactly what it found. A
registration that conceals a prior look is not a registration.

## 2. Phase plan

Nine phases. Each ends with a deliverable and a gate; a gate that fails stops the
next phase rather than being noted and passed.

### Phase 0 — Audit and specification · **COMPLETE**

These three documents. Deliverable: integration map, schema proposal, feasibility
findings, methodology, execution plan. **Gate: owner approval.**

### Phase 0.6 — Decisions that block registration · **OWNER, NOT BUILD**

Added 2026-08-18. These are not build steps and they gate everything downstream.
Until they are answered, `design.py` **refuses** to register the affected studies
rather than guessing — an open question stops the code instead of being resolved
by a default nobody chose.

| # | Decision | Blocks |
|---|---|---|
| **0018** | Does the plausible effect bound scale with horizon? | **every session-horizon study.** Under a fixed bound the current grid is partly powered; under a scaled one **every horizon becomes UNDERPOWERED**, including the two now marked detectable. This turns on whether disclosure causes a one-off repricing or a persistent rate of return. |

**Gate:** answered in writing, as a decision record, before Phase 6 registers
anything at a session horizon.

### Phase 1 — Skeleton, migrations, warehouse rebuild · ~3 weeks

| Step | Detail |
|---|---|
| 1.1 | Freeze MICCV2 — unload 3 launchd agents, move plists, tag `frozen-2026-08-16` (Plan 1 §3.3) |
| 1.2 | Repo scaffold, `pyproject.toml`, Python 3.14 via uv, pytest, GitHub Actions running tests only (Q53) |
| 1.3 | `src/common/`: resolved repo root, config loader, structured logging, explicit-env guard, SHA-256 helpers |
| 1.4 | **Trading calendar** ported from MICCV2 — observed sessions, never generated. Gate: 5,339 sessions reproduced exactly |
| 1.5 | Migration runner: forward-only SQL files, checksummed, `schema_migrations` table |
| 1.6 | `0001_init.sql` — every table in Plan 1 §5–§7 and Plan 2 §2, §7.3, §8.1 |
| 1.7 | Copy `v1_export` (1.2 GB) into `data/raw/v1_export/`, hash every file into `artefact` |
| 1.8 | Rebuild the price spine, adjusted spine, and PIT universe from `v1_export` with new code |
| 1.9 | Provenance DAG live from this point — every table written registers its artefact and edges |
| 1.10 | **Close Risk 8** — `restic` to the 256 GB pendrive + free-tier cloud, plus a restore drill that is actually watched succeeding (§6) |

**Gate:** the Plan 1 §3.4 reconciliation passes exactly — 7,749,148 price rows ·
4,200 symbols · 1,497 dead symbols · 174,616,363 F&O rows · 5,339 sessions.
Any mismatch is investigated before Phase 2.

### Phase 2 — Raw archive and collection · ~3 weeks

| Step | Detail |
|---|---|
| 2.1 | `src/archive/`: fetch → SHA-256 → dedupe on hash → store gzipped original → parse → parquet → record (Q11) |
| 2.2 | Browser-like session, 1 req/2 s, backoff, honest User-Agent (Q10) |
| 2.3 | NSE bulk + block parsers, historical archive endpoint (Q7) |
| 2.4 | **Backfill 2026-07-09 → present** (Q8) — the 5-week gap |
| 2.5 | Backfill the full NSE history through the archive endpoint, hashing every file |
| 2.6 | **BSE bulk + block** — new, never collected (Q9) |
| 2.7 | FII/DII cash collector — starts accruing forward (Q4 route: both) |
| 2.8 | `participant_oi` ported as the FII/DII **proxy**, labelled as F&O positioning, not cash flow |
| 2.9 | launchd agents installed and running from day one (Q13) |
| 2.10 | **Measure `available_from` empirically** — record observed publication time daily |
| 2.11 | Revision detection (Plan 1 §5.4) |

**Gate:** 7 consecutive days collecting cleanly, every file hashed, zero
overwrites, publication times recorded.

### Phase 3 — Identity layer · ~4 weeks · *the highest-value phase*

| Step | Detail |
|---|---|
| 3.1 | `security_master` wrapping the existing ISIN masters (Q15) |
| 3.2 | `symbol_history` — one `resolve(symbol, exchange, on_date)` function, all callers use it |
| 3.3 | Delisting detection from last-trade dates; classify MERGER / ACQUISITION / SUSPENSION |
| 3.4 | **Resolve the 7,354 unmatched deal symbols** — the single biggest quality win |
| 3.5 | `sector_history` PIT sectors from `index_membership` (13,163 rows with validity dates) (Q31) |
| 3.6 | Participant normalisation — aggressive cleaning, exact match only, no fuzzy auto-merge (Q19) |
| 3.7 | **Behavioural classifier first**: ≥95% same-day round-trip over ≥20 client-stock-days → `PROP_HFT` |
| 3.8 | Name-pattern classifier for the residual |
| 3.9 | Merge *suggestions* recorded, never applied; owner decides later (Q20) |
| 3.10 | Review queue CLI for the **1,515** names needing manual review |
| 3.11 | SHP collector → `promoter_entities`; PIT promoter flag (Q25) |
| 3.12 | Manual fund-house mapping file (Q21) |

**Gate:** unresolved symbol rate < 5% on the deal set — measured, not asserted.
This gate is what turns the exploratory study into a defensible one.

### Phase 4 — Clean mart · ~2 weeks

| Step | Detail |
|---|---|
| 4.1 | `institutional_deals_clean` with all flags (Plan 1 §7.1) |
| 4.2 | Duplicate grouping — NSE/BSE cross-listing, both kept (Q24) |
| 4.3 | Same-day and 5-day round-trip flags (Q23) |
| 4.4 | Internal-transfer and promoter-related flags |
| 4.5 | Size eligibility: `deal_value_to_adv20 ≥ 0.5%` and ≥ ₹1cr, configurable (Q26) |
| 4.6 | `eligible_for_research` excluding `PROP_HFT` by default, flag-driven (Q27) |
| 4.7 | Three interpretations — individual / accumulated / confirmation (plan §10) |

**Gate:** every clean deal either resolves to a security or carries an explicit
failure status. Zero silent drops.

### Phase 5 — Cost model and benchmarks · ~2 weeks

| Step | Detail |
|---|---|
| 5.1 | **`fee_schedule` versioned table, rebuilt not ported** — MICCV2's fee layer was wrong in 3 places (Plan 2 §4.1). Rates sourced from published rate cards and exchange circulars, every row carrying `verified` and a `source_url` |
| 5.2 | Corwin–Schultz and Abdi–Ranaldo spread estimators, rolling 21 sessions |
| 5.3 | Square-root market impact, `Y` configurable, sensitivity at 0.5 / 0.8 / 1.0 |
| 5.4 | Participation cap and delay cost |
| 5.5 | Volatility-regime multiplier from India VIX |
| 5.6 | Six benchmarks incl. **constructed smallcap** and **characteristic-matched** (Plan 2 §5) |
| 5.7 | Gross / base / pessimistic reporting at every level |

**Gate:** the cost model reproduces MICCV2's turn-of-month gross edge
(+129.70 bps/occurrence) **and then correctly kills it.** MICCV2 scored it at
126 bps cost → +3.70 bps net → "survives". With the fee errors fixed the cost is
136.06 bps → **−6.36 bps net → dies.**

The gate asserts the *corrected* result. This is deliberate: a regression test
that reproduces a wrong answer pins the bug. Reproducing the gross number proves
the pipeline is faithful; flipping the net sign proves the fee fix is live.

### Phase 6 — The outcome study · ~3 weeks

| Step | Detail |
|---|---|
| 6.1 | **Register all four experiments first** (§2.1 below), each with its own spec hash, incrementing the trial counter to 72 |
| 6.2 | Power analysis per stratum, before any fit (Plan 2 §6.5) |
| 6.3 | `deal_forward_outcomes` across 9 horizons × 6 benchmarks |
| 6.4 | Delisting/merger handling at 3 recovery factors (Q32) |
| 6.5 | Monthly-cohort collapse, moving-block bootstrap, NW-HAC |
| 6.6 | Three-scheme walk-forward: anchored (6) + rolling (11) + **CPCV (66 paths)** |
| 6.7 | **PBO** from the CPCV distribution |
| 6.8 | Romano–Wolf stepdown for participant/stratum ranking |
| 6.9 | **Null-calibration**: identical procedure on shuffled participant labels |
| 6.10 | Write `study_result` with corrected *p*, family size, CI, input hashes |

**Gate:** every `study_result` row has a non-null `correction_method` and
`n_tests_in_family`. Enforced by the schema, verified by a test.

### Phase 6R — Re-run exp_001 reproducibly · ~1 day

Owner decision [0013](../decisions/0013-rerun-exp001-reproducibly.md), against my
recommendation, and it had no step in this plan until 2026-08-18.

**Finding 001 is not reproducible.** The registration was correctly ordered and
the spec genuinely frozen, but the analysis code was never committed, and the
holdout is recorded as prose — "the complementary half of names" — with no seed
and no rule. Nobody can regenerate +0.237%/yr or −0.022%/yr, including me.

| Step | Detail |
|---|---|
| 6R.1 | Rebuild the analysis as committed, hashed code under the ISIN partition |
| 6R.2 | Re-derive both holdout numbers; any divergence is a finding in itself |
| 6R.3 | Register every artefact in the provenance DAG — this is its first real exercise, on a case where the answer is already known |
| 6R.4 | Carry a permanent `PRIOR_EXPOSURE` flag: ~100 exploratory cells were run against the full universe on 2026-08-16, so this can never be clean confirmation |

**Gate:** the recorded verdict is reproduced from committed code, or the
discrepancy is written up.

### Phase 7 — Seasonality rebuild and validation · ~3 weeks

| Step | Detail |
|---|---|
| 7.1 | Atlas rebuilt from scratch, 13 windows × 4 alignments × 2 bases (Q42) |
| 7.2 | Observation minimums ≥10 yearly / ≥30 monthly (Q41) |
| 7.3 | Index expansion 46 → ~202 with dedup and history eligibility (Q40) |
| 7.4 | Near-duplicate grouping incl. return-correlation > 0.9 (Q36) |
| 7.5 | BY + BH + Storey q, over the actual run test count (Q37) |
| 7.6 | Permutation, 1,000 rotations (Q38) |
| 7.7 | **Hansen SPA** for best-of-family |
| 7.8 | Three-scheme OOS + full cost model |

**Gate:** the run records its own `n_tests_in_run`. No hard-coded 31,893,556
anywhere — a test greps for it.

### Phase 8 — Monitoring and reports · ~2 weeks

Daily / weekly / monthly markdown reports (Q51), DQ gates, pause logic, and the
verification suite built to the Plan 2 §9.2 rules. Dashboard deferred.

**Gate:** the generated status page is derived from repository and database state,
not written by hand, and reproduces the live figures — test count, family
counters, collection status per source, unresolved-symbol rate against its 5%
limit. A hand-written status drifts within a week; MICCV2's README drifted from
its own crontab, this project's report claimed 146 tests against a live 220, and
three plan PDFs sat a day stale while the build reported GREEN. **Every one of
those was a number nobody had bound to anything.**

### Phase 9 — Deferred

Engines, paper portfolios, ML, LLM assistant. Not in v1.

---

### Phase 6S — Track S: the scan track · ~4 weeks

**Added 2026-08-18.** This phase plan described a one-track project. Track S —
the calendar and signal-combination search, and the half of the project the owner
identified as missing — appeared nowhere in it. Full design:
[PLAN_4_SCAN.md](PLAN_4_SCAN.md).

Runs **in parallel** with Phases 3–6, not after them. The deal machinery is
finished and idle, so building the scan track costs it nothing.

| Step | Detail |
|---|---|
| 6S.1 | `src/scan/folds.py` — anchored expanding windows + CPCV, purge and embargo. Gate: reports **effective** fold count, not just nominal (16 folds ≈ 8 independent tests) |
| 6S.2 | `src/scan/nulls.py` — measured rotation null. Gate: reproduces the drift curve, P(up) 0.461 at 1 day → 0.501 at 90 days. A flat 50% null is refused |
| 6S.3 | `src/scan/procedure.py` — the headline. Out-of-sample hit rate, degradation, PBO, rank decay |
| 6S.4 | `src/scan/calendar.py` — S1 cells. Cross-sectional rank IC only; the pooled average is **identically zero** by construction (decision 0021) |
| 6S.5 | `src/scan/signals.py` — S2 combinations, ~190 base variants to depth 3, realised width computed at run time and never hard-coded |
| 6S.6 | `src/scan/atlas.py` — chunked, resumable, checkpointed every 100k cells |
| 6S.7 | Migration `0003` — `scan_cell`, `scan_fold_result`, `procedure_result` |

**Gate before any full run:** a benchmark on 1/1000th of the grid must project the
full run inside the 21-day budget. The predecessor's "~3 weeks" was an assertion
and no cell was ever timed. If the projection exceeds budget, the grid is cut and
the cut is recorded as a decision.

**Gate on every result:** the bar comes from `simulated_max_null_t` on the actual
grid geometry, not from the formula. Fat tails raise the maximum and cell
correlation lowers it; they partly cancel, so no formula is right for a given
grid (decision 0022).

### Phase 6S dependencies on the deal track

Only two, and both are already built: `multiplicity.py` and the
registration/decision layer. Track S does **not** reuse `split.py` or `power.py`
— an ISIN partition is meaningless for a calendar cell, and a monthly cohort
collapse does not apply to observations that occur once a year. Track S has its
own partition (`split.yml § scan`) and its own power model (rank IC, measured
MDE 0.0140).

**Trial families keep the two tracks apart** (`configs/trials.yml`). Before this
existed, running Track S once would have raised Track D's bar from |t| ≥ 3.71 to
7.28 and retroactively failed `exp_001`. See
[decision 0023](../decisions/0023-trial-families-and-track-s-wiring.md).

---

## 3. Schedule — a critical path, not a sequence

**Rewritten 2026-08-18.** The previous schedule opened *"No deadline was set
(Q4)"*. That has been false since decision 0010 set **2027-02-28**. It also
totalled 22 weeks while omitting Phase 6S (4 weeks), Phase 6R and Phase 0.6.

### 3.1 Why the old schedule could not work

At 2–3 h/day averaging 15 h/week (Q5):

| | Weeks | Hours |
|---|---:|---:|
| calendar available to 2027-02-28 | 27.9 | 418 |
| plan as written, all phases | 26.2 | 393 |
| **slack** | **+1.7** | **+25** |

Six percent slack, on a project where **every estimate so far has been wrong**.
Applying its own track record:

| Overrun | Finishes | Slack |
|---|---|---|
| ×1.0 | on time | +1.7 wk |
| ×1.25 | **after** | −4.9 wk |
| ×1.5 | **after** | −11.4 wk |
| ×2.0 | **after** | −24.5 wk |

A 25% overrun — optimistic for software — misses by five weeks. The fix is not a
better estimate. It is deciding *in advance* what gets cut.

### 3.2 The critical path — 14 weeks to one defensible answer

The minimum to reach **one portfolio-gated verdict**. Nothing here is optional.

| Phase | Wk | Ends | Why it cannot be cut |
|---|---:|---|---|
| 1 · warehouse + reconciliation | 3 | 2026-09-07 | nothing is trustworthy until the gate passes |
| **2′ · collection, REDUCED** | **1** | 2026-09-14 | the stopgap already captures raw bytes daily; the full parser can wait for a study that needs it |
| 3 · identity layer | 4 | 2026-10-12 | the 34.2% join failure lives here |
| 4 · clean mart | 2 | 2026-10-26 | required |
| **6′ · costs + benchmarks** | 2 | 2026-11-09 | the 10.04 bps error is proof this cannot be skipped |
| **6″ · ONE outcome study** | **2** | **2026-11-23** | one study answered beats four half-answered |

**Critical path: 14 weeks, landing 2026-11-23** — one week inside the
2026-11-30 checkpoint, with **13.9 weeks of buffer** to the deadline.

That is 36% overrun tolerance in place of 6%.

### 3.3 Extensions, in the order they get cut

Everything below runs only if the critical path lands on time. **Listed last is
cut first**, decided now rather than under deadline pressure.

| Extension | Wk | Cumulative | Note |
|---|---:|---:|---|
| 6R · exp_001 re-run | 0.2 | 14.2 | cheap, and commissions the provenance DAG on a known answer |
| studies 2–4 | 3 | 17.2 | institutional selling first — 34,270 events, never examined |
| 6S · Track S scan | 4 | 21.2 | procedure test is the deliverable, not surviving patterns |
| 7 · seasonality — **validate, not rebuild** | 1 | 22.2 | **requires reversing owner decision 0006** — see §3.4 |
| 8 · monitoring and reports | 2 | 24.2 | **cut first.** Reports can be written by hand until there is something to report |

10.2 weeks of extensions against 13.9 weeks of buffer.

### 3.4 The one cut that needs the owner

Phase 7 is budgeted at 3 weeks for a **full 31.9M-cell rebuild**
([decision 0006](../decisions/0006-seasonality-full-rebuild.md)), chosen by the
owner against my recommendation to validate the existing atlas instead.

Validating costs ~1 week and saves 2. The case for the cut is stronger now than
when the decision was made: the predecessor already ran this scan and its own
verdict was *"the best pattern sits at the 94th percentile of rotated noise"*,
and the corrected fee schedule then killed both surviving effects.

**This is the owner's call, not mine.** It is listed as an extension so that if
the schedule holds, the full rebuild happens as decided.

### 3.5 What this changes about the kill criterion

The critical path runs **one** study. Decision 0010 abandons the thesis when
"3 of the 4 studies fail their portfolio gate" — a rule that cannot evaluate
against a single study. Reconciled in `configs/research.yml`: the count applies
to **studies actually run**, and the 2026-11-30 checkpoint becomes the primary
trigger, since it fires on the critical path alone.

**The gates still matter more than the dates.** A failed gate stops the phase.

---

## 4. What I have versus what I need

### 4.1 Have — no action required

21-year price history including 1,497 dead symbols · 174.6M F&O rows · 223,450
bulk deals · 12,430 block deals · verified trading calendar · Nifty 500 TR
benchmark · `participant_oi` FII/DII proxy 2014-2026 · index membership with
validity dates · itemised statutory cost constants · working PDF toolchain ·
Python 3.14 + uv environment.

### 4.2 Need to build — no blockers

Raw archive · NSE and BSE collectors · identity layer · PIT sectors · promoter
list · clean mart · cost model · benchmarks · outcome study · seasonality
rebuild · monitoring.

### 4.3 Need from outside — real gaps

| Gap | Impact | Route |
|---|---|---|
| **Smallcap index history** — 15 rows exist | One of six benchmarks | Construct from the price spine (Plan 2 §5.2), documented as constructed |
| **FII/DII cash history** — 22 days | Engine E deferred anyway | Unobtainable retrospectively; accrues forward from Phase 2 |
| **`available_from` for historical deals** | Timing precision pre-2026 | Measured going forward; conservative bound + LOW confidence for history |
| **Parent fund-house relationships** | Engine B deferred anyway | Manual mapping file (Q21) |
| **Owner time for 1,515 name reviews** | Blocks Phase 3 gate | ~3–4 h in the review CLI, batchable |

### 4.4 Need from the owner — decisions, not work

The open questions in §5, plus the Phase 3 review session.

---

## 5. Open questions

### 5.1 Q33 re-asked — excursions

The original question was unclear, so here it is plainly.

When an event is held for 12 months and ends **+20%**, that single number hides
the path. Two very different histories produce it:

```
Path A:   +2% … +8% … +14% … +20%        never below entry
Path B:   -41% … -22% … +5% … +20%       down 41% at the worst point
```

**Maximum Adverse Excursion (MAE)** is the worst point (−41% in Path B).
**Maximum Favourable Excursion (MFE)** is the best point reached along the way.

They matter because a strategy nobody could actually hold is not a strategy. If
institutional-follow events routinely draw down 40% before recovering, the
+7.80% headline is unreachable in practice.

**The question:** measure the worst point using *closing* prices only, or using
*intraday* lows?

- **Closing prices** — what a daily-monitoring holder would have seen. Milder.
- **Intraday low** — the true worst tick. More severe, and it is what a
  stop-loss would have hit. Your OHLC data supports it.

*My recommendation: intraday, because it is the honest worst case and understating
drawdown is the more dangerous error. Reported alongside the close-based figure
so both are visible.*

### 5.1b Resolved by the 2026-08-16 external review

| Item | Resolution |
|---|---|
| STT on delivery | **0.1% both sides**, not sell-only. MICCV2 under-charged 10 bps/round-trip. Turn-of-month's net edge flips negative |
| Exchange transaction charge | NSE **0.00307%**, BSE **0.00375%** — exchange-specific, and time-varying |
| GST base | 18% of **(brokerage + SEBI + transaction)**, not brokerage alone |
| Fee constants | Replaced by a **versioned `fee_schedule`** with `source_url` and `verified` per row |
| Book-to-market for DGTW | **Unavailable pre-2022.** Char-match becomes size × momentum × volatility × industry; BTM is a 2022+ sensitivity |
| CPCV group count | Fixed N=12 was **wrong** — purging a 24-month label exceeds a 20.6-month group. N now varies by horizon (190/120/45/15 paths) |
| PBO | CSCV logit-λ formulation specified explicitly |
| Hansen SPA | Studentised statistic + sample-dependent null; White's RC retained alongside for comparability with MICCV2 |
| CS/AR estimators | Log prices, zero-range exclusion, negative-to-zero, 15% winsorisation, overnight adjustment; both estimates + ratio stored |
| ADV / vol windows | Explicit config with alternates reported |
| Participation cap | 10% base **and 5% conservative**, the latter primary for the smallest tier |
| PROP_HFT thresholds | 95% / 20 justified from the observed bimodal distribution; 9-combination sensitivity table published |
| Review queue order | By `deal_value × contribution to unresolved rate`, so the Phase 3 gate can pass before the queue empties |
| Risk 8 | Closed in Phase 1.10 — restic to pendrive + free-tier cloud, with a watched restore drill |

### 5.2 New questions arising from the audit

**Resolved 2026-08-16:** delisting recovery — all three, headline 0.0 ·
excursions — intraday primary, close alongside · studies — all four registered
(§1.4) · brokerage — 0.03% headline with 0% reported alongside.

**Still open — the defaults below apply unless the owner says otherwise:**

1. **Consensus window.** What counts as consensus — 3+ institutions within 5, 21,
   or 63 sessions? *Default: all three as pre-declared variants inside study 1,
   with the correction accounting for three.*
2. **Consensus threshold.** 3 institutions, or 2, or 5? *Default: 3, with 2 and 5
   as declared variants.*
3. **Accumulation gap.** What gap closes an accumulation sequence?
   *Default: 63 sessions, configurable.*
4. **Repo public from day one (Q54), or at Phase 4?** Public now means negative
   findings are visible as they emerge — honest, but exposes half-finished work.
   *Default: public from Phase 1, README stating plainly it is in progress.*
5. **MICCV2 on disk after the Phase 1 gate?** Once the warehouse reconciles, its
   remaining value is its git history. *Default: keep until Phase 6, then tarball.*
---

## 6. Risks

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| 1 | **The answer is no** — no institutional edge exists | **High** | Low for the platform, high for expectations | Stated up front (Plan 2 §10). The platform's value is the ability to prove it |
| 2 | Symbol resolution stays poor, study stays biased | Medium | High | Phase 3 gate blocks at >5% unresolved |
| 3 | NSE/BSE change format or block collection | Medium | Medium | Raw bytes archived before parsing; a parse failure never loses the day |
| 4 | `available_from` unprovable for history | High | Medium | Conservative bound + LOW confidence flag; forward measurement from Phase 2 |
| 5 | 1,515 manual reviews stall | Medium | Medium | 78% is already automatic; review is batchable and the queue is prioritised by deal volume |
| 6 | Scope creep back toward engines | Medium | High | Engines are schema-only, `DISABLED`, with a test asserting the ledger stays empty |
| 7 | Rebuilding the 31.9M atlas is slow | Medium | Low | Chunked by entity, resumable, checkpointed |
| 8 | Everything on one disk, no off-machine backup | **High** | **Severe** | Carried over from MICCV2's risk register **unresolved** — see below |

**Risk 8 deserves its own line, and it now has a concrete plan.** MICCV2 recorded
"everything is on one disk, no off-machine backup" as the highest-likelihood
severe risk in its register and never closed it. The new repo inherits that
exposure the moment `v1_export` is copied: 1.2 GB of irreplaceable history on a
single laptop.

**Closed in Phase 1, step 1.10, using the owner's 256 GB pendrive plus a free
cloud tier.** Two independent failure domains, ~2 GB to protect.

| Tier | Target | Cadence | Contents |
|---|---|---|---|
| **Local** | 256 GB pendrive | Weekly, and before any destructive step | `restic` repo — `data/raw/`, `db/`, `configs/`, git bundle |
| **Off-site** | Free-tier object store (Backblaze B2 gives 10 GB free; Cloudflare R2 gives 10 GB) | Nightly, incremental | Same restic repo, encrypted |

```bash
restic -r /Volumes/BACKUP/institutional-research backup \
       data/raw db configs --exclude-caches
restic -r b2:institutional-research-backup backup data/raw db configs
restic check --read-data-subset=5%          # monthly: verify it can restore
```

**`restic` rather than `rsync`** because it is encrypted, deduplicated (2 GB of
mostly-static parquet dedupes to near nothing on repeat runs), and — the part
that matters — **verifiable**. A backup nobody has restored is a hypothesis. A
quarterly restore drill into a scratch directory is a Phase 1 deliverable, not a
later intention.

Free tiers are sufficient at 2 GB and require an owner account. Until that
exists, the pendrive alone still removes the single-disk failure mode, so the
cloud leg is not allowed to block Phase 1.

---

## 6b. When the project stops

Owner decision [0010](../decisions/0010-project-kill-criterion.md). It appeared
in `research.yml` and in no phase of this plan until 2026-08-18, which meant the
execution plan had no way to end.

**The thesis is abandoned, and written up as REJECTED, when either:**

- **3 of the 4 deal studies fail their portfolio gate**, or
- **no study has passed the portfolio gate by 2027-02-28**,

whichever comes first. Mid-point checkpoint **2026-11-30**: if no study has
reached even the event gate by then, abandon early rather than running out the
clock.

**Deliverable on abandonment:** `docs/reports/FINAL_VERDICT.md`, stating plainly
that public institutional deal disclosure does not contain a tradable edge for a
retail participant after realistic costs.

Note the schedule in §3 already runs to 2027-01-17, leaving six weeks of margin
against the deadline. That margin is the whole buffer, and Phase 6S runs in
parallel precisely because there is no room for it in sequence.

**Only a dated written amendment by the owner moves these dates** — not a good
week of results near the deadline. A deadline's entire value is being
inconvenient when it arrives.

---

## 7. Definition of done for v1

The platform is complete when it can answer, with a re-derivable number and a
recorded correction for how many times it looked:

1. Which institutions disclosed activity, and which are market makers rather than investors?
2. What happened after each disclosed transaction, at the live horizon grid
   (1/2/3/5/10/21 **sessions** primary, 3/6/12 months robustness — decision 0004
   replaced the original nine-month grid), against 6 benchmarks, net of a
   defensible cost model, **with the serial correction applied** (decision 0017)?
2b. **And does a constructed book applying that signal beat the identical book
   without it, net of costs on the incremental turnover?** An event effect and a
   useless portfolio signal are entirely compatible: `exp_001` measured −0.805%
   at t −3.93 on the event and −0.022%/yr at t −0.25 on the book, because the
   filter touched 1.2% of names. **Without this question the project can ship a
   correct event study as a tradable finding** (decision 0003).
3. Does that differ between individual deals, accumulation, and consensus?
4. Does institutional *selling* carry different information from buying?
5. Are block deals different from bulk deals?
6. Does any participant show skill that survives Romano–Wolf correction — and does the same procedure on shuffled labels find just as many?
7. Does any seasonal pattern survive observation minimums, BY/BH/Storey, near-duplicate grouping, 1,000-rotation permutation, Hansen SPA, three-scheme out-of-sample, and full costs?
8. For every one of the above: which data version, which code commit, which inputs — reachable through the provenance DAG?

**A "no" to questions 2 through 7, backed by 8, is a successful outcome.**

---

## 8. Immediate next steps on approval

```text
1. Owner answers the remaining §5.2 questions    (~10 min)
2. Owner plugs in the 256 GB pendrive            (Risk 8, local leg)
3. Freeze MICCV2 — 3 launchd agents, tag         (~10 min, reversible)
4. Repo scaffold + migration 0001                (me)
5. Copy v1_export, hash into the DAG             (me)
6. restic backup + watched restore drill         (me)
7. Rebuild the warehouse, run the §3.4 gate      (me)
8. Report: files changed, schema, tests run, limitations, next steps
```

Nothing is deleted at step 2 — agents are unloaded and plists moved, both
reversible. The first irreversible act in this plan is dropping
`MICCV2/data/warehouse/`, and that happens only **after** the Phase 1
reconciliation gate proves the new warehouse reproduces it.
