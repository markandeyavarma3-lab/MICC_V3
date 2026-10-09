# SCAN_CONFIRM_H21_REMEASURE_0088.md — exp_005 on the corrected spine

**RE-MEASURE under decision 0088 (corrected price spine), same CONFIRM window as the registered run. Not the registered result; nothing recorded in the ledger.**

**Verdict: NO_SEARCH_SKILL**

Folds: 11 folds, ~11.0 independent: test windows are disjoint; training is anchored, so consecutive folds share nearly all of it. PBO over the folds: 0.27.

## Primary — the search procedure, plain IC

| top N | hit rate | null mean | p | q (BH) | train IC | test IC | degradation | rank decay |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | **0.73** | 0.50 | 0.118 | 0.126 | +0.0903 | +0.0538 | +0.0365 | +0.399 |
| 10 | **0.73** | 0.50 | 0.109 | 0.126 | +0.0889 | +0.0514 | +0.0375 | +0.399 |
| 100 | **0.73** | 0.51 | 0.126 | 0.126 | +0.0869 | +0.0496 | +0.0373 | +0.399 |

## Attribution — partial IC net of hi_252, downvol_126

| top N | hit rate | null mean | p | q (BH) | train IC | test IC |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | **0.82** | 0.50 | 0.046 | 0.046 | +0.0469 | +0.0198 |
| 10 | **0.91** | 0.50 | 0.006 | 0.012 | +0.0460 | +0.0288 |
| 100 | **0.91** | 0.50 | 0.008 | 0.012 | +0.0440 | +0.0283 |

## Costs — selected sets as long-short books, pessimistic level

| top N | mean gross / rebalance | mean net / rebalance | folds net > 0 | mean turnover |
|---:|---:|---:|---:|---:|
| 1 | +1.35% | +0.94% | 7/11 | 26% |
| 10 | +1.30% | +0.90% | 6/11 | 25% |
| 100 | +1.27% | +0.86% | 6/11 | 26% |
