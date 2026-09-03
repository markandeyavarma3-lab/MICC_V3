# 0051 — The sell effect is confounded, not a miscalibrated bound

**Date:** 2026-09-03
**Decided by:** Owner asked for the confound checklist to be run against the
open question from 0044.
**Status:** ACTIVE — answers the question 0044 left open

## Context

0044 measured a −23.80% twelve-month market-relative mean on sold names against
a null of −0.00%, with a hit rate of 24.0% against 32.0%, while the study was
1.96x short of power. It stated the tension plainly and refused to resolve it:

> Either 0011's bound of 0.5%/month is miscalibrated for this event class — in
> which case every UNDERPOWERED verdict in this project needs recomputing — or
> the sell result is confounded by something `confounds.yml` covers and this
> measurement did not.

`confounds.yml` has declared a mandatory nine-item checklist for event studies
since 2026-08-18. **Nothing had ever run it.** Every verdict this project has
produced measured dispersion only, which 0035 permits precisely because
dispersion cannot distinguish a true effect from a false one.

## What was run

`src/research/confounds.py`, on **EXPLORE only** (n=1,255 sell events, 30% of
the population by `split.yml`'s partition), twelve-month horizon, at
`REPRODUCIBILITY_HORIZON`. Raw EXPLORE effect: **−30.30%**.

A confound answer IS an effect estimate, so per 0035 this charges its family.
`family_charge` is no longer empty — the first legitimate spend in the project.

## The result

**Four confounds come back clean:**

| confound | result |
|---|---|
| microstructure | control **−0.00%** on identical dates — explains 0.0% of raw |
| volatility | vol-matched peers **−0.06%**, residual −31.51% |
| momentum_reversal | corr **−0.0030**, quintiles non-monotonic → reversal rejected, matching the 2026-08-16 precedent exactly |
| time_concentration | sign consistent across all four eras (−17.28% / −29.23% / −58.10% / −29.96%) |

**Two do not, and together they are the answer:**

**1. The liquidity gradient runs the wrong way.**

| tier | n | effect |
|---|---:|---:|
| off500 | 129 | **−60.32%** |
| top500_ex100 | 432 | −32.98% |
| top100 | 514 | −25.43% |

Monotonically weaker as tradability rises. `confounds.yml` records that Finding
001 was *stronger* in liquid names and calls that "the unusual and encouraging
direction". This is the opposite, and its own text names the consequence: *"An
effect living only in off-500 names is an effect you cannot take."*

**2. Thirty-one percent of the events are on names that later stopped trading,
with no recovery factor applied.** 388 of 1,255. Plan 3 step 6.4 (delisting
handling at three recovery factors) is SPECIFIED and unbuilt, so a name that
declined and delisted contributes its full decline to the average with nothing
offsetting it.

**One cannot be measured at all.** `sector_concentration` is marked
NOT_APPLICABLE in writing: `sector_history` holds 0 rows because Plan 1 step 3.5
is unbuilt. `confounds.yml` calls the leave-one-sector-out re-run "cheap, and it
has killed real-looking results elsewhere" — so this is a real gap, not an
argument that sector does not matter.

## Decision

**The sell effect is treated as confounded.** 0011's plausible bound is NOT
revisited on this evidence.

## Why

The two live confounds are both mechanisms that manufacture a large negative
mean without any information being present, and they compound: illiquid names
are also the ones most likely to delist. An effect that is strongest exactly
where it cannot be traded, measured on a population where a third of the names
died with no recovery factor, is the textbook shape of a survivorship-and-
illiquidity artefact.

Revising 0011 would have been the higher-impact conclusion — it would have
reopened 0038, 0043, 0044 and 0046 at once. That is precisely why it needed the
checklist to survive rather than an argument to be built on it.

## What would reverse this

Step 6.4 built, delisting recovery factors applied at all three levels, and the
effect surviving in `top100` alone at a magnitude that still exceeds the bound.
The top100 tier is already the weakest at −25.43%; the test is whether it holds
once dying names are priced honestly.

## Cost accepted

- **The checklist ran on EXPLORE, n=1,255.** Small. The tiers that carry the
  finding are smaller still — off500 has n=129, and its −60.32% is not a number
  to defend to two decimals. The *direction* is the finding, not the magnitude.
- **`sector_concentration` is unmeasured and blocking.** Any registration of a
  sell study must build 3.5 first or disclose it as unmeasured. This record does
  not resolve it.
- **Size quintiles are badly unbalanced** — 843 of 1,008 classified events sit
  in size_q 5, and size_q 2 has n=9 at −53.84%. The size confound is reported
  but is not load-bearing here, and should not be quoted as though it were.
- **The family was charged twice** during development because the module was run
  twice. The ledger is append-only and correctly records both; the trial count
  reflects searches actually performed, not searches that should have been
  performed. That is the ledger working, and it makes the eventual multiplicity
  bar slightly stricter.
