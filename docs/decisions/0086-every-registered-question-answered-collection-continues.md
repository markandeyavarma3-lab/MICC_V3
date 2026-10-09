# 0086 — Every registered question is answered; collection continues and the waits are scheduled

**Date:** 2026-10-09
**Decided by:** Owner. Offered (a) collection only with scheduled
re-measurements, (b) a new hypothesis tested on years not yet seen, or
(c) wind down, they chose "do both a and b".
**Status:** accepted
**Related:**
- The verdicts: 0076 (exp_004), 0085 (exp_005), 0067 (exp_003), and
  exp_001 and exp_002.
- 0035: dispersion-only power runs are free.
- `docs/reports/INSIDER_POWER.md`: the yearly re-measure.

## Context

With exp_004's landing (0076), every question this project registered has
a verdict, and none found repeatable information in disclosed institutional
activity at the project's bound. Two series are closest to askable, and
each waits on its own length:
- **promoter insider sells**, 1.13× short at 12 months;
- **mutual-fund holding change**, 1.12× short at 63 sessions.

Their re-measurement was a sentence in a report and nothing else. A
sentence does not remind anyone; this project has twice lost data to
schedules that existed only in prose.

## Decision

1. **The collector keeps running unchanged.** It is what lets the two
   series grow: two evening runs plus the SHP session (0078), the deals
   retry, health and backup.
2. **The waits are scheduled in `configs/remeasure.yml`** with a due date,
   the command and what reaching the bound means:
   - insider sells: due 2027-09-15;
   - mutual-fund holding change: due 2027-10-15.

   `src/monitor/remeasure.py` puts a SCHEDULED section in the daily digest.
   It flags an item 30 days before it is due and every day after, until
   `last_done` passes the due date.
3. **A re-measurement is dispersion only (0035) and charges nothing.** A
   registration follows only when a re-measurement shows the design has
   reached its bound. It is then a new experiment with its own family
   charge, and it may not borrow direction from any earlier spread.
4. **(b) is pursued separately** as a forward test of exp_005's
   factor-neutral residual: frozen now, scored only on sessions after
   registration. It is drafted in
   `docs/plan/EXP006_FORWARD_RESIDUAL_DRAFT.md` and is not registered by
   this decision.

## What would reverse this

- The owner choosing to wind down. The collector would stop, the schedule
  would be deleted, and the verdicts would stand.
- A source retiring (NSE, NSDL or SEBI changing a route). That is a
  collection decision of its own.

## Cost accepted

- **Waiting.** Neither series can be asked before about 2028–2029, and
  nothing here makes that faster.
- **A schedule that will mostly report "not yet".** A re-measurement that
  confirms a series is still short is the expected outcome, not a failure.
