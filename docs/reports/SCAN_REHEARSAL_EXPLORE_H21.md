# SCAN_REHEARSAL_EXPLORE_H21.md — exp_005's analysis on EXPLORATION data

**EXPLORE (2005-2015), yearly test windows 2010-2015: the registered analysis rehearsed on data it is free to read. Not a finding; nothing recorded in the ledger.**

**Verdict: REDISCOVERS_KNOWN_FACTORS**

Folds: 6 folds, ~6.0 independent: test windows are disjoint; training is anchored, so consecutive folds share nearly all of it. PBO over the folds: 0.00.

## Primary — the search procedure, plain IC

| top N | hit rate | null mean | p | q (BH) | train IC | test IC | degradation | rank decay |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | **1.00** | 0.50 | 0.018 | 0.018 | +0.0889 | +0.0978 | -0.0088 | +0.772 |
| 10 | **1.00** | 0.50 | 0.016 | 0.018 | +0.0869 | +0.0935 | -0.0066 | +0.772 |
| 100 | **1.00** | 0.50 | 0.017 | 0.018 | +0.0834 | +0.0932 | -0.0097 | +0.772 |

## Attribution — partial IC net of hi_252, downvol_126

| top N | hit rate | null mean | p | q (BH) | train IC | test IC |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | **0.83** | 0.50 | 0.110 | 0.110 | +0.0574 | +0.0242 |
| 10 | **0.83** | 0.49 | 0.108 | 0.110 | +0.0562 | +0.0247 |
| 100 | **0.83** | 0.49 | 0.100 | 0.110 | +0.0534 | +0.0233 |

## Costs — selected sets as long-short books, pessimistic level

| top N | mean gross / rebalance | mean net / rebalance | folds net > 0 | mean turnover |
|---:|---:|---:|---:|---:|
| 1 | +2.37% | +1.56% | 5/6 | 29% |
| 10 | +2.34% | +1.55% | 6/6 | 28% |
| 100 | +2.34% | +1.53% | 6/6 | 29% |
