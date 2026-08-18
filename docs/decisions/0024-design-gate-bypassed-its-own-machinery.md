# 0024 — The design gate bypassed the machinery built to set its bars

**Date:** 2026-08-18
**Decided by:** Claude, found on an adversarial sweep of my own integration
**Status:** ACTIVE

## Context
`design.py` is the gate every study passes through. It computed its bar with:

```python
object.__setattr__(self, "_bar", bar(self.trials_before))
```

Three faults in that one line and its neighbours. **Every one made results easier
to pass**, which is the direction that matters.

### Bug A — `dof` was never passed
[Decision 0022](0022-multiplicity-had-three-errors.md) added degrees-of-freedom
support to `multiplicity.bar` because the normal assumption understates the bar
whenever the per-test sample is small. `design.py` was never updated, so every
design received the normal-assumption bar.

| Declared | Bar at 171 trials |
|---|---|
| nothing (assumes normal) | 3.67 |
| `dof=246` — Track D, 247 cohorts | 3.71 |
| `dof=20` — a calendar cell, 21 years | **4.36** |

### Bug B — `trial_family_id` was validated and then ignored
Worse. [Decision 0023](0023-trial-families-and-track-s-wiring.md) built the family
scheme *that same day* to stop searches being charged to the wrong counter.
`_check_scan` confirmed the family existed and `_compute_bar` never looked at it.

A scan declaring `TRACK_S_CALENDAR` — which carries **31,893,556** prior trials
from the predecessor's completed atlas — was handed a bar computed from
`trials_before=171`:

| | Bar |
|---|---|
| what it produced | **3.67** |
| what it should be | **11.27** |

**The predecessor's entire 31.9M-cell search was free.** The scheme was built to
prevent exactly this and the gate walked straight past it.

### Bug C — a per-month bound applied to any horizon
`HorizonPower.is_powered` fell back to `plausible_effect_bound_monthly` for
*every* horizon, including single-session ones. Comparing a 1-session MDE against
a per-month bound is a unit error, and it made short horizons look powered when
they may not be.

This is [decision 0018](0018-plausible-bound-not-horizon-scaled.md) — recorded as
OPEN two days ago — **live in code, silently producing verdicts.**

## Decision
1. `dof` is a declarable field on `StudyDesign` and is threaded into the bar.
2. When `trial_family_id` is declared, the bar comes from `families.charge`, so
   the family's carried count and typical dof both apply.
3. `is_powered` **refuses** any non-monthly horizon lacking an explicit
   `plausible_bound`, naming decision 0018 in the error.

## Why refusal rather than a default for Bug C
0018 turns on whether disclosure causes a one-off repricing (fixed bound) or a
persistent rate of return (scaled bound). That is an owner decision and it is not
made. **An open question should stop the code, not be resolved by a default
nobody chose** — which is precisely how the bound became load-bearing in the
first place ([0011](0011-plausible-effect-bound.md)).

## The pattern worth naming
All three bugs are the same shape: **machinery built and not wired in.** It is the
third instance in two days —

- `trials_before` computed, stored, never read (fixed 0022-era)
- family counters declared monotonic, nothing incrementing them (fixed 0023)
- `dof` and families built, the gate ignoring both (this record)

Writing the mechanism is not the work. Connecting it is, and connection is what
keeps being skipped. Integration tests now cover all three.

## What would reverse this
Decision 0018 being settled, at which point Bug C's refusal can become a
horizon-aware default rather than a demand.

## Cost accepted
Every study must now declare its dof and, for scans, its family — more ceremony
per registration. And no session-horizon study can be registered at all until
0018 is answered. That is deliberate: the alternative is a wrong verdict issued
quietly.
