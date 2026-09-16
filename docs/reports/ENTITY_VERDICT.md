# VERDICT: DEAD — deals-based Engine 1

**No tier of named entities persists out-of-sample after costs.**

**Experiment:** `exp_002_entity_persistence` · **spec hash:** `8e7436d7aa9e9186…`
**Registered:** 2026-09-11, before any return was computed · **Status:** REJECTED
**Artefact:** `engine_1_deals_entity_verdict` — `aed486f7bf5e3009` (re-run); supersedes `92ae0987f83e869d`
**Date:** 2026-09-11 · Every number below comes from a query, not recollection.
**Corrected:** 2026-09-12 — see *Correction* below.
**Re-run:** 2026-09-16 on the warehouse, under the registered bootstrap and
`security_id` partitioning (0061). **See *Re-run* below for every live figure;
counts tagged ⚠ are the superseded originals, kept as published.**

---

## Correction, 2026-09-12: the code did not run the spec it registered

**The verdict is unchanged and is not in question.** This correction *removes*
apparent evidence for skill, so it can only harden a DEAD finding. What changed
is that several intermediate numbers printed below are now known to be wrong.

An audit of `src/research/entity_verdict.py` against the frozen registration in
`scripts/register_exp002.py` found four deviations. The registration was correct
throughout; the implementation did not follow it.

| registered | implemented | consequence |
|---|---|---|
| `permutation_policy`: moving-block bootstrap, block 63 sessions, 10,000 draws, seed 20260911 | `math.erfc(\|t\|/√2)`, a two-sided **normal approximation** on raw per-deal returns | **produced both reported FDR passes** |
| `holding_period`: "primary 63 sessions; **all 9 horizons reported**" | `HORIZONS` declared at module level and never read | eight of nine horizons never computed |
| BH-FDR at 5% | raw `p*m/rank`, without the step-up running minimum | adjusted values not monotone in *p* |
| per-entity IC (workstream item 4) | `ic_eval` field declared, never assigned | IC never computed |

**Why the first one is not a stylistic difference.** The normal approximation
clears the BH rank-1 threshold (*p* < 0.05/24 = 0.002083) at |*t*| ≥ **3.08**
*regardless of n*. The correct two-sided *t* at the same threshold needs
|*t*| ≥ **305.6** at n = 2 and |*t*| ≥ **7.10** at n = 5. The registered
bootstrap is stricter still: it cannot run at all on two deals, because two
monthly cohorts cannot fill a three-month block.

**How far this goes, stated precisely — an earlier draft of this correction
overstated it.** The registered bootstrap resamples *whole months* and needs
more than three monthly cohorts, so what decides computability is the number of
distinct months an entity's formation deals span, not the deal count:

| case | under the registered bootstrap |
|---|---|
| n = 2 (SUNDARAM), 2 months | **uncomputable** — cannot fill a three-month block |
| n = 5 (FRANKLIN TEMPLETON), ≤ 3 distinct months | **uncomputable** |
| n = 5, ≥ 4 distinct months | **computable, and may still be significant** |

Which case Franklin Templeton falls into **is not known from this environment**
— it needs the warehouse. So the honest statement is: SUNDARAM's pass is
definitely an artefact of the substituted test; Franklin Templeton's may or may
not survive, and if it survives it remains a *significantly negative* result in
the BOTTOM tier. **The verdict is unaffected either way**, because the
registered bar requires a passer in the **TOP** tier and both sit in BOTTOM.

The memo already argued these
passes were meaningless *on sample-size grounds*; the stronger and more
uncomfortable statement is that **they were never passes under the registered
design at all.**

`src/research/power.py:198` has carried `block_bootstrap_ci` — the exact
registered procedure, seed parameter and all — since before this study ran. It
had **no callers anywhere in the codebase.**

**What is now fixed in code**, verified by `tests/test_entity_verdict_stats.py`
(16 tests, no warehouse required): `_p_form` runs the registered bootstrap and
returns `None` where it cannot run; `_bh` is a proper step-up; `_rank_ic`
computes IC with a five-observation floor; `build()` reports all nine horizons.

**What is NOT fixed here.** The corrected figures are not in this memo, because
recomputing them requires the warehouse (`db/research_prod.duckdb`,
`data/warehouse/`), which is gitignored and absent from the environment this
correction was made in. **Every count below tagged ⚠ is superseded and awaits a
re-run.** Inventing replacements would be the failure this project exists to
refuse. The re-run must use the unchanged `spec_hash`
`8e7436d7aa9e9186…`, since the registration never needed amending — only the
code did.

---

## Re-run, 2026-09-16 — the registered procedure, on the data

The correction above was made without the warehouse and left every count
tagged ⚠. This is the re-run it asked for: same `spec_hash 8e7436d7aa9e9186…`,
`_p_form` running the registered moving-block bootstrap (block 63 sessions,
10,000 draws, seed 20260911), BH as a step-up, all nine horizons, and — because
[0061](../decisions/0061-studies-join-prices-on-security-id.md) landed in
between — prices attached by `security_id` rather than ticker.

**VERDICT: DEAD. Unchanged. But on the other leg of the bar.**

| | 2026-09-11 (superseded) | **2026-09-16 (registered procedure)** |
|---|---|---|
| passed BH-FDR 5% anywhere | ⚠ 2 | **4** |
| passed BH-FDR 5% in the TOP tier | 0 | **1** (SBI Life Insurance) |
| TOP tier, out-of-sample, net of costs | +1.11% | **−0.88%** |
| MID / BOTTOM, out-of-sample | −1.46% / +0.13% | **−1.02% / +1.54%** |
| cross-entity rank IC (formation → evaluation) | not computed | **−0.049** |
| entities with zero formation deals | 12 | 12 |
| entities untestable (too few months for the block) | not distinguished | **5** |

Under the substituted normal approximation, condition (a) failed and the memo
argued from there. Under the registered bootstrap, **condition (a) is met** —
SBI Life Insurance sits in TOP and clears FDR — **and condition (b) fails**: the
TOP tier loses 0.88% net of costs out-of-sample. The bar requires both. Dead
either way, and the corrected reading is the harder one for the hypothesis: the
tiers are now **fully inverted** (BOTTOM +1.54% is the best-performing tier) and
the rank IC is indistinguishable from zero.

### The four passes, and what "p = 0.0001" means on five deals

| entity | formation deals | formation excess | *p* | *q* | tier |
|---|---:|---:|---:|---:|---|
| SBI LIFE INSURANCE | **4** | +12.78% | 0.0001 | 0.0006 | **TOP** |
| SBI MUTUAL FUND | 5 | +7.67% | 0.0001 | 0.0006 | MID |
| ICICI PRUDENTIAL MUTUAL FUND | 5 | +6.99% | 0.0001 | 0.0006 | MID |
| FRANKLIN TEMPLETON MUTUAL FUND | 5 | −11.92% | 0.0001 | 0.0006 | BOTTOM |

Every one of them reports **exactly *p* = 0.0001 — the floor of a 10,000-draw
bootstrap** (1/(B+1)). With four or five values to resample, the block bootstrap
never produces a resampled mean that crosses zero, so the *p*-value saturates at
its own resolution. Four "significant" entities with identical *p* at the floor
is not four discoveries; it is the bootstrap reporting that it has too few
observations to describe a null. Two of them are significantly *positive* and
one significantly *negative* in formation, and none of it predicts evaluation:
SBI Life +3.42%, ICICI Pru MF −2.83%, SBI MF +0.74%, Franklin +0.86%.

The two entities the original memo called passes: **Sundaram** (2 deals, 2
months) is **uncomputable** under the registered block — two monthly cohorts
cannot fill a 63-session block — and is confirmed an artefact of the substituted
test. **Franklin Templeton** (5 deals across ≥4 months) is computable and
**does** pass, which the correction of 2026-09-12 was right to leave open. It
sits in BOTTOM on −11.92%. A pass in the wrong direction.

### All nine horizons, as registered

Pooled excess return across the 24 tested entities, net of the full cost stack:

| 1s | 2s | 3s | 5s | 10s | 21s | **63s** | 126s | 252s |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| −0.76% | −1.03% | −0.95% | −0.44% | −0.61% | +0.17% | **−0.68%** | +1.27% | +4.24% |

Negative at every horizon out to three months; positive at six and twelve. The
registered primary is 63 sessions, and it is negative. The 252-session figure is
pooled across all 24 names, is not the registered metric, and is reported
because the registration said all nine would be — not because it changes
anything.

## The answer

The registered pass bar was: *the TOP tier must (a) contain at least one entity
passing BH-FDR 5% in-sample on 2006–2015, AND (b) beat its benchmark
net-of-costs on 2016–2026. Both, not either.*

| | |
|---|---|
| entities tested (LONG_ONLY) | 24 |
| passed BH-FDR 5% **anywhere** | ⚠ **2** — artefact of the substituted test; awaits re-run |
| passed BH-FDR 5% **in the TOP tier** | **0** |
| TOP tier, out-of-sample, net of costs | +1.11% |

**Condition (a) fails.** Both passers sit in the **BOTTOM** tier, and they got
there on *significantly negative* formation excess. A passed test in the wrong
direction is not a finding.

## Why the two "passes" are not evidence of anything

> ⚠ **Superseded by the correction above.** Both rows below were produced by a
> normal approximation that the registration did not authorise. Under the
> registered moving-block bootstrap neither entity is testable. The section is
> kept as written because the record of what was published matters more than a
> tidy memo.

| entity | formation deals | formation excess | q | tier |
|---|---:|---:|---:|---|
| SUNDARAM MUTUAL FUND | **2** | −27.09% | 0.0000 | BOTTOM |
| FRANKLIN TEMPLETON MUTUAL FUND | **5** | −11.86% | 0.0037 | BOTTOM |

A *t*-statistic on **two observations** produced *p* = 0.0000. The screen did
exactly what it was told; the sample is what makes the answer meaningless. This
is the same mechanism [0056](../decisions/0056-the-participant-study-cannot-be-run-and-the-machine-does-not-invent-findings.md)
measured across nine horizons — **the ranking tracks sparsity, not skill** —
appearing again under a different specification.

The tier means say the same thing. TOP +1.11%, **MID −1.46%**, BOTTOM +0.13%.
**Non-monotonic.** If formation-period ranking carried information, the
evaluation period would order TOP > MID > BOTTOM. It does not.

## The deeper finding: the registered walk-forward could not be run

| | |
|---|---|
| directional deals from tested entities | 1,539 |
| in the **formation** window (2006–2015) | **245** |
| in the **evaluation** window (2016–2026) | 1,294 |
| entities with **zero** formation-period deals | **12 of 24** |
| entities with ≥10 formation deals | 7 |
| entities with ≥30 | 3 |

**Half the tested entities cannot be tiered at all.** Most Indian AMCs in this
list — Motilal Oswal, Quant, Mirae, WhiteOak, Bandhan, Edelweiss, Nippon,
Aditya Birla — did not trade at bulk-deal scale before 2016.

The specification was run exactly as written anyway. Moving the split to where
the data is thick would have been choosing a design after seeing which design
would work, and that is the failure this project exists to refuse. **A study
that cannot be run is a different verdict from a study that ran and found
nothing**, and the distinction is recorded rather than blurred.

## What was done differently this time, and why it still died

This was the first specification in which the tested names were plausibly
*decision-makers*, and two steps were taken before any return was computed:

**Name normalisation.** 20,660 → 19,248 entities; 1,412 merged. Candidates at
the ≥30-deals/≥12-months floor: **119 → 133**. That mattered qualitatively, not
just numerically — HDFC Standard Life carried **eight** spellings, SBI Life six.
Fragmentation had been hiding exactly the long-only institutions the study
needed while leaving the ETFs plainly visible.

**Economic-role classification**, on names only, never on outcomes:

| role | entities | deals | tested? |
|---|---:|---:|---|
| UNKNOWN | 78 | 4,393 | no — reported, not tested |
| BANK_EXECUTION | 27 | 2,995 | **excluded** |
| **LONG_ONLY** | **24** | **1,539** | **yes** |
| ARBITRAGE | 2 | 388 | **excluded** |
| ODI_ISSUER | 2 | 263 | **excluded** |

Exclusions were declared in `src/research/roles.py` with written reasons before
any return existed. A cash bulk buy from an arbitrage desk is a delta hedge, not
a view; its forward return is mechanically related to the underlying and would
have read as skill in-sample.

So the population was the best this data can produce — HDFC, SBI, ICICI
Prudential, Norges Bank, the major Indian AMCs — and it still fails, for the
reason every previous specification failed: **there are not enough disclosure
events, early enough, per entity.**

## A bug worth recording, because it nearly produced the opposite answer

The first implementation tested `passed_fdr > 0 AND top_beats > 0` — that *any*
entity passed, not that a **TOP-tier** one did — and reported **ALIVE**. The
registration says "the TOP tier must contain at least one entity passing".

The loose reading converted a failed bar into a finding, on the strength of two
entities that were significantly *negative*. The registration was frozen and
correct; the code was wrong. A test now asserts `alive` equals the registered
conjunction exactly, and it was watched failing.

## Kill criteria, met

> "If no tier passes FDR in-sample AND beats the benchmark net-of-costs
> out-of-sample, deals-based Engine 1 is DEAD."

**Deals-based Engine 1 is dead.** Recorded as artefact
`engine_1_deals_entity_verdict` in `governance.sqlite`, the same way
`prop_hft_classifier_coverage` was.

## What would reverse it

An additional decade of pre-2016 disclosure from the AMCs that now dominate the
tape — which does not exist and cannot be fetched, since the historical endpoint
answers 503. Nothing in method fixes 245 formation-period deals across 24
entities.

## What this does not say

It does not say Indian institutions have no skill. It says **their disclosed
bulk and block deals do not reveal it at this sample size**, that the one
apparent signal came from two deals, and that the instrument used to reach that
conclusion was checked against noise and does not manufacture findings
([0056](../decisions/0056-the-participant-study-cannot-be-run-and-the-machine-does-not-invent-findings.md):
1.8% false-positive rate against a nominal 5%).
