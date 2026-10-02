# 0081 — The five-session round trip is a flag, not a filter

**Date:** 2026-10-01
**Decided by:** Owner ("yeah lets start doing"), on the recommendation to build
Plan 3 step 4.3 next. The five-day flag itself is owner decision Q23 (Plan 1
§7.1); this record fixes its definition and what it may be used for.
**Status:** accepted
**Related:** 0080 (the promoter flags, which follow the same flag-only rule),
0057 (the cost of matching participants on raw spelling).

## Context

`five_day_round_trip_flag` has been FALSE on every deal since Phase 4.
Only the same-day round trip was computed: a participant that bought and sold
one stock in one session. A participant that buys Monday and sells Thursday
was treated as an institution that bought.

## Decision

1. **A leg is flagged when the same participant traded the opposite side of
   the same stock on a different session no more than five SESSIONS away, in
   either direction.**
   - The window is counted on the observed trading calendar, so a weekend
     does not use up the window.
   - Same-day pairs are left to the same-day flag.
   - Two buys in a row are accumulation, not a round trip.
   - The participant and symbol keys are the same-day flag's
     (`UPPER(TRIM(...))`), so the two flags describe one idea at two horizons.
2. **A flag, never an eligibility rule.** Monday's buy is flagged from a sell
   disclosed on Thursday. Dropping Monday's buy from a study for that reason
   uses information nobody had at entry. It would flatter any "institutional
   buys predict returns" result by deleting the buys that were quickly
   undone. A study may describe its sample with the flag or run a labelled
   sensitivity, and may not select on it. A test fails if the eligibility
   ladder in `src/mart/clean.py` ever reads it.
   - The same-day flag remains an exclusion, because both of its legs are
     disclosed the same evening.

## Cost accepted

- **Spelling variants escape.** Raw spellings are not normalised, so a
  participant written two ways escapes the flag, the same cost 0057 measured
  for the same-day flag. Normalising here alone would make the two flags
  disagree about who a participant is.
- **The window is arbitrary.** Five sessions is Q23's number, not a measured
  one.
- **No exclusions.** Eligible samples still contain buys that were undone
  within the week. That is the price of not looking ahead.

## What would reverse this

- A registered study that wants to exclude round trippers PIT-safely. The
  backward half of the flag (this leg closes a position opened in the previous
  five sessions) is knowable at entry and could become a rule. That needs
  its own decision, and the forward half never can.
- A reviewed participant alias table (step 3.9). Both round-trip flags should
  then move to the reviewed identity together.
