# exp_007: does a stock keep drifting after a governance resignation?

**Status: DRAFT, 2026-10-16. Nothing registered, nothing frozen.** Written for
the owner to argue with. The research and the power behind it:
`docs/plan/EXP007_RESIGNATIONS_AND_INDUSTRY_PLAN.md`, `docs/reports/EXP007_POWER.md`.

## 1. The question

When a listed Indian company discloses that its statutory auditor, an
independent director, its CEO/managing director or its CFO has resigned, does
its stock underperform comparable stocks over the following three months,
**after** the announcement-day reaction?

The literature measures the announcement reaction (about -1.3% over four days
for independent directors in India; a further -2% over 30 days for CFO exits
in one unverified report). This project enters at the open after the filing,
so most of that reaction is already in the price. The question is whether the
market finishes adjusting on day one.

## 2. Why it is worth one trial

- **Powered on the whole sample** (dispersion only): 0.88x at 63 sessions
  against CHAR_MATCHED, 150 monthly cohorts, 4,894 events, 2014–2026.
- **A real economic story**, stated before any mean: governance resignations
  carry information the market may under-react to (directors with the most
  oversight leave first; SEBI's 2019 circular exists because auditors left
  without explanation).
- **Not a re-test of anything.** A new population, a new family.

## 3. Proposed frozen specification

| field | proposal |
|---|---|
| experiment_id | `exp_007_governance_resignation_drift` |
| family | **TRACK_E_EVENTS** (new: corporate-event disclosures), carried 0; this test pays 1 |
| event | a filing on NSE's announcement feed whose text reports the resignation of a statutory auditor, an independent director, a CEO/MD/whole-time director, or a CFO, by the rule in `src/research/resignations.py` at the registration commit (role read near each mention of resigning; subsidiaries' auditors and unreadable roles excluded) |
| de-clustering | a company's event counts only if it had none in the previous 21 sessions |
| sample | filings 2014-01-01 to the data date fixed at registration; returns to `measure.REPRODUCIBILITY_HORIZON` (2026-08-31) |
| entry / exit | the open of the first session after the filing date / the close 63 sessions later (`measure._returns_sql`); a suspension wider than the session span is no observation |
| statistic | the event's return minus its CHAR_MATCHED cell (outcomes.py's ladder, self-excluded, >= 10 names); events collapsed to monthly cohort means |
| test | one-sided: mean cohort abnormal return < 0, t on the cohort mean with the serial correction of `power.mde_serial_corrected` (lag covering the 3-month overlap, 0033) |
| pass bar | t <= -1.645 **and** mean <= -0.50% (a third of the 1.50% bound). Significant but smaller is reported as SIGNIFICANT_BUT_SMALL, not passed |
| reported, never tested | each role alone; 21 sessions; CHAR_MATCHED_IND and NIFTY 500 TRI; pre/post the SEBI auditor circular (Oct 2019); a cost-adjusted short book at the pessimistic level |
| kill | fewer than 120 monthly cohorts with an event at the read -> UNDERPOWERED, unread |
| explore | **none** — no mean is read before the registered read (§4) |
| prior | moderate. The announcement effect is established; drift after it is not. A null is a real possibility and an informative one: it would say the market adjusts on day one |

## 4. Why there is no EXPLORE half

The first plan split 2014–2018 (look) from 2019+ (test). Measured, that
leaves the test at exactly its bound (1.00x), a coin flip, and spends the
other 40% on a look that has nothing to shape: the event, its sign and its
rule come from the literature and the filing text. No mean has been read for
any period (`resignation_study.py explore` has not been run). One test on the
whole sample is the stronger design.

## 5. Open for the owner before the hash

1. **No explore, one test on 2014–2026** (recommended) — or the original
   split at 1.00x power.
2. **CEO/MD and CFO in the pooled event, or reported only?** Pooling them is
   what makes the test powered; independent directors and auditors alone are
   the cleaner governance signal but 2–7x short.
3. **The bar**: t <= -1.645 one-sided (a new family's first test) and the
   -0.50% effect floor.

## 6. On acceptance

`scripts/register_exp007.py` on the pattern of exp_006's: check-only by
default, `--rehearse` on a copy, `--register` typed, a clean-tree guard, the
family added to `configs/trials.yml`, and the event rule's code hashed with
the spec. Then one read, recorded beside its spec.
