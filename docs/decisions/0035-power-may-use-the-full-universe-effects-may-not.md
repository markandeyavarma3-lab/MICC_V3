# 0035 — Power analysis may use the full universe; effect estimates may not

**Date:** 2026-08-23
**Decided by:** Owner, on a self-audit
**Status:** ACTIVE

## Context

On 2026-08-23 an audit of the day's own work asked whether it had respected the
EXPLORE / SELECT / CONFIRM partition ([0008](0008-three-way-split.md)). It had
not consulted it: neither `charmatch.py` nor `src/mart/` references
`ConfirmationGuard` or `assign()`, and roughly a dozen measurements ran across
the full corpus, CONFIRM names included.

The work turns out to have been legitimate. Everything computed was
**dispersion** — cohort standard deviations, variance inflations, minimum
detectable effects. No mean, no *t*-statistic, no effect estimate. Plan 2 §6.5
explicitly requires MDE to be computed *"before running, from the observed N and
return dispersion"*, which cannot be done on 30% of the data if the study will
run on all of it: a power calculation on a subsample answers a question about the
subsample.

`family_charge` correctly reads 0, because nothing was tested.

**But the boundary had never been written down, and nothing enforced it.** The
day came out clean by recollection, in a repository whose entire thesis is that
discipline must be mechanical rather than remembered.

## Decision

- **Dispersion may use the full universe.** Cohort SD, serial inflation, MDE,
  effective sample size, thin-cell diagnostics, benchmark-construction
  diagnostics. These describe the data's noise, not its signal.
- **Any estimate of an effect must go through the guard**: means, medians, hit
  rates, *t*-statistics, information coefficients, portfolio differences — and
  every one of them charges its family.
- The dividing line is **whether the number could change a belief about the
  hypothesis.** A quantity that cannot distinguish a true effect from a false one
  cannot be p-hacked by looking at it.

## Why

Without the first half, pre-registration becomes impossible: `design.py` demands
a computed MDE before a study may exist, and that MDE must describe the universe
the study will actually run on. Forcing power analysis into EXPLORE would make
every registered bar wrong by construction.

Without the second half the partition is decoration.

Rejected: routing everything through EXPLORE. It costs precision on every
measurement and — worse — makes each registered study's stated MDE describe a
30% sample rather than the study. That is not conservatism, it is a different
error.

Rejected: leaving it as a judgement call. It survived one audit; it will not
survive twenty, and the reason to write it down is precisely that this session
relied on remembering it.

## What would reverse this

Evidence that dispersion estimates leak signal in practice — for example if
selecting a benchmark or a cohort frequency on measured MDE reliably favours
specifications that later show larger effects. That would make the "cannot change
a belief" test false, and power analysis would have to be charged like anything
else.

## Cost accepted

- **The rule is enforced by convention, not by code.** No guard distinguishes a
  dispersion query from an effect query, so this record is a rule a person must
  follow — the weaker form of discipline this project generally rejects, accepted
  because the mechanical version would break pre-registration.
- The boundary has a grey zone. Choosing among four benchmark specifications on
  measured MDE, as was done on 2026-08-23, is a *selection* even though the
  criterion is dispersion. It is permitted here, and a determined researcher
  could walk a long way toward a result while only ever looking at variances.
- Anything already measured on the full universe cannot be un-seen, so this
  ratifies past conduct as well as governing future conduct.
