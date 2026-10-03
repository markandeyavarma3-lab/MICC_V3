# exp_005 — Does a wide signal search work on 2016+? (Track S confirmation)

**Status: REGISTERED 2026-10-03 (0085) and RUN — verdict NO_SEARCH_SKILL (docs/reports/SCAN_CONFIRM_H21.md).**
Machine-readable form: `scripts/register_exp005.py` (rehearsed on a ledger
copy; the real ledger was unchanged). The analysis: `src/scan/confirm.py`.

## 1. The question

Plan 4 §4: **across walk-forward folds, does a candidate selected in
training keep winning in testing?** The question is about the search
procedure, not any one pattern. The scan is the instrument: 143 base
signals combined to depth 3, 1,929,213 candidates. Only one procedure is
under test per top-N, so the family (TRACK_S_PROCEDURE) has size 3 however
wide the scan.

## 2. What exploration showed (2005–2015, free to mine)

`docs/reports/SCAN_EXPLORE_H21.md`:

- **Hit rate:** 5/5 folds for the top 1, 10 and 100.
- **Test IC:** about +0.086, with degradation of about 0 and rank decay
  0.80. PBO 0.14.
- **p vs null:** 0.08–0.10. Five overlapping folds are about 3 independent
  tests, so even a perfect hit rate cannot reach significance.
- **What drove it:** momentum (52-week high, risk-adjusted momentum) and low
  volatility. These were published 1993–2006. The momentum signal is
  negative only in 2009, the year of the momentum crash, which is how a
  factor looks and not how a leak looks.
- **Deal signals** are the weakest of all 143.

`docs/reports/SCAN_REHEARSAL_EXPLORE_H21.md` adds the full registered
analysis (attribution and costs) rehearsed on the same data. See §5.

## 3. The design, and why each part is there

| part | choice | why |
|---|---|---|
| test data | 2016 → data end, never read before registration | split.yml `scan.temporal`: confirmation is spent once |
| folds | disjoint yearly test windows, anchored training from 2005, 21-session embargo: **11 folds, all independent** | exploration's ~3 independent folds could not conclude anything |
| statistic | rank IC on one cross-section per date (decision 0084); depth 1 is Spearman, depth 2–3 the rank-composite IC | exact and fast: the full grid scores in minutes |
| horizon | 21 sessions after a 1-session gap; 5 reported, never tested | monthly turnover is what costs leave room for; short windows carry bid-ask bounce |
| selection | top N by \|mean train IC\|, test read in the training sign, N ∈ {1, 10, 100} | scan.yml `procedure_test` |
| null | block sign flips, 21-session blocks shared by all candidates, **1,000 reps** | measured, not assumed; the first null was biased and a test caught it |
| multiplicity | Benjamini–Hochberg across the three N at 5% | the declared family |
| attribution | the same procedure on the **partial IC** net of hi_252 and downvol_126 | exploration found the search selecting exactly these two factors |
| costs | each fold's selected set as long–short books (top/bottom 20%, rebalanced every 21 sessions, ₹100 crore), pessimistic costs.yml level | scan.yml: every pattern is costed before it is reported |

## 4. The verdict ladder, fixed now

1. **NO_SEARCH_SKILL:** no N passes the primary.
2. **REDISCOVERS_KNOWN_FACTORS:** the primary passes, but no passing N also
   passes the partial-IC procedure.
3. **SIGNIFICANT_BUT_UNPROFITABLE:** an N passes both, and every such N has a
   mean net spread at or below 0.
4. **SEARCH_FINDS_NEW_EDGE:** all three pass.

**The expectation, stated in advance:** the plain procedure passes but more
weakly than 2010–2015, since factor investing spread in India after about
2017. The partial procedure does not pass. The likeliest verdict is
**REDISCOVERS_KNOWN_FACTORS**.

## 5. Rehearsal on exploration data

`docs/reports/SCAN_REHEARSAL_EXPLORE_H21.md` is the whole analysis on
2005–2015 with six disjoint yearly test windows (2010–2015) and 1,000 null
reps. It ran in 39 minutes.

| | result |
|---|---|
| primary | hit rate 6/6 for every N, p 0.016–0.018, q 0.018; test IC +0.093–0.098; degradation about −0.01; rank decay 0.77; PBO 0.00 |
| attribution, net of hi_252 and downvol_126 | hit rate 5/6, p 0.10–0.11, q 0.11; test IC +0.024 |
| costs, pessimistic | +2.34% gross and +1.55% net per monthly rebalance; net positive in 6/6 folds (top 10/100); turnover 29% |
| **verdict** | **REDISCOVERS_KNOWN_FACTORS** |

Every part of the pipeline runs end to end on real data. On the data it was
free to read, the search passes and its residual does not. One number to
watch in the confirm report: a net long-short spread of about 1.5% a month is
large. 2010–2015 was a strong period for momentum and low volatility in India,
and 2016+ is what tests whether it held.

Two speed fixes were made before this run, both with identical results
(tested): partial selection with one shared null pass, and the
partial-IC gather and matmul (an estimated 66 h fell to 7 min).

## 6. What the owner decides before registration

1. **The attribution factors:** hi_252 and downvol_126, the strongest
   momentum and low-volatility signals in exploration. (Choosing them from
   exploration is what exploration is for. Choosing them after seeing 2016+
   would not be.)
2. **Top N {1, 10, 100}** and **1,000 null reps**.
3. **The cost level (pessimistic) and book size (₹100 crore)**, the same as
   exp_004.
4. **The verdict ladder** as written in §4.
