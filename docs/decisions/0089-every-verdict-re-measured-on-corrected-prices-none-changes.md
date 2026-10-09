# 0089 — Every registered verdict re-measured on the corrected prices; none changes

**Date:** 2026-10-10
**Decided by:** Owner ("start 1 and then after 1 is done, go for the 2 …";
"we need to fix all the exp_001 to exp_005"; "lets give a last damm try to
fix all those").
**Status:** accepted
**Related:**
- 0087: the Kite audit.
- 0088: the corrections and the quarantine.
- 0067, 0076, 0085 and FINDING_001: the verdicts.
- The evidence is in `docs/reports/REMEASURE_0088.md`.

## Decision

1. **Every registered verdict stands.**
   - exp_001: REJECTED.
   - exp_002: DEAD.
   - exp_003: UNDERPOWERED, unaffected.
   - exp_004 v2: UNDERPOWERED.
   - exp_005: NO_SEARCH_SKILL.
   - Seasonality: DEAD.

   Each was re-measured with committed code on the corrected spine. Where
   it could be done, it was also re-measured with quarantined windows
   excluded. Re-measures are written beside the registered results, never
   over them; the registry was not touched.
2. **"Fixing" an experiment means fixing data and code, never its rules.**
   The owner asked for a last try at fixing them. Every fix here makes a
   verdict reproducible or its inputs trustworthy:
   - exp_001's analysis is now committed code;
   - exp_002 is deterministic;
   - exp_004 has a data cutoff;
   - exp_005's cache checks prices.

   None moves a bar, a horizon or a test after a result was seen. That
   would be the error pre-registration exists to prevent.
3. **exp_005's factor-neutral residual survives** (q 0.012, test IC 0.028).
   The exp_006 forward-test draft is updated to the re-measured effect:
   about 62 forward blocks. Registering it remains the owner's decision,
   before ~2026-11-03.

## What would reverse this

- **A re-measure that changes a verdict.** For example, a third source
  resolving quarantined days in a way that moves exp_004's d_mf across its
  bound. It would be recorded as a new result beside the registered one,
  with this table updated. A registered verdict is never edited.
- **A defect found in a re-measure's own code.** The affected line is
  re-run and the report says what moved.

## Cost accepted

- **exp_001 can only be reconstructed.** Its recorded +0.237%/yr cannot be
  reproduced: the code and the name-split rule were never kept. The
  reconstruction agrees with the verdict, not with the figures.
- **312 unexplained one-day moves stay quarantined**, not corrected; no
  second source exists for them.
