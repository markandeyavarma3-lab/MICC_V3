# SCAN_CONFIRM_H21.md — exp_005, the registered run

**CONFIRM (2016+), spec_hash `96cffcb539f7`, commit `ced0fba576bd`. Run once.**

**Verdict: NO_SEARCH_SKILL**

Folds: 11 folds, ~11.0 independent: test windows are disjoint; training is anchored, so consecutive folds share nearly all of it. PBO over the folds: 0.27.

## Primary — the search procedure, plain IC

| top N | hit rate | null mean | p | q (BH) | train IC | test IC | degradation | rank decay |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | **0.73** | 0.50 | 0.114 | 0.114 | +0.0891 | +0.0560 | +0.0331 | +0.400 |
| 10 | **0.73** | 0.50 | 0.105 | 0.114 | +0.0878 | +0.0493 | +0.0385 | +0.400 |
| 100 | **0.82** | 0.51 | 0.037 | 0.111 | +0.0858 | +0.0488 | +0.0369 | +0.400 |

## Attribution — partial IC net of hi_252, downvol_126

| top N | hit rate | null mean | p | q (BH) | train IC | test IC |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | **0.91** | 0.50 | 0.009 | 0.009 | +0.0463 | +0.0267 |
| 10 | **0.91** | 0.50 | 0.006 | 0.009 | +0.0454 | +0.0290 |
| 100 | **0.91** | 0.50 | 0.008 | 0.009 | +0.0434 | +0.0296 |

## Costs — selected sets as long-short books, pessimistic level

| top N | mean gross / rebalance | mean net / rebalance | folds net > 0 | mean turnover |
|---:|---:|---:|---:|---:|
| 1 | +1.32% | +0.91% | 7/11 | 26% |
| 10 | +1.25% | +0.85% | 6/11 | 25% |
| 100 | +1.23% | +0.82% | 7/11 | 26% |

## Reading it — by the registered ladder, and what it does not license

**The registered verdict is NO_SEARCH_SKILL.** No N passes the primary at
BH 5% (q 0.111–0.114). Top 100 had raw p 0.037, which fails after the
correction over the three N declared before the run. On 2016+ the
training-selected sets were positive out of sample in 8–9 of 11 years, but
not more often than the block-sign-flip null allows across 11 independent
folds.

**What changed from exploration.** The search no longer reads the future
cleanly:

| | exploration 2010–2015 | confirmation 2016–2026 |
|---|---|---|
| train IC | 0.09 | 0.09 |
| test IC | 0.09 | 0.05 |
| degradation | ~0 | +0.035 |
| rank decay | 0.77 | 0.40 |
| PBO | 0.00 | 0.27 |

The edge that momentum and low volatility carried in 2010–2015 roughly halved
after 2016. That fits the factors being widely traded.

**The partial-IC row is the surprise, and it is not a finding.** Net of
momentum and low volatility, the search's selections were positive in 10 of
11 years (q 0.009). The ladder requires the primary to pass first, and that
order was fixed before the run, so this row cannot change the verdict.
Reading it as "searching finds residual signal" would be choosing the result
after seeing it, which is the error this project was built to refuse. It
defines a new hypothesis, which would need its own registration and its own
family charge: "the factor-neutral residual of a wide search persists".

**Costs.** The selected sets stayed positive at the pessimistic level: about
+0.8–0.9% per monthly rebalance, net positive in 6–7 of 11 years. With no
significant selection skill, that is an average over years of mixed sign, not
a strategy.

**Procedural note.** The first CONFIRM attempt (13:14) was cut off when the
Mac shut down at 13:38, before anything was recorded. The atlas shards it had
written were reused by the 18:45 run under the manifest guard (same panel,
horizon, depth and statistic), and that run recorded once.
