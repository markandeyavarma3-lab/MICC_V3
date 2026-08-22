# 0028 — The plausible effect bound scales with horizon (the rate view)

**Date:** 2026-08-21
**Decided by:** Owner
**Status:** ACTIVE — closes [0018](0018-plausible-bound-not-horizon-scaled.md)

## Context

[0018](0018-plausible-bound-not-horizon-scaled.md) raised an open defect on
2026-08-17 and was never resolved. `configs/research.yml` carries a single
`plausible_effect_bound_monthly: 0.005`, and the `UNDERPOWERED` rule compared
**every** horizon's MDE against it — a comparison that is only dimensionally
valid at ~21 sessions. Judging a 1-session MDE against a per-month bound is a
unit error.

Since 2026-08-18 `design.py` has refused to register any non-monthly horizon
without an explicit bound rather than guess. Because every primary horizon is
measured in sessions ([0004](0004-horizons-in-sessions-not-months.md)), that
refusal blocked **all** Track D registration. Phase 6 could not start.

The question was which model of the effect applies:

- **Event view** — disclosure causes a one-off repricing; the effect is fixed
  regardless of horizon and one bound is correct.
- **Rate view** — skill is persistent; the effect accrues per unit time and the
  bound must scale.

## Decision

**The rate view.** The plausible bound scales linearly with horizon:

```
bound(h sessions) = plausible_effect_bound_monthly * h / sessions_per_month
```

with `sessions_per_month: 21`. `design.py` computes this for any
session-expressed horizon instead of raising.

## Why

An institution that is genuinely informed does not earn its entire edge in the
first session and then stop; if the disclosure carries information about the
company's prospects, the abnormal return accrues while that information is
absorbed. Under that reading a fixed bound would credit a 1-session horizon with
the same plausible effect as a 21-session one, which asserts that all of a
month's edge lands on day one.

The event view was rejected despite being the more convenient answer. It is not
obviously wrong — temporary price impact reversing is real, and the measured sign
flip (+0.691% at 1s decaying to −1.061% at 21s) is consistent with it. But it is
the reading under which this project can still claim to conclude things at short
horizons, and adopting the interpretation that licenses your own conclusions is
the failure mode the entire repository exists to prevent.

## The consequence, stated plainly

**Every horizon in the current grid becomes UNDERPOWERED.** Measured
serial-corrected MDEs against the scaled bounds:

| horizon | MDE corrected | scaled bound | verdict |
|---|---:|---:|---|
| 1s | 0.191% | 0.024% | **UNDERPOWERED** |
| 5s | 0.423% | 0.119% | **UNDERPOWERED** |
| 10s | 0.660% | 0.238% | **UNDERPOWERED** |
| 21s | 0.968% | 0.500% | **UNDERPOWERED** |

The two horizons previously marked detectable are not detectable. This is not a
degradation of the project — it is the project's own machinery reporting that the
data cannot answer the question at the resolution being asked, which under
`power.py`'s rule is **silence, not a negative result**.

It also means a study cannot be registered as designed today: `design.py`
rejects a design where every horizon is blind. The route forward is to raise
power — characteristic matching cut cohort SD 8.55% → 5.91% and MDE 1.52% →
1.05% on one dimension alone — not to relax the bound.

## What would reverse this

A measured decomposition of abnormal return against horizon showing the effect is
front-loaded and flat thereafter — i.e. the repricing completes inside a session
or two and does not accrue. That is an empirical question this platform can
answer once the identity layer lands, and answering it would justify reopening
under the event view with a new record.

## Cost accepted

- **No Track D study can currently reach a conclusion at any declared horizon.**
  Phase 6 as specified produces four UNDERPOWERED verdicts.
- The project's most likely deliverable moves further toward "we could not tell"
  and away from "there is no effect" — a weaker and less satisfying negative,
  though a more honest one.
- Work is now required on power before registration is worth doing:
  characteristic matching ([benchmarks.yml](../../configs/benchmarks.yml)
  `CHAR_MATCHED`) moves from a control to a **precondition**.
- `21` sessions-per-month is itself a convention, not a measurement. It is
  recorded in config rather than hard-coded so it can be challenged.
