# 0034 — Long horizons restored; 12 months becomes the primary horizon

**Date:** 2026-08-23
**Decided by:** Owner
**Status:** SUPERSEDED by [0038](0038-no-horizon-survives-a-participation-cap.md) — the twelve-month result held only because no participation ceiling was applied. With Plan 2 §4.4's ceiling, no horizon is registrable.

## Context

[0004](0004-horizons-in-sessions-not-months.md) made sessions primary and dropped
the 8/10/15/18/24-month horizons outright, on this reasoning:

> *"At 12 months MDE is already 7.38% against a plausible bound of 0.50%, so
> longer is strictly more hopeless, and each one spends multiple-testing budget
> to guarantee an `UNDERPOWERED` row."*

That arithmetic was correct **under a fixed bound**. [0028](0028-plausible-bound-scales-with-horizon.md)
replaced the fixed bound with one that scales with horizon, and the comparison
inverts: at 12 months the bound is **6.00%**, not 0.50%.

MDE grows roughly with √horizon while the bound grows linearly with it, so under
the rate view **longer horizons get easier, not harder** — the exact opposite of
0004's premise. 0028 did not notice it was invalidating 0004.

Measured 2026-08-23 on eligible, size-filtered bulk buys (n=17,988; round trips
and PROP_HFT removed, ≥₹1cr and ≥0.5% ADV20), market-relative, monthly cohorts,
serial-corrected at a lag covering the label overlap ([0033](0033-serial-lag-must-cover-the-label-overlap.md)):

| horizon | MDE | bound | verdict |
|---|---:|---:|---|
| 21s (1m) | 0.8403% | 0.50% | 1.68x short |
| 63s (3m) | 1.8506% | 1.50% | 1.23x short |
| **252s (12m)** | **5.7273%** | **6.00%** | **within reach, 5% margin** |

Every session horizon is 1.7–3.9x short. Twelve months is the only horizon in
the entire grid that comes within reach of its own bound.

## Decision

**12 months becomes the primary horizon.** The session grid is retained and
demoted to robustness, reported with its `UNDERPOWERED` verdicts intact. The
8/10/15/18/24-month horizons stay dropped — nothing measured argues for
reinstating them, and each still costs multiplicity budget.

## Why

It is the only horizon that can reach a conclusion, and a project that cannot
conclude at any horizon has no path to a result at all. 0004's reasoning was
sound and its premise no longer holds; leaving it standing would keep the primary
grid pointed at four horizons that are all guaranteed `UNDERPOWERED` — the exact
waste 0004 was written to prevent, now pointing the other way.

Rejected: keeping sessions primary and 12m as robustness. That preserves a
headline that cannot conclude while burying the only horizon that can, which is
choosing the appearance of precision over the ability to answer.

Rejected: leaving 0004 standing and pivoting to Track S. Track S remains
worthwhile on its own terms, but abandoning Track D while an untested viable
horizon exists would be giving up early on the measurement rather than on the
evidence.

## What would reverse this

The 12-month margin failing to survive its confound checklist. It is **5%**, and
it is lag-dependent: at K=18 the same measurement is 1.01x short. Era splits,
delisting recovery factors, and the survivorship and time-concentration checks in
`confounds.yml` all have room to move it either way. If it does not hold, no
horizon is registrable and the honest conclusion is that Track D cannot conclude.

## Cost accepted

- **The primary horizon is now the one with the worst overlap problem.** A
  12-month label on monthly cohorts overlaps 11/12, which is why 0033 had to be
  fixed first and why the CPCV group count must fall to N=10 (45 paths) at this
  horizon — thin for a stable PBO estimate.
- **The margin is 5%.** A study registered here sits close to its own detection
  floor, which is the condition `power.py` exists to flag. It must be reported as
  marginal, never as comfortable.
- Twelve-month outcomes mature slowly: events after **2025-08** have no complete
  12-month window, so the usable event set ends roughly a year before the data
  does, and the most recent regime is invisible to the primary horizon.
- The headline moves from "no effect at short horizons" to "an effect that takes
  a year to appear", which is a materially weaker economic claim even if it
  clears statistically.
