# 0022 — The multiplicity bar was wrong three ways, all anti-conservative

**Date:** 2026-08-18
**Decided by:** Claude, after the owner asked for verification
**Status:** ACTIVE

## Context
`multiplicity.py` has set every significance bar in this project since it was
written. Its docstring claimed the errors in it pointed the safe way:

> *"treating N as independent is CONSERVATIVE: the bar comes out too high rather
> than too low. That is the right direction for the error to point."*

**All three errors found on verification pointed the other way.**

### Error 1 — sidedness
The estimator computed the expected maximum of *signed* normals,
`norm.ppf(1 - 1/n)`, while `Bar.clears()` compares `abs(observed_t)`. Measured at
N=171 over 20,000 replications: `max(z)` = 2.693, `max|z|` = 2.922. The module
matched a one-sided maximum and was applied two-sided, understating **every bar
it ever produced**.

### Error 2 — degrees of freedom
Test statistics are t-distributed, not normal, and with few observations the t
has far fatter tails. Over 3,146 draws:

| Distribution | E[max \|stat\|] |
|---|---|
| normal N(0,1) | 3.746 |
| t, df=20 (21 obs) | **4.599** (+23%) |
| t, df=60 | 3.999 |
| t, df=250 | 3.798 |

A calendar cell scored on 21 yearly observations is t(20). Track D is unaffected
in practice — 247 monthly cohorts give t(246).

### Error 3 — grid geometry
Correlation between overlapping cells pulls the maximum back *down*, partly
cancelling error 2:

| Cell correlation | E[max \|t\|] |
|---|---|
| ρ = 0.0 | 4.595 |
| ρ = 0.3 | 4.125 |
| ρ = 0.7 | 3.071 |

On a simulated realistic calendar grid the truth was **4.151**, against a normal
formula of 3.568 and a dof-adjusted 4.60. **No formula gets a specific grid
right.**

## Decision
1. Both branches use the two-sided quantile `G⁻¹((1+p)/2)`.
2. `expected_max_null_t` and `bar` accept `dof`; validated against Monte Carlo to
   within 1.0% across trials ∈ {100, 3146, 100k} × dof ∈ {20, 60, 246}.
3. `simulated_max_null_t` added. **For Track S it is the operative bar**; the
   formula is a planning guide only.
4. `configs/scan.yml` sets `bar_from: multiplicity.simulated_max_null_t` and
   `dof_must_be_declared: true`.

## Corrected published values

| N | old (1-sided) | corrected | bar | bar at df=20 |
|---|---|---|---|---|
| 10 | 1.57 | 1.90 | 2.80 | 3.14 |
| 171 | 2.71 | **2.94** | **3.67** | 4.36 |
| 1,000 | 3.26 | 3.45 | 4.31 | 5.13 |
| 31,893,556 | 5.51 | **5.63** | **7.04** | **11.27** |

Track D's operative bar becomes **\|t\| ≥ 3.71** (171 trials, df=246), up from
3.62. **exp_001's t = −3.93 still clears it**, so no recorded verdict changes.

The binding constraint at 171 trials flipped from the Śidák family-wise value to
the noise maximum, which is why `test_both_binding_regimes_are_reachable` now
probes N=10 for the family-wise branch.

## What would reverse this
A scan whose per-cell statistic is genuinely normal — a large-sample z rather
than a small-sample t — where `dof=None` is correct rather than a shortcut.

## Cost accepted
Every bar in the project rises. Track S's nominal bar at full width goes from
6.89 to 11.27 before the geometry correction pulls it back, and the operative bar
now requires a simulation run before any scan can be scored. That is slower and
correct.

**And the process cost.** Three errors in one module, all anti-conservative, none
caught by 146 tests — because the tests pinned the module's own output as golden
values rather than checking it against an independent Monte Carlo. A test that
asserts the code agrees with itself proves nothing. The dof tests added here
compare against simulation, which is the standard the originals should have met.
