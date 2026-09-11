# VERDICT: DEAD — deals-based Engine 1

**No tier of named entities persists out-of-sample after costs.**

**Experiment:** `exp_002_entity_persistence` · **spec hash:** `8e7436d7aa9e9186…`
**Registered:** 2026-09-11, before any return was computed · **Status:** REJECTED
**Artefact:** `engine_1_deals_entity_verdict` (`92ae0987f83e869d`)
**Date:** 2026-09-11 · Every number below comes from a query, not recollection.

---

## The answer

The registered pass bar was: *the TOP tier must (a) contain at least one entity
passing BH-FDR 5% in-sample on 2006–2015, AND (b) beat its benchmark
net-of-costs on 2016–2026. Both, not either.*

| | |
|---|---|
| entities tested (LONG_ONLY) | 24 |
| passed BH-FDR 5% **anywhere** | **2** |
| passed BH-FDR 5% **in the TOP tier** | **0** |
| TOP tier, out-of-sample, net of costs | +1.11% |

**Condition (a) fails.** Both passers sit in the **BOTTOM** tier, and they got
there on *significantly negative* formation excess. A passed test in the wrong
direction is not a finding.

## Why the two "passes" are not evidence of anything

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
