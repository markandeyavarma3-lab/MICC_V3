# Institutional Research Platform — Plan 2 of 3: Research Methodology

**Companion to Plan 1 (Foundations) and Plan 3 (Execution)**
**Date:** 2026-08-16 · **Status:** Phase 0 deliverable — awaiting owner approval

<!--TOC-->

---

## 1. The problem this methodology exists to solve

The audit (Plan 1 §1.3) measured the owner's central hypothesis and it failed:
1-month and 3-month institutional signal is flat (*t* ≈ −0.8), and the 12-month
result is right-skew on survivors with a bootstrap CI spanning zero.

That result was produced by a fast exploratory pass. It is **not** the final
answer, because that pass had four defects this methodology fixes:

| Defect in the exploratory pass | Fixed by |
|---|---|
| 45% of events dropped on unresolved symbols and delistings | Identity layer (Plan 1 §6) + delisting-aware outcomes (§3) |
| Flat cost assumption | Advanced cost model (§4) |
| One benchmark, cap-weighted, unsuited to a small-cap-skewed event set | Six benchmarks incl. characteristic-matched (§5) |
| No correction for how many strata were examined | Multiple-testing framework (§6) |

Corrected, the number may go up or down. The methodology's job is to make it
*trustworthy*, not to make it positive.

---

## 2. Pre-registration — the non-negotiable

Owner decision Q44: every study, no exceptions. Q35: the outcome study itself is
pre-registered, and the fact that an exploratory version was already run is
disclosed.

### 2.1 `experiment_registry`

```sql
CREATE TABLE experiment_registry (
    experiment_id    TEXT PRIMARY KEY,
    engine_id        TEXT,                  -- NULL for pure research
    hypothesis       TEXT NOT NULL,
    prior_belief     TEXT NOT NULL,         -- what we expect, and why, BEFORE the fit
    created_at       TIMESTAMP NOT NULL,
    created_by       TEXT NOT NULL,

    data_version     TEXT NOT NULL,
    universe_definition TEXT NOT NULL,
    participant_definition TEXT,
    interpretation_mode TEXT,
    holding_period   TEXT NOT NULL,
    entry_policy     TEXT NOT NULL,
    exit_policy      TEXT NOT NULL,
    cost_policy      TEXT NOT NULL,
    benchmark_policy TEXT NOT NULL,

    training_period  TEXT NOT NULL,
    validation_period TEXT NOT NULL,
    final_test_period TEXT NOT NULL,

    search_space_definition TEXT NOT NULL,
    test_count       INTEGER NOT NULL,      -- declared BEFORE running
    multiple_testing_policy TEXT NOT NULL,
    permutation_policy TEXT NOT NULL,

    pass_bar         TEXT NOT NULL,         -- the number that means "real"
    kill_criteria    TEXT NOT NULL,         -- the number that means "dead"
    exploratory_prior_run TEXT,             -- Q35 honesty field

    spec_hash        TEXT NOT NULL,
    trials_before    INTEGER NOT NULL,      -- cumulative counter, Q47
    configuration_json TEXT NOT NULL,
    code_commit_hash TEXT NOT NULL,
    status           TEXT NOT NULL,
    decision_reason  TEXT
);
```

Statuses: `DRAFT → REGISTERED → RUNNING → {REJECTED | VALIDATED} → PAPER_TRIAL → PROMOTED → RETIRED`, plus `PAUSED`.

`spec_hash` covers hypothesis, features, universe, horizons, cost policy, pass
bar and kill criteria. **Changing any of them after seeing a result produces a
different hash and therefore a different experiment.** Amending an experiment
post-hoc is the failure mode this field exists to make impossible.

`exploratory_prior_run` is the Q35 field: the outcome study's registration will
say plainly that an exploratory version was run on 2026-08-16 and what it found.
A pre-registration that hides a prior look is not a pre-registration.

### 2.2 The trial counter (Q47)

Carried from MICCV2 at **N = 47 + 21 legacy = 68**, monotonically increasing,
never reset. Every registered experiment increments it, and the deflated-Sharpe
denominator uses the value at registration time.

**Applied to everything, incumbent included.** MICCV2's asymmetry — deflating
challengers while exempting the champion — was found in the audit and is the
exact self-deception the counter exists to prevent.

---

## 3. The outcome study

### 3.1 Event definition

```text
An EVENT is one (participant, security, side, trade_date) row from
institutional_deals_clean where eligible_for_research = TRUE.
```

Owner decision Q28: multiple same-day rows by one client are **separate**
events, not aggregated. Q27: `PROP_HFT` is excluded by default via
`eligible_for_research`, and every study reports its N both with and without,
because a 44%-of-data filter must be visible.

### 3.1a The EXPLORE / SELECT / CONFIRM partition

> **Live spec: [`configs/split.yml`](../../configs/split.yml).** Rationale:
> [decision 0008](../decisions/0008-three-way-split.md) and
> [0009](../decisions/0009-split-key-is-isin.md).

Pre-registration answers *"was the bar set before the result?"*. It does not
answer *"how many things did you look at before registering?"* — and on
2026-08-16 the answer was ~100 unregistered cells, which moved the trial counter
from 68 to 171. Under a single data pool that cost is permanent and global: every
future study's bar is higher forever because of one afternoon.

That is the wrong incentive. It makes examining your own data expensive, so you
examine it less, so you find less. **The fix is not to look less. It is to have
somewhere that looking is free.**

| stratum | share | charged? | may be touched by |
|---|---|---|---|
| `EXPLORE` | 30% | **no** | anything, unregistered, without limit |
| `SELECT` | 20% | yes | comparing candidates; registered, SELECT bar |
| `CONFIRM` | 50% | yes | one registered experiment, **once** |

Three strata rather than two, because *finding* a hypothesis and *choosing among
candidates* are different expenditures of freedom. MICCV2's champion was not
mined into existence — it was **selected** from a factory of candidates, and the
selection was never charged for. Full-sample Sharpe 1.52, trailing-24m 0.11.

**The key is the ISIN, never the symbol.** Measured against the seed: 276 ISINs
carry more than one symbol, 459 of those symbols appear in deal data, and they
account for **26,046 deal rows — 11.04% of the corpus**. `CADILAHC → ZYDUSLIFE`,
`PRISMCEM → PRSMJOHNSN`, `GEOJITBNPP → GEOJITFSL`. Keyed on the symbol, each of
those companies sits in one stratum under its old name and another under its new
one — contaminating the confirmation set by construction, with nothing in any
output looking wrong. Measured coverage: **87.6% of deal rows ISIN-keyed**, 12.4%
falling back to the symbol, against a 15% cap.

Assignment is `sha256(key) % 1000`, not a seeded shuffle. A seeded shuffle over a
symbol list reassigns *every* name whenever the list changes, and it changes with
every listing and delisting. A hash depends only on the identifier, so a new IPO
self-assigns and no existing name ever moves.

**What the partition does not give you.** It does *not* give independent samples.
Equities co-move through sector and market beta, so an effect discovered in
`EXPLORE` leaks into `CONFIRM` via common factors. The honest quantity is the
effective sample size under the standard design effect,
`n_eff = n / (1 + (n−1)·ρ̄)`. At ρ̄ = 0.20, 2,100 confirmation names are worth
about **five** independent observations. **Every MDE in this plan is computed as
if names were independent and is therefore optimistic** — reported alongside
power, not in a footnote.

Enforcement is `ConfirmationGuard`, which raises on any `CONFIRM` read outside a
registered experiment with a frozen spec, and caps each experiment at one touch.
A stratum read a hundred times by a hundred "single" tests is a single-pool
regime wearing a costume.

**Measured on the real corpus:** `CONFIRM` holds 122,994 deal rows across 1,930
names and 247 months. The partition passes its balance audit on names (within
0.3pp) and deal type (0.030), and **breaches on era** — 2006-11 came out 57.1%
`CONFIRM` against a 50% target, deviation 0.071 against a 0.05 limit. That is
recorded as a limitation and **not re-drawn**: re-drawing until a split looks
balanced is p-hacking the split itself
([decision 0016](../decisions/0016-era-balance-breach-accepted.md)).

Seasonality gets a different partition entirely — a time split *and* an index
split, both of which a cell must survive. See §7 and
[decision 0012](../decisions/0012-seasonality-dual-split.md).

### 3.2 Timing

```text
trade_date T
   └─ disclosure published (measured, not assumed) → available_from
        └─ first session strictly after available_from → entry_date
             └─ entry at that session's OPEN
                  └─ exit at horizon, or on delisting/merger
```

No same-day close entry unless publication before that close is *proven* by the
measured `available_from`. Where it cannot be proven for a historical period,
the conservative bound is used and the row is flagged.

### 3.3 Horizons (Q29) — REVISED 2026-08-16

> **Live values: [`configs/research.yml`](../../configs/research.yml)
> `horizons_sessions` / `horizons_months`. This section explains them; the config
> defines them.** See [decision 0004](../decisions/0004-horizons-in-sessions-not-months.md).

**Primary: 1, 2, 3, 5, 10, 21 trading sessions.** Headline reporting is
1/3/5/10 sessions. **Robustness only: 3, 6, 12 months.**

This replaces the original 1/3/6/8/10/12/15/18/24-month grid, which the owner had
asked to extend. Measured power is why:

| aggregation | observations | MDE @ 80% power |
|---|---|---|
| monthly cohorts | 247 | 1.52% |
| **daily cohorts** | **~3,345** | **0.163%** |

A 9× improvement in detectable effect from the choice of aggregation alone. And
the only real effect found on 2026-08-16 sat at **10 sessions** — the original
grid would have missed it entirely, because its finest resolution was a month.

The 8/10/15/18/24-month horizons are dropped rather than demoted. At 12 months MDE
is already 7.38% against a plausible bound of 0.50%; anything longer is strictly
more hopeless, and each one spends multiple-testing budget to guarantee an
`UNDERPOWERED` row.

Every horizon is measured in *trading sessions* from the calendar, never
calendar-day arithmetic.

### 3.4 Delisting and merger handling (Q32)

The owner chose to use delisted stocks in the analysis rather than drop them.
Four cases, priced separately, and the aggregate reported under each:

| `exit_reason` | Treatment |
|---|---|
| `HORIZON` | Normal exit at the horizon session's open |
| `MERGED` | Roll into `merged_into_id` at the exchange ratio, continue the horizon |
| `DELISTED` | Exit at last traded price × recovery factor |
| `SUSPENDED` | Mark at last traded price, flagged, excluded from the headline |

**Owner decision: report all three recovery factors, headline at 0.0.**

| Recovery factor | Meaning | Role |
|---|---|---|
| **0.0** | Total loss on delisting | **Headline** — conservative |
| 0.25 | Partial recovery | Sensitivity |
| 0.50 | Substantial recovery | Sensitivity |

This is the single most consequential assumption in the study — **6,574 of
30,771 events hit it**. A single number would hide a load-bearing choice, so all
three appear in every table and the headline states which it used. MICCV2's
silent drop of these events was worth roughly the whole measured effect.

### 3.5 Excursions

`max_adverse_excursion` (MAE) is the worst the position went during the holding
window; `max_favorable_excursion` (MFE) is the best. They matter because a path
nobody could actually hold is not a strategy:

```
Path A:  +2% … +8% … +14% … +20%      never below entry
Path B:  -41% … -22% … +5% … +20%     down 41% first
```

Both end +20%. Only one is holdable.

**Owner decision: intraday high/low as the primary basis, with the close-based
figure reported alongside.** Intraday is the true worst tick and what a stop
would have hit; understating drawdown is the more dangerous error. The close-based
number is what a daily-monitoring holder would have seen, and the gap between
them is itself informative about how violent the path was.

`excursion_basis` on each outcome row records which produced the stored value,
and both are always populated.

---

## 4. The advanced cost model (Q34)

The owner is right that MICCV2's model is too crude. It applies a flat slippage
by liquidity tier — 0.15% / 0.40% / 0.80% per side — which is a constant where
reality is a function of order size, volatility, and the stock's own spread.

The fee side of MICCV2's model is *exact* and is kept unchanged. Only the
market-friction side is replaced.

### 4.1 Layer 1 — statutory and brokerage costs

**MICCV2's fee layer was wrong in three places, and the errors compound.**
Found during the 2026-08-16 external review and verified against the live
published rate card. This layer is therefore **rebuilt, not ported.**

| Component | MICCV2 | Actual (verified) | Error |
|---|---|---|---|
| STT (delivery) | 0.10% **sell only** | **0.10% on BOTH buy and sell** | Under-charged 10 bps per round trip |
| Exchange transaction | 0.00345%, one rate | **NSE 0.00307% · BSE 0.00375%** | Wrong value, and no exchange distinction |
| GST | 18% of **brokerage** | 18% of **(brokerage + SEBI + transaction)** | Under-charged |
| SEBI turnover | ₹10/crore | ₹10/crore | ✅ correct |
| Stamp duty | 0.015% buy | 0.015% (₹1500/crore) buy | ✅ correct |

Recomputed, at a conservative 0.03% brokerage:

```
                        BUY bps   SELL bps   ROUND TRIP
MICCV2 (as shipped)        5.39      13.90        19.29
CORRECTED  NSE            15.41      13.91        29.33
CORRECTED  BSE            15.49      13.99        29.49
  (NSE, zero brokerage)   11.87      10.37        22.25

UNDER-CHARGE: +10.04 bps per round trip
```

**Consequence — a published MICCV2 finding does not survive.** Turn-of-month was
reported as the seasonality effect that cleared costs:

| | per occurrence |
|---|---|
| Gross edge | +129.70 bps |
| MICCV2 cost model (126 bps) | **+3.70 bps** — reported as surviving |
| Corrected (136.06 bps) | **−6.36 bps** — **sign flips, effect dies** |

This is precisely why Q43 (remove turn-of-month and turn-of-year from
consideration) was the right call, and it is now supported by arithmetic rather
than by judgement.

### 4.1.1 The fee schedule is versioned, not constant

Rates change. NSE cut cash-segment transaction charges to ₹2.97 per lakh
effective 1 October 2024 under SEBI's true-to-label circular, and revised the
IPFT component again effective 1 March 2026. STT and stamp duty have both moved
inside the 2006–2026 sample. **A single constant is wrong for nearly every
historical year, not merely the current one.**

```sql
CREATE TABLE fee_schedule (
    fee_id           BIGINT PRIMARY KEY,
    component        TEXT NOT NULL,     -- STT|TXN|SEBI|GST|STAMP|BROKERAGE
    segment          TEXT NOT NULL,     -- EQ_DELIVERY|EQ_INTRADAY
    exchange         TEXT,              -- NSE|BSE|NULL where uniform
    side             TEXT NOT NULL,     -- BUY|SELL|BOTH
    rate             REAL NOT NULL,
    rate_basis       TEXT NOT NULL,     -- PCT_TURNOVER|PER_CRORE|PCT_OF_BASE
    applies_to_base  TEXT,              -- for GST: the components it taxes
    effective_from   DATE NOT NULL,
    effective_to     DATE,
    source_url       TEXT NOT NULL,
    source_note      TEXT NOT NULL,
    verified         BOOLEAN NOT NULL,  -- FALSE until a circular is cited
    verified_at      TIMESTAMP
);
```

Every cost calculation joins on `trade_date BETWEEN effective_from AND
effective_to`. Rows carry `verified=FALSE` until a primary source is attached,
and **any study whose window touches an unverified row says so in its output.**
Owner decision: rates sourced from published broker rate cards and exchange
circulars, never from memory.

*Sources for the current schedule:* [Zerodha charges](https://zerodha.com/charges/) ·
[NSE transaction-charge circular](https://nsearchives.nseindia.com/content/circulars/FA73061.pdf)

**Brokerage caveat.** Zerodha charges **zero** brokerage on equity delivery. The
default 0.03% is therefore *deliberately conservative* — it models a mid-tier
broker rather than the cheapest available. Reported alongside a zero-brokerage
scenario (22.25 bps round trip) so the reader sees both bounds.

### 4.2 Layer 2 — bid-ask spread, estimated from the data

MICCV2 had no spread estimate at all. Intraday quotes are not held, but the
spread is recoverable from daily OHLC using two published estimators:

**Corwin–Schultz (2012) high–low spread estimator.** Uses the insight that the
high–low range over two days reflects both volatility and spread, and the two
scale differently with the observation interval:

```
β = E[(ln(H_t/L_t))² + (ln(H_{t+1}/L_{t+1}))²]
γ = (ln(H_{t,t+1}/L_{t,t+1}))²
α = (√(2β) − √β)/(3 − 2√2) − √(γ/(3 − 2√2))
S = 2(e^α − 1)/(1 + e^α)
```

**Abdi–Ranaldo (2017) close–high–low estimator** as a cross-check; it is less
biased in low-volume names, which matters because event stocks skew small.

**Implementation requirements**, all of which are places these estimators are
commonly got wrong:

- **Log prices throughout.** The `β`/`γ`/`α` terms are defined on log ranges;
  mixing arithmetic returns in silently biases the estimate.
- **Zero and negative ranges.** A session where `H == L` (circuit-locked, common
  in Indian small caps) gives `ln(H/L) = 0` and must be excluded, not treated as
  a zero spread. Sessions with missing high/low are excluded, not forward-filled.
- **Negative spread estimates set to zero**, per Corwin–Schultz's own
  recommendation — the estimator is unbiased in expectation but noisy per
  observation.
- **Winsorisation at the 15% tails** of the rolling distribution before use.
- **Overnight adjustment.** Where a session gaps through the prior close, the
  two-day range is adjusted per the paper's overnight-return correction.

**Both estimates and their ratio are stored**, not just the chosen one:

```sql
spread_estimates(symbol, date, cs_spread, ar_spread, ratio,
                 chosen_spread, chosen_method, n_valid_sessions, flagged)
```

Where the two disagree by more than 2×, the wider is used and `flagged=TRUE`.
Storing both makes "where and why do these diverge?" a question the warehouse
can answer later — likely by liquidity tier and volatility regime — rather than
a decision buried in code.

### 4.3 Layer 3 — market impact, square-root law

The empirically robust form across markets:

```
impact = Y · σ_daily · √(Q / ADV)
```

where `Q` is order quantity, `ADV` is average daily volume, `σ_daily` is
trailing return volatility, and `Y` is a dimensionless constant in the 0.5–1.0
range. Default `Y = 0.8`, with sensitivity reported at 0.5 and 1.0.

**The window lengths are arbitrary and are therefore configuration, not
constants.** The literature uses a range — ADV over 5, 20, 21, or 60 sessions;
volatility over 20, 21, or 60 — and no choice is canonical.

```yaml
impact:
  adv_window_sessions: 20      # alternates tested: 5, 60
  vol_window_sessions: 21      # alternates tested: 60
  y_constant: 0.8              # alternates tested: 0.5, 1.0
```

Each headline result is re-run at the alternates and the spread across them is
reported. If a finding depends on whether ADV is measured over 20 sessions or
60, that is itself the finding.

This is the layer that makes the difference for the event study. Institutional
deals are, by the 0.5%-of-volume disclosure threshold, **large relative to ADV
by construction** — so a flat 0.15% slippage for a large-cap systematically
understates the cost of trading alongside them. The square-root form is why.

### 4.4 Layer 4 — participation constraint

A position cannot be established instantly. Cap participation at a fraction of
ADV per session; an order larger than that is spread over consecutive sessions,
each leg priced at its own open with its own impact, and the resulting **delay
cost** is charged. Where the position cannot be built inside 5 sessions, the
event is marked `TOO_LARGE` and excluded with the reason recorded.

**Two caps, both reported.** 10% of ADV is the common default, but institutional
execution studies use nearer 5% for small caps — and this event set skews small
by construction, since the 0.5%-of-volume disclosure threshold is easiest to
cross in thin names.

| Scenario | Cap | Role |
|---|---|---|
| Base | 10% ADV | Headline |
| Conservative | 5% ADV | Sensitivity, and the primary figure for the smallest liquidity tier |

### 4.5 Layer 5 — regime conditioning

Spreads and impact widen in stress. `σ_daily` already carries part of this; the
model additionally scales impact by a volatility-regime multiplier derived from
India VIX relative to its trailing 252-session median (1.0 in calm, up to 1.5 in
the top decile).

### 4.6 Reporting

Every result is reported at three cost levels — **gross**, **base model**, and
**pessimistic** (Y=1.0, wider spread estimate, 5% participation cap) — so the
reader can see how much of any effect survives friction. The seasonality work in
MICCV2 already demonstrated why this matters: turn-of-month's entire +1.297%
edge sat against a 1.26% round-trip cost, leaving +0.037%. The economics died
where the statistics lived.

---

## 5. Benchmarks (Q30)

The owner asked for at least five, including large-cap, mid-cap and small-cap.

### 5.1 The set

| ID | Series | Coverage | Role |
|---|---|---|---|
| `NIFTY50_TR` | NIFTY 50 + dividends | 2007-2026 | Large cap |
| `NIFTY500_TR` | Cap-weighted ^CRSLDX + div (already built) | 2011-2026 | Broad market, headline |
| `NIFTY_MIDCAP100` | NIFTY MIDCAP 100 | 2005-2026 | Mid cap |
| `SMALLCAP_SYNTH` | **Constructed — see §5.2** | 2005-2026 | Small cap |
| `EW_TOP500` | Equal-weighted top-500 | 2005-2026 | The no-skill portfolio |
| `CHAR_MATCHED` | Characteristic-matched — **see §5.3** | 2005-2026 | The academically correct one |

### 5.2 The smallcap gap, and how it is closed

`NIFTY Smallcap 100` exists in the warehouse with **15 rows** (2026-06-17 →
2026-07-08). There is no small-cap benchmark history, and this is a real gap the
owner should know about.

**Solution:** construct one from the price spine. At each month-end, rank the
point-in-time universe by 20-day median turnover, take ranks 251–500, weight by
free-float-proxy market cap, hold for one month, chain the series. This is
reproducible, point-in-time, delisting-aware, and documented as *constructed,
not official*. Every result using it says so.

### 5.3 The characteristic-matched benchmark — the one that matters most

Simple index-relative returns are the wrong comparison for an event study whose
events skew toward small, volatile, recently-moving stocks. If institutional
deals cluster in small caps and small caps outperform, an index-relative measure
credits the institutions with beta they did not create.

**DGTW-style matching (Daniel, Grinblatt, Titman, Wermers 1997), adapted to the
data that actually exists.**

The original method sorts on size × book-to-market × momentum. **Book-to-market
is not available here.** Verified during the review: `annual_balance` and
`quarterly_balance` store a JSON blob that *does* contain `Stockholders Equity`
and `Tangible Book Value`, but coverage begins at **28 symbols in 2021 and
~2,200 from 2022 onward**. For 2006–2021 — sixteen of the twenty years — there
is no stock-level book value at all. `index_valuation.pb` is index-level and
cannot match individual stocks.

**Primary construction (owner decision): size × momentum × volatility ×
industry.** All four are computable from the price spine and the PIT sector
history over the full 2005–2026 span.

| Dimension | Measure | Buckets |
|---|---|---|
| Size | market cap proxy = price × shares, or 20-session median turnover where shares unavailable | 5 |
| Momentum | 12-1 month return | 5 |
| Volatility | trailing 21-session return σ | 5 |
| Industry | PIT sector (`sector_history`) | grouped to ~10 |

Sorted independently, then intersected. Each event stock is matched to the
equal-weighted return of its own cell; abnormal return is the event's return
minus its cell's.

**Thin-cell guard.** 5×5×5×10 is 1,250 cells and many will be sparse in early
years. Where a cell holds fewer than 10 names at the matching date, the industry
dimension is dropped first, then volatility, and the fallback level used is
**recorded per event** so the reader can see how often the full match was
achievable. A silently-degraded match is worse than a declared one.

**BTM as a 2022+ sensitivity only**, clearly labelled, never in the headline.

**This is the primary outcome measure for participant skill** — not
index-relative returns. Index-relative credits an institution with small-cap and
momentum beta it did not create, and this event set is skewed toward exactly
those characteristics. Where the two disagree, the characteristic-matched number
is the one reported as the finding.

### 5.4 Reporting rule

Every outcome row carries a return against **all six**. No result is reported
against a single benchmark. Where they disagree, the disagreement is the finding.

---

## 6. Statistical framework

### 6.1 The overlap problem

With 12- to 24-month horizons and events clustered in time, observations are
massively overlapping and cross-sectionally correlated. The audit demonstrated
the scale of the distortion: naive *t* = **11.61**, monthly-cohort *t* = **3.61**,
bootstrap CI spanning zero. **A naive standard error on this data overstates
significance by roughly 3×.**

Three defences, all applied:

1. **Cohort collapse.** Aggregate events to equal-weighted monthly cohorts before
   any inference. This is the primary estimator.
2. **Moving-block bootstrap.** Blocks of length ≥ the horizon, 10,000 draws,
   preserving serial dependence. Reports a CI, not just a *p*.
3. **Newey–West HAC** with lag = horizon, as a cross-check.

Where the three disagree, the most conservative is reported as the headline.

### 6.2 Multiple-testing correction — better than BY/BH (Q37)

The owner asked whether there is something better. There is, and the right answer
depends on what is being controlled.

| Method | Controls | Where used | Why |
|---|---|---|---|
| **Benjamini–Yekutieli** | FDR under arbitrary dependence | Seasonality atlas | Conservative but valid when overlapping windows break independence in both directions |
| **Benjamini–Hochberg** | FDR under positive dependence | Reported alongside BY | Q37 asked for both; the gap between them is informative |
| **Storey q-value** | FDR, adaptive | Both families | Estimates π₀ (the true null fraction) instead of assuming 1, so it is strictly more powerful than BH when many nulls are true — which is the case here |
| **Romano–Wolf stepdown** | FWER, bootstrap-based | **Participant / stratum ranking** | The genuinely better model for §6.3. Handles arbitrary dependence via bootstrap, far more powerful than Bonferroni or Holm |
| **Hansen SPA** | Best-of-family superiority | Seasonality "is the best cell real?" | Studentised, and strictly less conservative than White's Reality Check, which MICCV2 used |

**The upgrade over MICCV2 is Romano–Wolf and Hansen SPA.** MICCV2 used White's
Reality Check; Hansen (2005) showed RC loses power when the family contains many
poor candidates — precisely the seasonality case with 31.9M cells. And MICCV2 had
*nothing* for participant ranking, which §6.3 fixes.

**SPA implementation requirements.** It is not a max-*t* bootstrap with a
different name. The implementation must use Hansen's **studentised** statistic
(each candidate scaled by its own bootstrap standard error, which is what stops
a high-variance candidate dominating the max) and the **sample-dependent null**
— the recentring rule that discards candidates too far below zero to plausibly
be best. Both `SPA_l`, `SPA_c` and `SPA_u` bounds are reported; `SPA_c` is the
decision rule.

**White's Reality Check is retained alongside SPA**, not replaced. MICCV2's
result was produced with RC, and reporting both makes the rebuild directly
comparable to it. Where RC and SPA disagree, that gap is itself informative
about how many poor candidates the family contains.

### 6.3 Participant ranking — closing the plan's blind spot

The original plan's §12 selects participants with no correction. With 27,417
names and the most active having 268 deals, "the best participant" is a
maximum-of-many statistic and will look impressive under any naive test.

**Procedure, fixed before any leaderboard is computed:**

```text
1. Eligibility:  participant needs >= 30 matured events at the horizon
                 -> reduces 27,417 names to a few hundred
2. Declare N  =  the exact number of eligible participants tested; stored in
                 experiment_registry.test_count BEFORE running
3. Statistic  =  monthly-cohort mean abnormal return vs CHAR_MATCHED
4. Romano-Wolf stepdown over all N, bootstrap 10,000, preserving the
   cross-sectional and serial dependence structure by resampling whole months
5. Report the FWER-adjusted p for every participant, not only the winners
6. A participant is "supported" only at adjusted p < 0.05
```

And the null-calibration check that makes it honest: **run the identical
procedure on randomly-relabelled participants** (permute the participant column
within date). If the real data yields a similar number of "supported"
participants as the shuffled data, there is no participant skill in this dataset —
only variance. That comparison is the headline finding, not the leaderboard.

### 6.4 Walk-forward design (Q39) — "think big", done properly

The owner proposed six anchored windows (2005→2010 test 2010–2015, etc.) and
asked for something bigger. More windows is not the upgrade; **more independent
backtest paths** is. Three schemes run together:

**Scheme A — anchored expanding (the owner's design, kept).** Train 2005→T,
test T→T+5, for T ∈ {2010, 2012, 2014, 2016, 2018, 2020}. Six paths. Tests
whether an effect estimated on all history survives forward. Intuitive and
reportable.

**Scheme B — rolling fixed-width.** Train on an 8-year window, test the next 3,
stepped annually. ~11 paths. Tests regime adaptation — whether an effect
estimated on *recent* history survives, which the anchored scheme cannot see
because early data dominates.

**Scheme C — Combinatorial Purged Cross-Validation (López de Prado).** This is
the "think big" answer. Partition the timeline into *N* contiguous groups, then
use every combination of *k* = 2 groups as a test set — C(N,2) backtest paths
instead of one ordering of time. Each path trains on the remaining N−2 groups,
with:

- **Purging** — training observations whose label window overlaps any test
  observation are removed. Essential here: a 24-month horizon means an event in
  month *t* carries a label reaching to *t+24*, which without purging leaks
  straight into a test fold.
- **Embargo** — an additional gap (default 1 month) after each test group,
  because serial correlation leaks across the boundary even without label overlap.

**N must vary with the horizon, and this corrects an error in the first draft
of this plan.** The draft specified a fixed N=12 (66 paths). Checked against the
data, that is unusable at long horizons:

```
deal data span = 20.6 years
N = 12  ->  20.6 months per group
a 24-month label purges MORE THAN AN ENTIRE ADJACENT GROUP
```

The constraint is that group length must be at least ~2× the label horizon, or
purging destroys the training set. Corrected schedule:

| Horizon | N | Group length | Paths C(N,2) |
|---|---:|---:|---:|
| ≤ 3 months | 20 | 12.4 mo | **190** |
| ≤ 6 months | 16 | 15.4 mo | **120** |
| ≤ 12 months | 10 | 24.7 mo | **45** |
| ≤ 24 months | 6 | 41.2 mo | **15** |

At 24 months, 15 paths is thin for a stable PBO estimate; that horizon's PBO is
reported with an explicit low-confidence marker, and the anchored and rolling
schemes carry more of the weight there.

**Probability of Backtest Overfitting (PBO), CSCV formulation.** Across the
paths, split each into in-sample and out-of-sample halves, rank the candidate
configurations in each, and compute the **logit-transformed relative rank λ** of
the in-sample winner within the out-of-sample distribution. PBO is the
probability mass of λ below zero — i.e. how often the in-sample best lands below
the out-of-sample median. **PBO > 0.5 means the selection process is worse than
random and the result is an artefact.**

MICCV2 never computed this and could not have: it ran exactly one path.

| Scheme | Paths | Answers |
|---|---:|---|
| A — anchored | 6 | Does an all-history estimate survive forward? |
| B — rolling | 11 | Does a recent-history estimate survive forward? |
| C — CPCV | **15–190**, horizon-dependent | What is the *distribution* of outcomes, and is selection overfitting? |

All three are reported. A result that passes A but fails C's PBO test is a
result that got lucky in one ordering of time.

### 6.5 Power analysis — before the fit, not after

For each planned stratum, the minimum detectable effect at 80% power is computed
**before** running, from the observed N and return dispersion. Strata that cannot
detect an economically meaningful effect are marked `UNDERPOWERED` and reported
as *silence*, not as a negative result.

This is the discipline MICCV2's exp_002 got right and it is the difference
between "fundamentals do not work" and "we could not tell". With 80 buys for
SBI Mutual Fund at a 12-month horizon, the honest answer is almost certainly the
latter, and the study should say so in advance.

### 6.6 The two gates — an event study is not a strategy test

> **Live spec: [`configs/research.yml`](../../configs/research.yml)
> `portfolio_gate`.** Rationale:
> [decision 0003](../decisions/0003-portfolio-gate-required.md).

Everything above §6.5 measures whether an *event* moves prices. None of it
measures whether a *book* can be built on that. Those are different questions and
the gap between them is not a detail — it is where this project's first result
died.

**Both gates are mandatory. Clearing the event gate alone is not a result.**

| gate | passes when |
|---|---|
| **event** | abnormal return significant vs the matched control, after correction, with MDE below the plausible bound |
| **portfolio** | a constructed book applying the signal beats the identical book without it, net of real costs on the *incremental* turnover, with a paired block-bootstrap CI excluding zero |

Construction is deliberately dumb: point-in-time top-500, **equal weight**,
month-end rebalance, minimum 30 names, paired difference against the same book
unfiltered so market and style exposure cancel. No optimiser — an optimiser is a
second signal, and a second signal is a second thing to overfit.

#### Why this section exists

`exp_001` produced a **real** event effect. It survived a random-stock control
(−0.860% event-specific), a volatility-matched control (**−0.805% at t = −3.93**),
and a momentum-reversal check (correlation +0.008, quintiles U-shaped rather than
monotonic). Every statistic pointed the same way and every one of them was
correct.

Its portfolio effect was **−0.022%/yr at t = −0.25.**

The gap is entirely dilution: the filter touched **1.2% of names.** Roughly 302
qualifying events a year across a 500-name universe, each tainting one name for 10
sessions, is about six names at any moment. A −0.8% effect on 1.2% of a book is
about one basis point a month.

Under the original plan, portfolio construction lived in Room 5, which was out of
scope — so nothing could legitimately reach Room 5, and every gate that existed
was an event-study gate. **`exp_001` would have been recorded as a PASS and
shipped as a finding.**

Consequently the **dilution factor is computed at design time**, before
registration, not discovered afterwards. Had it been, `exp_001`'s expected
portfolio impact would have been visible as ~1 bp/month and the study would have
been redesigned rather than run. Every study reports
`report_fraction_of_book_affected`.

---

## 7. Seasonality — rebuild and validation layer

Per Q42 the atlas is **rebuilt from scratch** with new code. Per Q43 the two
surviving effects (turn-of-month +0.45%/yr, turn-of-year +2.11%/yr) are
**removed** from consideration as strategy candidates.

### 7.1 What is rebuilt identically

13 windows (1,2,3,5,7,10,14,20,30,45,60,75,90) · 4 alignment schemes
(TRADING_DAY_OF_YEAR, CALENDAR_DATE, TRADING_DAY_OF_MONTH_START,
TRADING_DAY_OF_MONTH_END) · 2 return bases (PRICE, MARKET_RELATIVE) · stocks +
indices + pooled top-500 · window-specific measured base rates.

### 7.2 What changes

| Change | Owner decision |
|---|---|
| Minimum observations: **≥10 yearly, ≥30 monthly** alignments | Q41 |
| Index expansion 46 → ~202, with dedup and history-eligibility | Q40 |
| Near-duplicate grouping, incl. return-series correlation > 0.9 | Q36 |
| Permutation runs: **1,000** (300 for iteration) | Q38 |
| Correction: BY + BH + Storey q, and Hansen SPA for best-of-family | Q37 |
| Time-based OOS via the §6.4 three-scheme design | Q39 |

### 7.3 `seasonality_cell`

```sql
CREATE TABLE seasonality_cell (
    seasonality_cell_id BIGINT PRIMARY KEY,
    atlas_version    TEXT NOT NULL,
    entity_id        TEXT NOT NULL,
    entity_type      TEXT NOT NULL,        -- STOCK|INDEX|POOLED
    window_days      INTEGER NOT NULL,
    alignment_scheme TEXT NOT NULL,
    calendar_position TEXT NOT NULL,
    return_basis     TEXT NOT NULL,

    observation_count INTEGER NOT NULL,
    positive_count   INTEGER NOT NULL,
    positive_rate    REAL NOT NULL,
    mean_return      REAL NOT NULL,
    median_return    REAL NOT NULL,
    baseline_positive_rate REAL NOT NULL,   -- window-specific, measured
    baseline_return  REAL NOT NULL,
    relative_edge    REAL NOT NULL,

    raw_p_value      REAL NOT NULL,
    corrected_p_value REAL,
    correction_method TEXT,
    permutation_p_value REAL,
    spa_p_value      REAL,

    near_duplicate_group_id BIGINT,
    group_member_count INTEGER,
    out_of_sample_status TEXT,              -- UNTESTED|PASS|FAIL
    cost_adjusted_status TEXT,              -- SURVIVES|DIES_ON_COSTS
    eligibility_status TEXT NOT NULL,       -- ELIGIBLE|TOO_FEW_OBS|DUPLICATE_ENTITY
    n_tests_in_run   BIGINT NOT NULL        -- the actual count, never hard-coded
);
```

### 7.4 The promotion gate

```text
candidate cell
  → observation minimum (>=10 yearly / >=30 monthly)
  → window-specific baseline comparison
  → BY + BH + Storey correction over the ACTUAL run test count
  → near-duplicate grouping (adjacency + return-correlation > 0.9)
  → permutation test, 1,000 circular rotations
  → Hansen SPA on the best of family
  → three-scheme out-of-sample (§6.4)
  → full cost model (§4) at three levels
  → only then: a research candidate
```

**Expected yield: close to zero.** The prior atlas found 1,579,659 "significant"
cells against 1,497,584 expected by chance — a ratio of 1.05 — and its best
NIFTY50 pattern sat at the 94th percentile of randomly rotated data. The
rebuild is worth doing because the *validation layer becomes reusable
infrastructure* for every future scan, not because the answer is expected to
change.

---

## 8. Provenance — better than a hash chain (Q46)

The owner asked for something better than MICCV2's linear hash-chained idea
ledger. A linear chain proves *that nothing was altered*. It does not prove
*what produced what* — so it cannot answer the question that matters when a
result is challenged: "which data and which code produced this number, and can
it be re-derived?"

### 8.1 A content-addressed provenance DAG

Every artefact — a source file, a parsed table, a feature set, a benchmark
series, a study result — gets a **content hash**. Every artefact records the
hashes of its inputs. The result is a directed acyclic graph in which any node's
full lineage is reachable.

```sql
CREATE TABLE artefact (
    artefact_hash    TEXT PRIMARY KEY,      -- SHA-256 of content
    artefact_type    TEXT NOT NULL,         -- SOURCE|TABLE|FEATURE|RESULT|FIGURE
    logical_name     TEXT NOT NULL,
    produced_by      TEXT NOT NULL,         -- module:function
    code_commit      TEXT NOT NULL,
    produced_at      TIMESTAMP NOT NULL,
    row_count        BIGINT,
    byte_size        BIGINT,
    params_json      TEXT NOT NULL
);

CREATE TABLE artefact_edge (
    child_hash       TEXT NOT NULL REFERENCES artefact,
    parent_hash      TEXT NOT NULL REFERENCES artefact,
    edge_role        TEXT NOT NULL,
    PRIMARY KEY (child_hash, parent_hash)
);
```

### 8.2 What this buys over a hash chain

| Question | Hash chain | Provenance DAG |
|---|---|---|
| Was the record altered? | ✅ | ✅ |
| What produced this number? | ❌ | ✅ full lineage |
| Can I re-derive it exactly? | ❌ | ✅ inputs are content-addressed |
| Which results are invalidated if a source is restated? | ❌ | ✅ walk the DAG downward |
| Did two results use the same data version? | ❌ | ✅ compare input hashes |

The fourth row is the operationally valuable one. When NSE restates a bulk-deal
file (Plan 1 §5.4), the DAG identifies **exactly which published results depend
on it**, rather than leaving the question open.

### 8.3 Tamper evidence retained

The append-only property is kept: `artefact` and `artefact_edge` carry SQLite
triggers refusing UPDATE and DELETE — the mechanism MICCV2 uses, which the audit
verified genuinely works. Additionally, a daily **Merkle root** over all artefact
hashes is written to an append-only log, so the whole graph has a single
verifiable fingerprint per day.

---

## 9. Room 6 — monitoring and pause logic

Research-scope in v1 (no engines to pause), but the data-quality gates run from
day one.

### 9.1 Gates that block downstream work

| Gate | Trip condition | Action |
|---|---|---|
| Source missing | expected report absent > 1 session | ALERT, mark date incomplete |
| Parse failure | `ingestion_status != OK` | ALERT, archive bytes, block that date's mart build |
| Hash change | new hash for an existing date | Record revision, flag dependent results via DAG |
| Symbol resolution | unresolved rate > 5% in a month | BLOCK the outcome study for that period |
| Participant backlog | > 50 unreviewed names with ≥6 deals | WARN |
| Duplicate spike | duplicate rate > 2× trailing median | WARN |
| Calendar | session count outside 18–25 in a month | WARN |
| Cost anomaly | modelled spread > 3× trailing median | WARN |

**Symbol resolution is the one that blocks rather than warns**, because it is the
gate that separates a biased study from an unbiased one — the defect that cost
45% of events in the exploratory pass.

### 9.2 Verification, done right this time

Learning from audit defects 1–3 (Plan 1 §1.2):

- Verification is **strictly read-only**. It never rebuilds anything.
- Readers and verifiers use `data/snapshots/`, never the live DB file.
- Dashboard availability is tested **while a writer lock is held**.
- The environment is explicit; unset fails loudly.
- Every verification claim names the table and row count it re-derived from raw.

---

## 10. Honest expectation

Set out plainly so it cannot read as a surprise at Phase 6.

**Most likely outcome:** another rigorous negative result. The 1-month and
3-month institutional signal is already flat at *t* ≈ −0.8. The 12-month result
is right-skew whose CI spans zero, and three of this methodology's four fixes —
delisting-aware exits, the advanced cost model, and the characteristic-matched
benchmark — push the estimate **down**, not up. Only the identity fix could push
it up, by recovering 7,354 events.

**What would change the picture:** block deals (0.7% round-trip, genuinely
institutional, 12,430 events) have never been studied separately. Institutional
*selling* has never been studied at all. Consensus — multiple independent
institutions buying the same name in a window — is far better powered than
single-participant skill. Those three are where the residual probability lives,
and the study design covers all three.

**What this platform is worth even if the answer is no.** A system that can
prove an idea is dead, with pre-registration, correction for how many times it
looked, a cost model that survives scrutiny, and a provenance graph that lets
anyone re-derive the number, is a more credible piece of work than one that
reports a positive result nobody can check. That is the deliverable.

---

*Continues in **Plan 3 — Execution**.*
