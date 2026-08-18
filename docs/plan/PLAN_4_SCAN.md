# Plan 4 of 4 — Track S: mass pattern search, walk-forward validated

**Written 2026-08-18.** Live parameters: [`configs/scan.yml`](../../configs/scan.yml).
This document explains; the config defines.

---

## 0. Why this document exists

Plans 1–3 describe Track D — the institutional deal event studies. Their
machinery is built: `power.py`, `split.py`, `multiplicity.py`, `design.py`, 146
tests.

**None of it serves the mass-search side of the project**, which the owner
correctly identified on 2026-08-18 as being half the point and absent from the
system. The 31.9M combinations existed in configs, two decision records and a
paragraph of prose, with zero lines of code behind them.

This plan corrects that. It is the design for Track S, which runs in parallel
with Track D and shares the registration, decision and multiplicity layers.

---

## 1. What Track S is, in one paragraph

Search a very large space of candidate patterns — calendar patterns and
combinations of trading signals — inside a training window, then require each
candidate to repeat in a window it has never seen. Do this across many folds.
**Report as the headline not which patterns survived, but how well the search
procedure itself performed out of sample.** Report surviving patterns second.

---

## 2. What the predecessor did, and the one thing it never asked

MICCV2 scanned **31,893,556 cells**: 13 windows × 242 calendar ordinals × 4,200
symbols, plus index-level variants across 4 alignments and 2 bases.

Its own verdict, from `docs/SEASONALITY_FINDINGS.md`:

> *"Essentially none of it survives contact with its own null. The single best
> pattern found in NIFTY50 — a 3-day window that rose in 94.7% of years — sits at
> the 94th percentile of what randomly rotated data produces, which is to say it
> is an ordinary result of looking 31.9 million times."*

And the finding that matters most:

> *"The scan of millions found nothing. The eight pre-registered guesses found
> two. That asymmetry is the finding."*

Both of those two were subsequently killed by the corrected fee schedule —
turn-of-month goes from **+3.70 to −6.36 bps** net.

**What it never asked.** Every one of those 31.9M cells was scored against a
single sample. The question was *"is this cell better than chance in-sample?"*
It was never *"does this cell do it again?"* — which is the only question a
seasonal or signal claim actually makes.

That is the gap this track closes.

---

## 3. Three measurements that determined the design

Everything below was measured on 17–18 August 2026 before any of this plan was
written. Under the project's own Rule 1, no design element enters a plan without
a computed number beside it.

### 3.1 A calendar cell fires once a year, and that is fatal per stock

| Fold | Train obs | Test obs |
|---|---|---|
| train 2005–10 → test 2010–12 | 5 | **2** |
| train 2005–15 → test 2015–20 | 10 | **5** |
| train 2005–18 → test 2018–21 | 13 | **3** |

Two observations detect an effect of **49.5% per year**. Five detect 31.3%. A
stock's entire 21-year history detects 15.3%.

The history is not there either. Distribution of price history across 4,200
symbols:

| Percentile | Years |
|---|---|
| 25th | 2.3 |
| **50th** | **5.5** |
| 75th | 14.7 |
| 90th | 21.0 |

Only **513 of 4,200** have 20+ years — and "survived twenty years" is itself a
survivorship-selected sample.

**Conclusion: per-stock calendar analysis is not difficult, it is arithmetically
impossible.** It is still run and reported, marked UNDERPOWERED with its MDE
beside it, because "we could not tell" is a more useful statement than silence.

### 3.2 Pooling across stocks does not rescue it — and the obvious fix is undefined

The obvious response is to pool: 4,200 stocks × 5 years = 21,000 observations,
MDE 0.48%/yr. That reasoning fails twice, and both failures are instructive.

**First failure — raw prices.** Every stock experiences trading day 47 **on the
same day**, so all of them share whatever the market did. Measured mean pairwise
correlation of raw daily returns across 656 liquid names, 2015+: **ρ = +0.2350**,
giving n_eff of **4.3** out of 21,000 and an MDE of **33.95%/yr**. Raw-price
pooling is dead. The predecessor treated `PRICE` and `MARKET_RELATIVE` as equal
bases; its entire PRICE-basis pooled output was arithmetically worthless.

**Second failure — and this one I got wrong first time.** An earlier draft of
this plan reported that market-relative returns have ρ = +0.0001, "indistinguishable
from independence", and concluded that removing the market factor multiplies
effective sample size by ~1,550×.

**That was an artifact.** Subtracting the cross-sectional mean forces average
pairwise correlation to −1/(N−1) *regardless of the input*. Verified against
simulated controls:

| Input | Raw ρ | After demeaning |
|---|---|---|
| pure independence, N=657 | −0.00003 | −0.00148 |
| strong market factor, N=657 | **+0.4035** | −0.00145 |
| theoretical −1/(N−1) | — | −0.00152 |

The statistic cannot distinguish a strong market factor from pure noise. It
measured the arithmetic of subtraction.

**And the real consequence is larger than the erratum.** If market-relative means
"minus the cross-sectional mean", then the cross-sectional mean *of* market-relative
returns is identically zero. Measured across 656 stocks and 2,870 sessions, the
largest absolute value on any day is **1.698 × 10⁻¹⁷**.

> **"Is trading day 47 good on average, market-relative?" is not a weak question.
> It has no content. The answer is exactly zero for every day, by construction.**

So the pooled-average formulation is not underpowered — it is *undefined*. Which
means the cross-sectional formulation in §5 is not the strongest option among
several. **It is the only one.** See [decision 0021](../decisions/0021-pooled-average-is-undefined.md).

### 3.3 Hundreds of folds are not hundreds of tests

Anchored expanding windows share almost all of their training data — consecutive
folds are roughly 95% the same fit.

| Design | Folds | Independent tests |
|---|---|---|
| anchored, 2y test, 1y step, 2010–2026 | 16 | **8** |
| anchored, 2y test, 2y step (disjoint) | 8 | 8 |
| anchored, 1y test, 1y step (disjoint) | 16 | 16 |
| CPCV, N=16 groups, k=2 | **120** | 16 |
| CPCV, N=20 groups, k=2 | **190** | 20 |

So "make some hundreds of tests" is achievable, but the honest evidence count is
8–20, not 120–190. Both designs are run because they answer different questions:

- **Sequential walk-forward** answers *"would this have worked if I had deployed
  it in real time?"* — the deployment question, and the one originally asked.
- **CPCV** yields many more paths, which is what a stable estimate of
  overfitting probability requires.

Neither substitutes for the other, and every result reports its effective fold
count alongside its nominal one.

---

## 4. The headline: testing the procedure, not the patterns

### 4.1 The reframing

The natural design is *find the best pattern in training, test it in the test
window.* That yields **one out-of-sample test per fold**. Run 31.9M candidates
through it and the best survivor across 8 folds is still very likely luck.

The stronger design inverts what is under test:

> **Across all folds, how often does a pattern selected in training actually win
> in testing?**

This measures the **search procedure**, not any pattern. And it makes scan width
an asset rather than a liability: the wider the search, the more precisely you
measure how badly searching overfits.

### 4.2 What gets computed

For each fold, rank every candidate by its training statistic, take the top
*N* ∈ {1, 10, 100}, and measure their performance in the untouched test window.

| Metric | Question |
|---|---|
| **Out-of-sample hit rate** | Fraction of folds where the training-selected set beat zero |
| **Degradation** | Training statistic minus test statistic — how much was illusion |
| **PBO** | Probability of backtest overfitting (CSCV logit-λ) |
| **Rank decay** | Do training ranks predict test ranks at all? |

### 4.3 Both outcomes are results

| Outcome | Meaning |
|---|---|
| Hit rate ≈ **50%** | Mass scanning does not work on this data. **This is the most likely outcome and it is a genuine methodological finding** — it generalises well beyond this dataset. |
| Hit rate **> 50%** | The selection procedure carries information. Report the hit rate as headline, surviving patterns as secondary. |

Crucially the bar here is **not** deflated by the number of cells scanned. There
is exactly one procedure under test per configuration — a family of three, one
per value of *N*. Scanning 31.9M candidates does not make the procedure test
harder to pass; it makes it more precise.

---

## 5. The only viable formulation: cross-sectional persistence

Section 3.2 leaves exactly one estimator standing. Instead of *"is trading day 47
good?"* — which is undefined — the question must be:

> **Does trading day 47 rank stocks consistently — and does that ranking persist
> out of sample?**

Measured as rank information coefficient: the Spearman correlation between the
signal's cross-sectional ranking and the subsequent return ranking, with
persistence tested as sign agreement across folds.

A persistent cross-sectional *ordering* is far harder to produce by chance than a
persistent average, because chance does not usually order four thousand things
the same way twice.

### 5.1 The unit of evidence is the date, not the stock-year

This is what the artifact in §3.2 was obscuring. **Each date yields one IC
observation, however many stocks it ranks.** Pooling stocks buys precision
*within* a date; it does not buy more dates. So the sample size is the number of
independent dates — and that is why the 21,000 "stock-years" figure was always a
mirage.

Measured 2026-08-18 on 656 stocks × 2,870 sessions:

| Quantity | Value |
|---|---|
| IC observations | 568 |
| sd of IC | 0.1190 |
| SE(mean IC) | 0.0050 |
| **MDE on mean IC** | **0.0140** |

*(Worked example only — 21-session momentum against 5-session forward returns.
The forward-return alignment in that probe was not audited, so the −0.0327 mean
IC it produced is not reported as a finding.)*

**The important part is the floor: ~0.014.** Real equity signal ICs typically run
0.02–0.05, so this estimator can see a genuine signal. That is more than can be
said for any other formulation considered in this plan, and it is the reason
Track S is worth building at all.

---

## 6. Track S1 — calendar patterns

Grid: 13 windows × 4 alignments × 202 indices and 4,200 stocks × 2 bases.

**The null is not 50%, and it moves.** The Indian market drifts upward, so the
probability that a window closes higher rises with window length purely from
drift. Measured by the predecessor: **0.461 at one day rising to 0.501 at ninety
days.** A scan scored against a flat 50% would manufacture thousands of false
discoveries at short windows and miss real ones at long. The null is measured by
rotation, 1,000 rotations for final runs.

Leap-day cells are excluded. Near-duplicate cells — adjacent windows whose
returns correlate above 0.90 — are grouped so that one effect is not counted
thirteen times.

Turn-of-month and turn-of-year are removed from consideration, by owner decision
Q43 and independently by arithmetic: **+129.70 bps gross against 136.06 bps of
cost is −6.36 bps net.**

---

## 7. Track S2 — signal combinations

**Owner decision, 2026-08-18: scan wide, explicitly to measure overfitting
rather than in the expectation of finding an edge.**

Seven families, roughly 190 base variants, crossed to depth 3 with thresholds.
The realised combination count is computed at run time and sets the bar; a test
greps for hard-coded literals so the count can never be stale.

| Family | Variants | Mechanism |
|---|---|---|
| momentum | ~40 | underreaction to news |
| reversal | ~30 | liquidity provision is paid |
| volatility | ~25 | risk compensation / low-vol anomaly |
| volume | ~25 | attention and participation |
| liquidity | ~20 | illiquidity premium |
| seasonal | ~30 | flow calendar effects |
| institutional | ~20 | Track D deal signals as inputs |

Every base signal requires a **written mechanism** before entering the pool. The
scan is deliberately wide; that is not a licence to include things nobody can
explain.

**The prior is explicit and unflattering.** V2 ran a strategy factory of exactly
this shape for five weeks and promoted **zero** strategies. That is the starting
expectation here, not a surprise to be explained away afterwards.

Track D's deal signals appear here as *inputs*. Track D remains a separate track
with its own verdicts — this is reuse, not a merger.

---

## 8. The multiplicity bar

The required standard rises only with the **logarithm** of scan width, so a wide
scan costs less than intuition suggests:

**Corrected 2026-08-18** after three errors were found in the estimator, all
pointing the anti-conservative way. See §8.1.

| Width | Noise max \|t\| (normal) | Bar (normal) | **Bar at df=20** |
|---|---|---|---|
| 5,000 | 3.87 | 4.84 | **5.93** |
| 3,146 | 3.75 | 4.68 | **5.73** |
| 1,000,000 | 4.98 | 6.23 | **8.60** |
| **31,893,556** | **5.63** | **7.04** | **11.27** |

A calendar cell scored on 21 yearly observations is t(20), not normal, so the
`df=20` column is the applicable one. For context, the predecessor's single best
pattern sat at the 94th percentile of rotated noise — nowhere near any of these.

### 8.1 Three errors in the estimator, all anti-conservative

The bar published a day earlier was **\|t\| ≥ 6.89**. It was wrong three ways,
and every one made results *easier* to pass:

1. **Sidedness.** The estimator computed the expected maximum of *signed*
   normals while `Bar.clears()` compares `abs(t)`. Measured at N=171: max(z) is
   2.693 but max\|z\| is 2.922. Every bar the module ever produced was low.
2. **Degrees of freedom.** Statistics are t-distributed, not normal, and 21
   yearly observations give t(20), whose tails are far fatter. Over 3,146 draws:
   normal 3.746 versus t(20) 4.599, **+23%**.
3. **Grid geometry.** Correlation between overlapping cells pulls the maximum
   *down* — measured 4.595 at ρ=0 falling to 3.071 at ρ=0.7 — partly cancelling
   effect 2. On a realistic simulated grid the truth was **4.151** against a
   dof-adjusted 4.60 and a normal 3.568.

**No formula gets a specific grid right.** Every Track S scan must therefore
generate its own grid under its own null and measure the maximum directly
(`multiplicity.simulated_max_null_t`). The table above is a planning guide, not
the operative bar.

---

## 9. Costs, and a verdict that did not exist before

Every surviving pattern is costed before being reported, using the corrected
schedule in `costs.yml`. The predecessor's headline seasonal finding was an
artefact of a fee model wrong by 10.04 bps per round trip.

A new verdict is introduced: **SIGNIFICANT_BUT_UNPROFITABLE** — statistically
real, economically negative. It is neither a pass nor a fail, and it was the true
status of both of V2's surviving seasonal effects.

---

## 10. Compute, measured rather than asserted

The predecessor's "~3 weeks" for a full rescan was an assertion; no single cell
was ever timed. The dual-fold design multiplies the work again.

**Before any full run**, a benchmark on 1/1000th of the grid must produce a
measured projection. If that projection exceeds the 21-day budget, the grid is
cut and the cut is recorded as a decision rather than absorbed silently.

---

## 10a. How Track S connects to Track D

Written 2026-08-18 after a check found the two tracks had never been wired
together. Three gaps, each of which would have surfaced only once scan code ran.
Full record: [decision 0023](../decisions/0023-trial-families-and-track-s-wiring.md).

### 10a.1 Trial families — who pays for which search

`research.yml` said the trial counter applied to **everything**. `scan.yml` said
nothing. Read literally, running Track S once would have done this:

| Counter state | Track D bar |
|---|---|
| today (171 trials) | 3.71 |
| after a 5,000-combination signal scan | 4.92 |
| after a 1M-cell calendar scan | 6.42 |
| after the full 31.9M rescan | **7.28** |

`exp_001`'s t = −3.93 would have **retroactively failed**, and no deal study could
ever have passed again. **Track S would have destroyed Track D as collateral
damage**, and nobody would have found out until the day a scan ran.

The counter is now hierarchical (`configs/trials.yml`). Four families:

| Family | Charges | dof | Carried |
|---|---|---|---|
| `TRACK_D_DEALS` | deal event studies | 246 | 171 |
| `TRACK_S_CALENDAR` | calendar cells | 20 | **31,893,556** |
| `TRACK_S_SIGNALS` | signal combinations | ~500 | 0 |
| `TRACK_S_PROCEDURE` | the procedure test | — | fixed at 3 |

`TRACK_S_CALENDAR` carries the predecessor's completed 31.9M-cell scan. **That
space is not virgin**, and a rebuild does not get to look at it as though for the
first time.

**The procedure exemption.** `TRACK_S_PROCEDURE` stays at a family size of 3 —
one per value of *N* — no matter how wide the scan. Exactly one procedure is
under test per configuration, and the 31.9M cells are the **instrument** that
measures it, not competing hypotheses. This is precisely what makes §4's "scan
wide to measure overfitting" a legitimate design rather than a loophole, and it
holds **only** while the reported claim is about the procedure. The moment a
specific surviving pattern is reported, that claim pays full width in
`TRACK_S_CALENDAR`.

**A project-level claim faces everything.** A within-family bar answers "is this
the best of the calendar cells". A claim that *the project* found something is a
selection across all four families and faces the summed bar. Both are always
reported — publishing only the friendlier one is exactly what the predecessor did
when it exempted its own champion.

**What stops family-splitting being a loophole is declaration order, not family
size.** Families are declared before the search and are immutable afterwards, and
a result may never be moved to a smaller family once seen.

### 10a.2 The Track S partition

`split.yml` partitions by ISIN, which is meaningless for a calendar cell — a cell
spans every stock at once. So Track S had **no exploration/confirmation regime at
all** while Track D sat behind a guard that raises.

| Split | Role | Boundary |
|---|---|---|
| **time** | **mandatory** | explore ≤ 2015-12-31, confirm ≥ 2016-01-01, 21-session embargo |
| index | corroborating only | 40 / 60 by hash of index name |

The time split is mandatory because it is **the only partition that tests
persistence**, which is what a pattern claim asserts. The index split is
explicitly weak and labelled as such: the 202 indices overlap heavily, since
NIFTY 50 constituents sit inside NIFTY 100, NIFTY 500 and most sector and
thematic indices, so an "explore" index and a "confirm" index can share most of
their members.

A cell must clear its bar under **both**, and observation floors apply per half.

### 10a.3 The design gate now covers scans

`StudyKind` gained `scan`, and five blocking confounds were added for it —
`multiple_testing_declared`, `null_is_measured_not_assumed`, `fold_independence`,
`bid_ask_bounce`, `prior_search_of_this_space`. Before then the gate applied to
Track D and left the half of the project with far worse multiple-testing exposure
with no required controls at all.

A scan must declare its family, its **nominal** fold count and its **effective**
fold count before registration. A single-fold scan is refused: one fold is an
in-sample fit, which is what the 31.9M atlas was.

### 10a.4 A fourth gap, found inside the fix

`trials.yml` declared the counters *monotonic* and *never reset* — and nothing
incremented them. `charge()` was a pure function and the project counter summed
static YAML, so a 31.9M-cell scan could have run without moving anything.

That is `exp_001`'s `trials_before` — computed, stored, printed once, never read
— **rebuilt one level up, inside the file whose subject is that exact failure.**
Fixed by migration `0002_trial_families`: an append-only `family_charge` ledger
whose triggers refuse UPDATE, DELETE, and any total that would decrease.

---

## 11. What has to be built

| Module | Purpose | Status |
|---|---|---|
| `src/scan/folds.py` | Anchored walk-forward + CPCV generation, purge/embargo | not built |
| `src/scan/nulls.py` | Measured rotation null | not built |
| `src/scan/calendar.py` | S1 cell enumeration and scoring | not built |
| `src/scan/signals.py` | S2 combination enumeration | not built |
| `src/scan/procedure.py` | The headline: hit rate, degradation, PBO, rank decay | not built |
| `src/scan/atlas.py` | Chunked resumable execution, checkpointing | not built |
| migration `0002` | `scan_cell`, `scan_fold_result`, `procedure_result` | not built |

Reused unchanged from Track D: `multiplicity.py`, `hashing.py`, `migrate.py`,
`paths.py`, the experiment registry and the decision-record discipline.

**Not reused:** `split.py` and `power.py`. Both are event-study machinery — the
name-based partition is meaningless for a calendar cell, and the monthly cohort
collapse does not apply to annual observations. Track S needs its own equivalents,
which is most of the build above.

---

## 12. Honest expectation

Stated in advance so it cannot be adjusted afterwards:

- **The procedure test most likely returns a hit rate near 50%**, meaning mass
  scanning does not work on this data. That is the primary expected finding and
  it is worth having.
- **Very few or no individual patterns will clear the simulated bar**, which on
  a realistic grid lands near \|t\| ≥ 5.2 and rises steeply with width. The
  predecessor's best cleared nothing close.
- **The calendar track is the weaker of the two.** It has been run before and
  returned nothing, and its per-stock form is arithmetically dead.
- **The signal track has better arithmetic** — signals fire many times a year, so
  walk-forward works natively — but its prior is a factory that promoted zero.

The value of Track S does not depend on finding an edge. It depends on producing
a defensible measurement of whether searching for one works at all, on twenty-one
years of real data, with the costs modelled correctly.

**That measurement does not currently exist anywhere in this project, and it is
the thing the 31.9M cells are actually good for.**
