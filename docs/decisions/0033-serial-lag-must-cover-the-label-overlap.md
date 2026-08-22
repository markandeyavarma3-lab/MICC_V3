# 0033 — The serial-correlation lag must cover the label overlap

**Date:** 2026-08-23
**Decided by:** Claude, on measurement; owner approved the fix
**Status:** ACTIVE

## Context

`power.serial_inflation` defaulted its Bartlett lag to the Newey–West rule of
thumb, `4·(n/100)^(2/9)`. That rule depends only on the **number** of
observations and knows nothing about how far each observation's label reaches.

For non-overlapping data that is fine. This project is built almost entirely on
overlapping windows — a 12-month forward return on monthly cohorts means
consecutive observations share eleven twelfths of their window — and there the
rule is not merely imprecise, it is wrong in the direction that manufactures
findings.

Measured 2026-08-23 on real filtered events:

**12-month label, 236 monthly cohorts, overlap 11/12, bound 6.00%**

| lag | inflation | MDE | verdict |
|---:|---:|---:|---|
| NW rule, K=5 | 1.77 | 4.97% | POWERED |
| K=12 (the overlap) | 2.37 | 5.73% | POWERED, 5% margin |
| K=18 | 2.66 | 6.07% | 1.01x SHORT |

**252-session label, 5,035 daily cohorts, overlap 251/252, bound 6.00%**

| lag | inflation | MDE | verdict |
|---:|---:|---:|---|
| NW rule, K=9 | 2.06 | 3.62% | POWERED |
| K=252 (the overlap) | **10.02** | 7.97% | 1.3x SHORT |

In the second case the rule chose lag 9 against a true overlap of 252 and
**understated the variance inflation fivefold**. Both configurations returned a
POWERED verdict that a correct lag removes.

## Decision

`serial_inflation`, `effective_periods` and `mde_serial_corrected` take a
`label_periods` argument — the horizon expressed in cohort periods. When given,
the lag is `max(newey_west_rule, label_periods)`, **never** the minimum. An
explicit `max_lag` still overrides both, because that is the caller stating a
decision rather than accepting a default.

Omitting `label_periods` retains the old behaviour, which is correct only when
consecutive observations do not share a window.

## Why

Under-correcting inflates `n_eff`, shrinks the MDE, and turns an undetectable
effect into a detectable one. That is the single failure mode `power.py` exists
to prevent — its own docstring records that the 12-month +7.80% result *"was
never marginal evidence, it was undetectable"*. The module was reproducing that
error through a parameter nobody had chosen deliberately.

Rounding is deliberately asymmetric. Over-correcting costs power and may report
silence where an effect exists; under-correcting reports an effect where there is
none. Only the second is unrecoverable, because it ends in a published finding.

Rejected: making `label_periods` mandatory. It would break every existing caller
and force a value on non-overlapping studies where the rule is already right.

## What would reverse this

A better-founded bandwidth selector for overlapping labels — Andrews' automatic
selection, or Hodrick's 1B standard errors, which handle overlap directly rather
than by widening a kernel. Either would replace the `max()` heuristic with
something derived rather than chosen.

## Cost accepted

- **Every previously computed long-horizon MDE is too optimistic**, including
  intermediate figures quoted during 2026-08-22–23. The decision-0017 table is
  probably unaffected — monthly cohorts with 10- and 21-session labels barely
  overlap — but that has not been re-derived and should not be assumed.
- Wider lags cost power. Some studies will now report UNDERPOWERED that
  previously would have concluded, and that is the correct direction.
- `label_periods` is opt-in, so a caller who forgets it gets the old behaviour
  silently. The guard against this is convention, not the type system, which is
  weaker than this project's usual standard.
