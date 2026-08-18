# 0023 — Trial families, and the three gaps between the two tracks

**Date:** 2026-08-18
**Decided by:** Owner instructed "fix all those gaps"; scheme designed by Claude
**Status:** ACTIVE

## Context
Decision [0019](0019-two-track-programme.md) split the project into Track D
(deals) and Track S (scan). A verification pass found the two tracks were never
wired together. Three gaps, all of which would have surfaced only once Track S
code ran.

### Gap 1 — Track S had no exploration/confirmation partition
`configs/split.yml` partitions by ISIN, which is meaningless for a calendar cell
(a cell spans every stock at once). `scan.yml` never referenced a split. So a
31.9M-cell scan would have run across all data with nothing held back, while
Track D sat behind a guard that raises. **Half the project was outside its own
discipline framework.** Decision [0012](0012-seasonality-dual-split.md) had
specified the answer and it was never implemented.

### Gap 2 — a scan study could not be registered
`StudyKind` was `event_study | portfolio | seasonality`. `confounds.yml` had no
`applies_to: [scan]` entry. The design gate — mechanism, side-prediction,
computed MDE, confound checklist — **did not apply to Track S at all**, i.e. to
the half with far worse multiple-testing exposure.

### Gap 3 — the trial counter would have destroyed Track D
`research.yml`: *"Applied to EVERYTHING including incumbents."* `scan.yml`:
silent. Read literally:

| Counter state | Track D bar |
|---|---|
| today (171) | 3.71 |
| after a 5,000-combination signal scan | 4.92 |
| after a 1M-cell calendar scan | 6.42 |
| after the full 31.9M rescan | **7.28** |

**exp_001's t = −3.93 would have retroactively failed and no deal study could
ever have passed again.** Track S would have killed Track D as collateral damage,
and the contradiction would have surfaced only on the day someone ran a scan and
watched every deal result evaporate.

## Decision

**Hierarchical trial families** (`configs/trials.yml`, `src/research/families.py`).
Four families — `TRACK_D_DEALS`, `TRACK_S_CALENDAR`, `TRACK_S_SIGNALS`,
`TRACK_S_PROCEDURE` — each with its own monotonic counter and bar. A search
charges its own family and no other. **Any claim of the form "the project found
X" faces the project-level bar summed across all families**, and both bars are
reported.

**The procedure exemption.** `TRACK_S_PROCEDURE` has a fixed family size of 3
(one per `top_n`) regardless of scan width, because exactly one procedure is
under test per configuration and the 31.9M cells are the instrument that measures
it, not competing hypotheses. **This is the reasoning that makes "scan wide to
measure overfitting" legitimate rather than a loophole.** It holds only while the
claim is about the procedure; the moment a specific surviving pattern is
reported, it pays full width in `TRACK_S_CALENDAR`.

**`TRACK_S_CALENDAR` carries 31,893,556 prior trials** from the predecessor's
completed scan. That space is not virgin and a rebuild does not get to look at it
as though for the first time.

**Track S partition** (`split.yml § scan`): a mandatory **time** split — explore
2005–2015, confirm 2016+, 21-session embargo — because it is the only partition
that tests persistence, which is what a pattern claim asserts. Plus a secondary
**index** split (40/60), explicitly `corroborating_only` because the 202 indices
overlap heavily. `ScanGuard` refuses unregistered CONFIRM reads.

**Scan study kind** with five blocking confounds: `multiple_testing_declared`,
`null_is_measured_not_assumed`, `fold_independence`, `bid_ask_bounce`,
`prior_search_of_this_space`. A scan must declare its family, its nominal fold
count, and its **effective** fold count before registration.

## What stops this being a loophole
Not family size — **declaration order**. Families are declared before the search
and are immutable afterwards, and a result may never be moved to a smaller family
once seen. Choose the family late and every result lands in a family of one,
which is exactly the predecessor's failure: it deflated challengers while
exempting its own champion.

## A fourth gap, found inside the fix
`trials.yml` declared the counters `monotonic` and `never_reset` — and **nothing
incremented them.** `charge()` was a pure function; `project_counter()` summed
static YAML. A 31.9M-cell scan could have run without moving anything.

That is exp_001's `trials_before` — computed, stored as 171, printed once, never
read — **rebuilt one level up, inside the file whose subject is that exact
failure.** Fixed by migration `0002_trial_families`: a `family_charge` ledger with
triggers refusing UPDATE, DELETE, and any total that would decrease.

## What would reverse this
Evidence that two families are in fact one — that a selection is genuinely being
made across them. If the final verdict ever reads "we tried the deal studies and
the scan and here is the best result", that claim already faces the project-level
bar, which is the case this scheme was built to handle.

## Cost accepted
Four counters to maintain instead of one, and a weakening of the blunt "applies
to EVERYTHING" rule that existed because the predecessor exempted its champion.
The defence is retained inside each family and at project level; what is given up
is the simplicity of a single number.

195 tests pass, from a clean database, twice.
