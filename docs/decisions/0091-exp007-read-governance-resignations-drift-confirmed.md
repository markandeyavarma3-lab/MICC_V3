# 0091 — exp_007 read once: governance resignations drift, DRIFT_CONFIRMED

**Date:** 2026-10-18
**Decided by:** Owner wrote "approve" for the registration (2026-10-18); the
read follows the spec registered at 09:05 UTC the same day, so the rules, not a
choice, made the verdict.
**Status:** VALIDATED
**Related:** `docs/plan/EXP007_REGISTRATION_DRAFT.md`, `docs/reports/EXP007_POWER.md`,
`docs/reports/EXP007_RESULT.md`, `scripts/register_exp007.py`, `scripts/read_exp007.py`, 0033 (serial inflation),
0035 (dispersion-only power).

## What was read

`exp_007_governance_resignation_drift`, family TRACK_E_EVENTS, spec ddddb17f…,
event list 90d96da3… (8,229 frozen events, 2014–2026-08-31). The read ran once,
at 09:12 UTC, commit 788d926. Its guards re-derived the event list and checked
the hash, the REGISTERED status and that no result existed. A second run is
refused.

| | |
|---|---|
| events with a 63-session return | 4,894 (the same count the power report showed before registration) |
| monthly cohorts | 150 |
| mean cohort CHAR_MATCHED abnormal return, 63 sessions | **−1.73%** |
| t (one-sided, Bartlett inflation 1.00, lag 4) | **−3.70** |
| bar | t ≤ −1.645 and mean ≤ −0.50% |
| verdict | **DRIFT_CONFIRMED** → registry VALIDATED; study_result verdict PASS |
| family ledger | charge 12, trials 0 → 1; the ledger's generic two-sided bar (1.98 at 150 dof) is cleared too |

## What it says, and what it does not

- After a listed company files that its auditor, an independent director, its
  CEO/MD or its CFO has resigned, its stock tends to lag comparable stocks by
  about 1.7% over the next three months. This holds on the pre-registered test,
  against size-momentum-volatility-matched peers (73% of events at the full rung).
- **Not a trading result.** The reported short book subtracts only the statutory
  round trip (~0.29%). It leaves out market impact and borrow. In India, single
  stocks can be held short overnight only through futures (F&O names) or thin
  stock lending (SLB), and many resigning companies are small. A tradable claim
  needs its own registration.
- **The reported splits are not tests.** By role: auditor −4.77% (193 events),
  CEO/MD −2.62%, CFO −1.58%, independent director −1.42%. Before and after
  SEBI's October 2019 auditor-resignation circular: −2.58% before, −1.06% after
  (t −1.85). The later period is weaker. That is a reason to watch, not a
  finding.

## What would reverse this

- Only a defect in the data or the code that the read used: the event list,
  the price spine or the char panel. If one is found, the fix is re-measured
  beside this result, as 0089 did, and the recorded row is never edited.
- A future registration that fails out of sample does not reverse this read. It
  is its own result.

## Cost accepted

- **One trial** in TRACK_E_EVENTS (trials 0 → 1): the family's next test faces
  a stricter bar.
- The pooled design answers only the pooled question. Role-level or
  post-2019 claims would each need a new registration and a new trial.
