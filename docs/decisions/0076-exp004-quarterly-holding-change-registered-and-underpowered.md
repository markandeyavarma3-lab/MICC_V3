# 0076 — exp_004: quarterly holding change, registered and UNDERPOWERED

**Date:** 2026-10-09
**Decided by:** Owner. They confirmed the registration directly ("Register
and run") after choosing, on 8 October, to retire an earlier row registered
without their confirmation (option B).
**Status:** accepted — the study is closed
**Related:**
- 0074: the SHP bytes come before the registration.
- 0077: the market leg is NIFTY 500 TR.
- 0078: the evening SHP session.
- 0035: dispersion-only power runs.
- 0038 and 0043: the same class of landing.
- `docs/plan/EXP004_HOLDINGS_REGISTRATION_DRAFT.md`: the spec, with its
  argument in §1–8 and the retired row in §10.

## What was registered

`exp_004_holdings_change_v2`, spec `2b5811c1…6c30e0`, frozen at commit
`3196d93` from a clean tree on 9 October 00:58 IST. Every company that files
had its filings held: 2,300 of 2,300 (the 618 without filings are empty
masters).

The study asks whether the top decile of filing-over-filing change in a
stock's FPI, all-foreign-institution or mutual-fund holding beats the bottom
decile over 63 sessions:
- three tests, with BH-FDR at 5%;
- the primary is CHAR_MATCHED;
- the bound is 1.50% per 63 sessions;
- the tail rule is the participation cap.

The prior, written into the spec before any return was read: "UNDERPOWERED
remains the likeliest landing."

`exp_004_holdings_change` (spec `e610fbae…`) is RETIRED and unrun. It was
registered by a coverage probe without the owner's word, carrying a coverage
line read through a bug (draft §10).

## The result

| signal | cohorts | spread | 95% CI | q (BH) | MDE | vs bound | net of cost |
|---|---:|---:|---|---:|---:|---:|---:|
| d_fpi | 18 | +0.77% | [−1.33%, +3.07%] | 0.611 | 3.60% | 2.4× | −0.25% |
| d_foreign | 14 | −0.10% | [−1.75%, +1.54%] | 0.921 | 3.04% | 2.0× | −1.12% |
| d_mf | 18 | +0.65% | [−0.31%, +1.86%] | 0.611 | 1.68% | 1.12× | −0.37% |

**UNDERPOWERED in all three tests (kill 1).** d_foreign also meets kill 2:
what spread there is lives in the untradeable names. Nothing passed. No
spread survives costs.

None of the 36 robustness lines is a test; each is reported in
`docs/reports/HOLDINGS_VERDICT.md`. Their CIs straddle zero except two:
- the market-relative mutual-fund line, [+0.11%, +2.01%];
- the 21-session mutual-fund line, [+0.02%, +1.18%].

Both are unadjusted, untested, and inside a design that cannot see its own
bound. They are recorded as observations, not findings.

`TRACK_H_HOLDINGS` was charged 3 trials (0 → 3).

## What it means

The fourth registered question met a bar fixed before the data was read and
did not clear it. As with consensus (0043) and bulk buys (0038), the design
cannot detect an effect of the size the project calls plausible. This is
not evidence that holding changes carry nothing. It is evidence that 18
quarters of Indian shareholding filings cannot show it at this bound.

Mutual funds came closest, at 1.12× short. The series grows four cohorts a
year. If the MDE shrinks with √cohorts, the d_mf design reaches the bound
after about 23 cohorts, around 2028. Re-asking it then is a new
registration, `exp_004_v3`, and it would be charged to the same family.

## What would reverse this

- Nothing reverses a registered verdict.
- A re-registration of d_mf alone, once ~23 cohorts exist, is permitted. It
  must not borrow anything from this run's spreads, so the direction stays
  two-sided.

## Cost accepted

- Three trials in a family that started at zero.
- A registry that now carries a RETIRED row for this study, kept by its
  no-delete trigger, because its first registration was not the owner's.
