# VERDICT: DEAD — binding constraint: SAMPLE SIZE

**No seasonality specification worth running has enough power to survive its own
multiplicity correction.** The one specification class that clears the bar on
arithmetic — a handful of pre-registered, long-window hypotheses — is not a
search, is barely a calendar effect, and **has already been run by this project,
with both of its survivors killed by the corrected cost model.**

**Scope:** feasibility arithmetic only. No warehouse query was run, no
`seasonality_cell` row written, no table created.
**Reproducibility:** every figure below comes from `src/research/seasonality_power.py`
and is pinned by `tests/test_seasonality_power.py` (20 tests, no warehouse).
**Date:** 2026-09-12

> **One input could not be read as specified.** The hard rules permit reading
> `price_spine_adj` row counts and date span. **This environment has no
> warehouse** — `db/` is absent and `data/` holds zero files — so the span is
> taken from the committed `docs/STATUS.md:44` ("adjusted spine reaches
> 2026-09-10") and the 2005 start in `configs/split.yml`. That is 21 years, the
> only number this memo needed from the spine. Nothing else here touches data.
>
> **The artefact is NOT yet registered, and this is the same cause.**
> `scripts/register_engine2_verdict.py` is written and ready. Run here it
> *appeared* to succeed: `provenance` created a governance database, wrote this
> verdict as its only row, printed a hash and exited 0 — a registration into a
> ledger with no prior artefacts, no trial counters and an empty `merkle_log`.
> That database has been deleted and the script now **refuses** an empty ledger
> (exit 2), pinned by four tests. Run it on the machine holding the real
> `governance_prod.sqlite` to register the verdict for real.

---

## The binding constraint, stated once

A calendar cell **fires once per year**. Twenty-one years of history is
twenty-one observations, and **nothing buys more**:

- **Pooling across names does not help.** At the project's own measured
  cross-sectional correlation `rho = 0.2350` (`configs/scan.yml`,
  656 × 2,870 panel), the entire 4,200-name universe carries the information of
  **4.25 independent names** — `n_eff = N/(1+(N-1)ρ) → 1/ρ`. `scan.yml` measured
  this directly: *"n_eff 4.3 of 21,000"*.
- **And the correlation cannot be argued away.** `scan.yml` records the
  correction: the market-relative `rho` of +0.0001 was an **artefact** of
  subtracting the cross-sectional mean, which forces ρ to −1/(N−1) whatever the
  input is. 0.235 is the honest figure.
- **Pooling market-relative returns is not weak, it is undefined.** The
  cross-sectional mean of market-relative returns is identically zero — measured
  max absolute value 1.698e-17. *"Is trading day 47 good on average?"* has no
  content by construction.

---

## 1. The 31.9M figure cannot be reproduced as a product — and that is correct

`configs/trials.yml` charges Track S a prior search of **31,893,556** cells
(MICCV2, run 2026-08-13). `docs/report/PROJECT_REPORT.md:386` illustrates it as:

```
13 window lengths × 242 starting points × 4,200 companies = 13,213,200
plus index-level variants, four calendar alignments, two bases → 31,893,556
```

**The first line is exact. The second does not follow, and no grouping of the
documented axes produces the figure.**

| | |
|---|---|
| prime factorisation of 31,893,556 | **2² × 37 × 215,497**, with 215,497 **prime** |
| do any documented axes divide 215,497? | **none** — not 13, 242, 4,200, 202, 4 or 2 |
| full cartesian grid `13 × 242 × (4,200+202) × 4 × 2` | **110,789,536** |
| 31,893,556 as a fraction of it | **28.8%** |

So V2's number is an **enumeration, not a product**: entities have unequal
history, so not every entity supports every window × start, and roughly 29% of
the grid survived that filter. This is the right way to count and the wrong way
to document it — the report's "=" sign asserts an arithmetic identity that is
false. *(`test_the_documented_axes_do_not_multiply_to_the_published_figure`)*

**For multiplicity purposes the enumerated 31,893,556 is the correct m**, and it
is what this memo uses.

---

## 2. MDE for a representative monthly cell (20 firings)

**Stated assumptions.** Annual return sd **25.0%/yr**, *not assumed but backed
out of the project's own quoted seasonality MDEs* — `scan.yml` states "Two
observations detect an effect of 49.5%/yr. Twenty-one detect 15.3%/yr", and both
imply 25.0%/yr under `power.mde`. Two-sided, 80% power, `power.py` constants.
Cross-correlation ρ = 0.2350 as above.

| correction | α | per-stock | pooled 4,200 (ρ-adjusted) |
|---|---|---:|---:|
| none (m = 1) | 5.0e-02 | 452 bps | **219 bps** |
| **Bonferroni / 31.9M** | 1.6e-09 | **1,110 bps** | **538 bps** |
| BH-FDR 5%, R = 1 | 1.6e-09 | 1,110 bps | 538 bps |
| BH-FDR 5%, R = 100 | 1.6e-07 | 982 bps | 476 bps |
| BH-FDR 5%, R = 1,000 | 1.6e-06 | 911 bps | 442 bps |
| BH-FDR 5%, R = 100,000 | 1.6e-04 | 746 bps | 362 bps |

**BH is reported as a range because its threshold is `α·R/m` — it is looser than
Bonferroni only to the extent that discoveries actually exist.** At R = 1 the two
coincide exactly. Quoting a single BH number requires assuming how many true
seasonal effects there are, which is the question being asked.

---

## 3. Against the published magnitudes: nothing survives

Literature magnitudes below are **from the published record, not measured here**
(no warehouse access, and measuring them would be the analysis this memo is
forbidden to do). They are the generous, original-publication values; McLean &
Pontiff (2016) document ~58% post-publication decay, so live magnitudes are
lower.

| effect | typical magnitude | vs pooled Bonferroni MDE **538 bps** |
|---|---:|---|
| January effect (US small caps, post-1980) | 50–100 bps | invisible |
| Turn-of-the-month (4-day) | 60–90 bps | invisible |
| Halloween / Sell-in-May (monthly differential) | 80–120 bps | invisible |
| India March / fiscal year-end | 100–150 bps | invisible |
| India pre-Budget drift | 100–200 bps | invisible |
| Monday / weekend effect | −10 to −30 bps | invisible |
| January effect (US small caps, 1927–1980, pre-decay) | 200–300 bps | invisible |

**Nothing in the published record comes within a factor of 1.8 of the detection
threshold, and most of it is 5–10× below.** The largest calendar effect ever
credibly reported is less than 60% of the smallest MDE the full scan admits.

---

## 4. Reduced specifications — and the number that settles it

### The decisive result: multiplicity is not what kills this

**At m = 1 — one pre-registered hypothesis, zero multiplicity penalty — a
one-month cell still needs 219 bps/month.** That already exceeds most of the
table in item 3.

| window | MDE at **m = 1** (no correction) | m = 20 | m = 480 | m = 503,360 | full scan |
|---|---:|---:|---:|---:|---:|
| 1 month | **219 bps** | 302 | 370 | 483 | 538 |
| 3 months | 127 bps | 175 | 213 | 279 | 311 |
| 6 months | **90 bps** | **123** | 151 | 197 | 220 |
| 12 months | 63 bps | 87 | 107 | 139 | 155 |

Longer windows help as **√T** — a drift grows linearly with the window while its
sd grows as its root. Sector-level cells (m ≈ 503,360) and macro-conditioning
barely move the number, because they cut *m* while leaving the 20 firings and
the correlation untouched. **Cutting m is cutting the wrong term.**

### Years of history required (1-month window, pooled)

| effect | m = 1 | m = 20 | m = 480 | full scan |
|---|---:|---:|---:|---:|
| 100 bps/month | **96 yr** | 183 yr | 273 yr | 580 yr |
| 150 bps/month | 43 yr | 81 yr | 121 yr | 258 yr |

**Available: 21 years.** Detecting a 100 bps effect needs 4.6× the entire
history of the Indian market's usable record even with **no** multiplicity
correction at all.

### The rank-IC route, which `scan.yml` makes mandatory

`configs/scan.yml` fixes the unit of evidence as the **date** and records why:
*"pooling stocks buys precision WITHIN a date, and buys no additional dates."*
**The same logic applies one level up.** A calendar claim is about the month; the
~21 sessions inside one March move together, so they buy precision *within* a
firing and buy no additional firings.

| intra-firing IC correlation ρ_ic | effective obs | MDE IC, m = 20 | MDE IC, full scan |
|---:|---:|---:|---:|
| 0.0 *(not credible)* | 420 | 0.0224 | **0.0399** |
| 0.1 | 140 | 0.0389 | 0.0692 |
| 0.2 | 84 | **0.0502** | 0.0893 |
| 0.3 | 60 | 0.0594 | 0.1057 |
| 1.0 *(one IC per firing)* | 20 | 0.1028 | 0.1830 |

Plausible real equity signal IC is **0.02–0.05** (`scan.yml:148`). The full scan
clears that band **only at ρ_ic = exactly 0** — sessions within a month treated
as fully independent evidence about that month. One tenth of a point of
correlation destroys it. *A feasibility that survives only at a boundary value
nobody believes is not a feasibility.*

### The largest specification that clears the bar

**≤ 20 pre-registered hypotheses at a ≥ 6-month window, pooled across the
universe: MDE 123 bps/month**, against India-specific effects plausibly at
100–200 bps. Costs are not the binding term here — one round trip per firing
amortised over six months is 4.9 bps/month, under 5% of the MDE.

**But this specification is not Engine 2.** It is not a search — m = 20 means
twenty hypotheses chosen in advance. A 6–12 month "seasonal" window is a
half-year drift, not a calendar effect; at 12 months the cell *is* the annual
return and the calendar contrast vanishes entirely. **And this project has
already run it**: `docs/report/PROJECT_REPORT.md` records that *"the scan of
millions found nothing, while eight carefully-reasoned guesses found two. Both
of those two were then killed by the corrected cost model."*

The only powered specification is one that has been executed and returned
nothing tradeable.

---

## Verdict

**DEAD. The binding constraint is SAMPLE SIZE**, and it is not close:

1. **One firing per year.** 21 years is 21 observations and no design recovers more.
2. **Correlation makes pooling nearly worthless.** 4,200 names → 4.25 independent.
3. **Multiplicity is the secondary penalty, not the primary one.** At m = 1 the
   MDE is already 219 bps; the full correction takes it to 538. **Removing
   multiplicity entirely does not make this feasible.**

This is a stronger and more final result than "the scan found nothing", because
it holds **before any data is examined**. A search cannot be rescued by a better
estimator, a longer scan or a cleverer correction when the smallest visible
effect exceeds the largest plausible one at zero multiplicity.

## What would reverse it

Another ~75 years of Indian equity history, or a genuine cross-sectional
seasonal signal with IC above 0.05 — twice the top of the range `scan.yml`
considers plausible for *any* equity signal. Neither is obtainable.

## What this does not say

It does not say calendar effects do not exist. It says **21 annual firings
cannot distinguish one from noise at any multiplicity correction, including
none** — and that the project's remaining seasonality budget buys a measurement
of its own blindness rather than a finding.
