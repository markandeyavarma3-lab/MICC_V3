# 0025 — The schedule becomes a critical path with a pre-declared cut order

**Date:** 2026-08-18
**Decided by:** Claude, at the owner's instruction to fix the feasibility problem
**Status:** ACTIVE

## Context
PLAN_3 §3 opened *"No deadline was set (Q4), so this is an estimate, not a
commitment."* That has been false since
[decision 0010](0010-project-kill-criterion.md) set **2027-02-28**. The table
also totalled 22 weeks while omitting Phase 6S (4 weeks), Phase 6R and Phase 0.6.

Measured honestly at 15 h/week (Q5):

| | Weeks | Hours |
|---|---:|---:|
| calendar available | 27.9 | 418 |
| plan as written | 26.2 | 393 |
| **slack** | **+1.7** | **+25** |

Six percent. Applying the project's own estimating record:

| Overrun | Slack |
|---|---|
| ×1.25 | **−4.9 wk** |
| ×1.5 | **−11.4 wk** |
| ×2.0 | **−24.5 wk** |

**Every estimate in this project so far has been wrong.** A 25% overrun —
optimistic for software — misses by five weeks.

## Decision
Replace the sequence with a **critical path plus a pre-declared cut order**.

**Critical path — 14 weeks to one portfolio-gated verdict, landing 2026-11-23:**
warehouse (3) · collection reduced to 1 · identity (4) · mart (2) · costs and
benchmarks (2) · **one** outcome study (2).

Two reductions make it fit, and neither is a guess:

- **Collection 3 → 1 week.** The stopgap already captures raw bytes daily and has
  since 2026-08-17. The full parser can wait for a study that needs it, because
  the bytes are already safe.
- **Outcome study 3 → 2 weeks, one study not four.** One study answered beats
  four half-answered, and the remaining three become extensions.

**Extensions, cut last-listed-first:** exp_001 re-run (0.2) · studies 2–4 (3) ·
Track S (4) · seasonality validate-not-rebuild (1) · monitoring (2).

10.2 weeks of extensions against **13.9 weeks of buffer** — 36% overrun tolerance
in place of 6%.

## Why a cut order decided now
Under deadline pressure the thing that gets dropped is whatever is least
defended at that moment, not whatever matters least. Deciding the order in
advance, while nothing is at stake, is the only time the decision is honest.

Monitoring is cut first because reports can be written by hand until there is
something to report. Seasonality is cut second, but only with owner approval —
see below.

## The one cut needing the owner
Phase 7's full 31.9M-cell rebuild is [decision 0006](0006-seasonality-full-rebuild.md),
chosen against my recommendation. Validating instead costs ~1 week and saves 2.
The case is stronger now than when it was made: the predecessor already ran the
scan and its own verdict was *"the best pattern sits at the 94th percentile of
rotated noise"*, and the corrected fee schedule then killed both surviving
effects. **Listed as an extension so the full rebuild happens as decided if the
schedule holds.**

## Consequential fix to the kill criterion
Decision 0010 abandons the thesis when "3 of the 4 studies fail". The critical
path runs **one**, so that rule could never evaluate. `research.yml` now uses
`fail_fraction_threshold: 0.75` over studies **actually run**, with
`min_studies_before_fraction_applies: 2`, and the **2026-11-30 checkpoint as the
primary trigger** — the only condition that fires on the critical path alone.

## What would reverse this
The critical path landing early, which frees the extensions to run as originally
sequenced. Or 0018 resolving in a way that invalidates the outcome study, in
which case the critical path needs redesigning before it is walked.

## Cost accepted
The project now plans to deliver **one** study by the checkpoint rather than four
by the deadline. That is a real reduction in ambition, chosen over the
alternative of four studies that all run out of time at 80% complete — which is
what a 6%-slack schedule actually produces.
