# 0017 — The MDE correction is serial, not cross-sectional

**Date:** 2026-08-17
**Decided by:** Claude, correcting my own error
**Status:** ACTIVE

## Context
I told the owner, and wrote into `configs/split.yml` and Plan 2 §3.1a, that
*"every MDE in this project is computed as if names were independent and is
therefore optimistic"*, with the implication it could be wrong by a factor of
three.

**That was false.** `power.py` collapses to monthly cohort means before computing
anything, which defeats cross-sectional dependence by construction: one month is
one observation no matter how many events fall inside it. Measured at the
10-session horizon on 16,445 real bulk-buy events:

| estimator | MDE |
|---|---|
| naive, events treated as independent | 0.076% ← never done |
| monthly cohort, what the code does | 0.621% |
| serial-corrected, what was missing | **0.660%** |

The 8× penalty was already being paid. I overstated my own project's rigour
problem, which is the more embarrassing direction to be wrong in.

## Decision
The MDE carries a **serial** correction — a Bartlett-kernel variance inflation on
the monthly cohort series, Newey–West lag rule `4(n/100)^(2/9)`, K=5 at n=247.
Implemented as `power.serial_inflation`, `effective_periods`, and
`mde_serial_corrected`.

`split.effective_sample_size` is retained but rescoped: it bounds how much
**independent evidence** CONFIRM supplies relative to EXPLORE. It does not enter
the MDE.

## Why
Measured autocorrelation of the cohort series is real but modest — ρ₁ between
0.086 and 0.133, inflation 1.13 to 1.62, so 247 months are worth 152 to 219. A
6–27% correction, not a factor of three.

## What would reverse this
A study whose analysis unit is the *event* rather than the monthly cohort. There
the cross-sectional correction would bind directly and this record would not
apply.

## Cost accepted
Every MDE rises by 6–27%. Two consequences already visible: the 10-session
observed −0.603% now sits **below** its own 0.660% floor, and `exp_001`'s
event-level finding is revealed to depend on the volatility-matched benchmark's
lower dispersion rather than surviving any benchmark.
