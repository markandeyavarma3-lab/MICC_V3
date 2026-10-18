# exp_007 — the one read: **DRIFT_CONFIRMED**

Read 2026-10-18T09:12 UTC at commit 788d926; spec ddddb17fa518; event list 90d96da34527.

## Primary (tested)

Governance resignations pooled (auditor, independent director, CEO/MD, CFO), 63 sessions from the open after the filing, against CHAR_MATCHED; monthly cohorts; one-sided t with Bartlett inflation.

| events | cohorts | mean cohort abnormal | t | inflation | bar | verdict |
|---:|---:|---:|---:|---:|---|---|
| 4894 | 150 | -1.73% | -3.70 | 1.00 | t <= -1.645 and mean <= -0.50% | **DRIFT_CONFIRMED** |

Registry status advanced to **VALIDATED**; one trial charged to TRACK_E_EVENTS.

## Reported, never tested

None of these is a test; none can change the verdict above.

| figure | events | cohorts | mean | t |
|---|---:|---:|---:|---:|
| 63s MKT | 4894 | 150 | -2.16% | -4.38 |
| 21s MKT | 5313 | 151 | -0.97% | -3.65 |
| 63s CHAR_MATCHED | 4894 | 150 | -1.73% | -3.70 |
| 21s CHAR_MATCHED | 5313 | 151 | -0.97% | -4.29 |
| 63s CHAR_MATCHED_IND | 4894 | 150 | -1.75% | -3.71 |
| 21s CHAR_MATCHED_IND | 5313 | 151 | -0.99% | -4.13 |
| 63s CHAR_MATCHED AUDITOR | 193 | 76 | -4.77% | -1.85 |
| 63s CHAR_MATCHED CEO_MD | 1169 | 150 | -2.62% | -2.56 |
| 63s CHAR_MATCHED CFO | 1066 | 146 | -1.58% | -1.56 |
| 63s CHAR_MATCHED INDEPENDENT_DIRECTOR | 2466 | 150 | -1.42% | -2.27 |
| 63s CHAR_MATCHED before the SEBI auditor circular | 2250 | 70 | -2.58% | -3.45 |
| 63s CHAR_MATCHED after the SEBI auditor circular | 2644 | 81 | -1.06% | -1.85 |

CHAR_MATCHED rungs used: {'SIZE_MOM_VOL': 0.733, 'SIZE_MOM': 0.267, 'SIZE': 0.001}

Short book (reported): statutory round trip at the headline brokerage on Rs 10 lakh per name, market impact and borrow EXCLUDED — median cost +0.29%; a short's mean after that cost +1.45%.

## Reading this

- The 4,894 events with a 63-session return are the same count the power
  report (`EXP007_POWER.md`) showed before registration; nothing moved between
  registration and read.
- **Not a trading result.** Market impact and borrow are excluded; overnight
  single-stock shorts in India need F&O futures or thin SLB borrow, and many of
  these companies are small.
- The splits by role and around SEBI's 2019 auditor circular are reported, not
  tested. The weaker post-2019 figure is a reason to watch, not a finding.
- Decision 0091.
