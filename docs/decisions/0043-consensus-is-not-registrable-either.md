# 0043 — Consensus is not registrable either, on either basis

**Date:** 2026-09-01
**Decided by:** Mine — a measurement, taken because 0038 left the question open
**Status:** ACTIVE

## Context

[0031](0031-consensus-is-the-critical-path-study.md) put consensus on the
critical path, and its reason survives [0038](0038-no-horizon-survives-a-participation-cap.md):
*a pooled convergence event requires no individual institution to be smart.*
Single-participant skill is unmeasurable at this sample size — SBI Mutual Fund
has 80 buys in twenty years — so consensus is the only one of the four studies
whose power does not rest on any one participant being good.

0038 killed the bulk-buy horizons. It did **not** settle consensus, and assuming
it did in either direction would have been guessing at the project's central
question. So it was measured.

## The measurement

3+ distinct participant names buying one symbol inside a trailing 21-session
window (`participants.yml` primary definition), fired on the **crossing** rather
than the state. Market-relative, monthly cohorts, serial-corrected at a lag
covering the label overlap ([0033](0033-serial-lag-must-cover-the-label-overlap.md)),
on `price_spine_adj`.

| basis | horizon | n | cohorts | cohort SD | MDE | bound | verdict |
|---|---|---:|---:|---:|---:|---:|---|
| STRICT | 21s (1m) | 298 | 133 | 18.17% | 4.9204% | 0.50% | 9.84x short |
| STRICT | 63s (3m) | 291 | 131 | 30.70% | 8.3527% | 1.50% | 5.57x short |
| STRICT | 252s (12m) | 255 | 123 | 55.00% | 16.5196% | 6.00% | 2.75x short |
| PERMISSIVE | 21s (1m) | 1,234 | 236 | 12.62% | 2.6136% | 0.50% | 5.23x short |
| PERMISSIVE | 63s (3m) | 1,202 | 235 | 22.15% | 4.9371% | 1.50% | 3.29x short |
| **PERMISSIVE** | **252s (12m)** | **1,064** | **223** | **58.17%** | **11.6414%** | **6.00%** | **1.94x short** |

## Decision

**No consensus horizon is registrable, on either basis.** The best case is
1.94x short of its own bound.

## Why two bases, and why neither was chosen

For a bulk buy the event **is** the trade, so a deal too large to build is not a
tradable event — that is 0038's whole argument. For consensus the event is
*"three institutions converged"* and the trade is a **new position of my own
choosing**, sized by the stock's liquidity rather than by how large their deals
were. The ceiling could reasonably apply in either place.

STRICT counts only deals that are themselves tradable (5,877 eligible).
PERMISSIVE counts any directional buy that is not a same-day round trip and not
a PROP_HFT participant (38,771). Both are reported. Choosing one silently is
how the twelve-month result looked POWERED for a week.

It does not matter here — **neither basis reaches its bound at any horizon** —
but it will matter for Selling and Blocks, and the reasoning is recorded now
rather than re-derived under pressure later.

## This is NOT the kill criterion, and saying it were would be wrong

[0010](0010-project-kill-criterion.md) abandons the thesis when **3 of 4 studies
FAIL their portfolio gate**, or when **none has PASSED one by 2027-02-28**.

An underpowered study has not failed a gate — it cannot be registered to face
one. **Nothing has failed.** What this bears on is the deadline clause: two of
the four studies now have no registrable horizon, so the remaining routes to a
pass by 2027-02-28 are **Selling** (34,270 events, never examined anywhere) and
**Blocks** (cleanest data), both untested.

## What would reverse this

Selling or Blocks measuring as powered — they have more events than consensus
and have not been measured. Or a materially larger effect bound, which would be
an owner decision with its own record, not a fix.

## Cost accepted

- **The event counts are an UPPER bound on real convergence, and the study is
  underpowered even so.** `participant_id` is NULL on all 237,340 rows because
  Phase 3.6 is not built, so "SBI MUTUAL FUND" and "SBI MUTUAL FUND A/C" count
  as two institutions. `participants.yml` flags the same problem from the other
  side — SBI Mutual Fund and SBI Life are two names of one house. Both errors
  inflate apparent consensus. Fixing them can only reduce n and worsen the MDE.
- **The parent-grouped robustness run declared in `participants.yml` has not
  been done**, because the fund-house mapping (step 3.12) does not exist.
- **The threshold and window alternates (2/5 institutions, 5/63 sessions) were
  not run.** Running them now, after seeing the primary fail, would be searching
  for a threshold that produces a result. They belong in a registration, before
  the answer is known.
- Twelve-month events need a complete forward window, so 2,374 constructed
  crossings become 1,064 measurable ones. The most recent year of convergence is
  invisible to the horizon with the best chance.
