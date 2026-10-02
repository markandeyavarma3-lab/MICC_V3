# SCAN_EXPLORE_H21.md — Track S procedure test, EXPLORATION ONLY

**Regime EXPLORE (2005-2015; split.yml scan.temporal). Not a finding.** run_id `88d48ded3a5f9d20`, commit `922c5edb07e8`. Recorded write-once in governance `procedure_result`. It informs the CONFIRM registration, which tests 2016+ once.

- grid: 1,929,213 candidates — 143 base signals to depth 3 (signed rank composites, decision 0084), forward horizon 21 sessions after a one-session gap
- panel: 2005-01-03 .. 2015-12-31, 1,321 names ever in the point-in-time top 500
- folds: 5 folds, ~3.0 independent: consecutive folds share 1/2 of their test window and nearly all their training
- null: block sign flips, 200 reps (procedure.null_hit_rates)
- PBO over 120 CPCV paths: **0.14**

| top N | folds | effective | hit rate | null mean | p vs null | train IC | test IC | degradation | rank decay |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 5 | 3.0 | **1.00** | 0.49 | 0.080 | +0.0879 | +0.0917 | -0.0038 | +0.801 |
| 10 | 5 | 3.0 | **1.00** | 0.50 | 0.100 | +0.0858 | +0.0857 | +0.0001 | +0.801 |
| 100 | 5 | 3.0 | **1.00** | 0.49 | 0.095 | +0.0820 | +0.0860 | -0.0040 | +0.801 |

Per-fold test IC of the selected set (sequential folds, training sign):

- top 1: seq_2010 +0.0460, seq_2011 +0.0788, seq_2012 +0.1317, seq_2013 +0.1136, seq_2014 +0.0884
- top 10: seq_2010 +0.0572, seq_2011 +0.0745, seq_2012 +0.1056, seq_2013 +0.1073, seq_2014 +0.0838
- top 100: seq_2010 +0.0543, seq_2011 +0.0739, seq_2012 +0.1171, seq_2013 +0.1030, seq_2014 +0.0817

## What drives it — read before any number above

**Not a leak; the two best-known equity anomalies.** The strongest depth-1
signals over 2007–2015 (mean IC, h = 21):

| signal | IC | family |
|---|---:|---|
| hi_252 (price / 52-week high) | +0.077 | momentum |
| downvol_126, downvol_63 | −0.072 | volatility (low-vol anomaly) |
| ram_252, ram_126 (risk-adjusted momentum) | +0.071, +0.067 | momentum |
| ma_cross_50_200 | +0.065 | momentum |
| vol_252, beta_252 | −0.064, −0.064 | volatility |

Bulk/block deal signals (dnet_*) sit at ±0.0004, the weakest of all 143. That
matches Track D's verdicts.

**The leak check is the year profile.** hi_252 is positive in every year
except the one containing the March–May 2009 rebound (−0.079), the
best-documented momentum crash. A look-ahead artefact does not crash in the
year momentum crashed; a factor does.

**So the exploration result is a rediscovery, not a discovery.** A wide
search reliably selects momentum and low-volatility composites, and in
2010–2015 they persisted out of sample: hit rate 5/5, degradation about 0,
rank decay 0.80, PBO 0.14. These factors were published years before this
sample (momentum 1993, 52-week high 2004, low volatility 2006). That is why
nothing degrades: the search finds what was already true and already known.

**Three things the CONFIRM registration must take from this:**

1. **Power.** Five folds with about 3 independent give p ≈ 0.08–0.10 even
   for a perfect hit rate. The confirm design needs about 10 independent
   folds (1-year test windows, 1-year step, 2016+).
2. **Attribution.** The confirm report must say how much of the selected
   set's test IC is momentum and low-volatility exposure, for example by
   regressing on those two depth-1 signals. A procedure that only rediscovers
   two published factors is not evidence that searching finds anything new.
3. **Costs.** A monthly-rebalanced top-500 composite turns over heavily, so
   the SIGNIFICANT_BUT_UNPROFITABLE verdict (scan.yml `costs`) must be
   evaluated before any pass is claimed.
