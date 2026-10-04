# 0083 — One participant per cleaned name, and the owner rules the rest

**Date:** 2026-10-02
**Decided by:** Owner ("yeah start doing them"), building Plan 3 steps 3.6,
3.9, 3.10 and 3.12 under the identity rules already decided in Plan 1 §6.4:
Q19, Q20 and Q21.
**Status:** accepted
**Related:** 0058 (`entity_names.normalize`), 0057 (the cost of raw-spelling
identity), 0049 (read before destroying), 0080 and 0081 (the flags that would
move to this identity).

## Context

`participant_master` and `participant_aliases` were in the schema and empty.
Every count of "institutions" keyed on the raw spelling. "SBI Mutual Fund."
and "SBI MUTUAL FUND" were two institutions. Nothing grouped a fund house's
scheme accounts, and the 1,515-name review queue had no tool.

## Decision

1. **Cleaning gives one participant per cleaned name** (Q19), using
   `entity_names.normalize`, the one rule the counterparty counts already
   use. 29,677 raw spellings become 27,772 participants, and 1,534 of them
   carry more than one spelling.
2. **Classification order:**
   - the owner's ruling;
   - then behaviour (PROP_HFT, measured over all of a participant's
     spellings together);
   - then the participants.yml name patterns, in file order;
   - then UNKNOWN.

   An UNKNOWN with 6 or more deals is queued for review. 681 are queued, by
   rupee deal value.
3. **Likely duplicates are suggested and never merged** (Q20). Two
   conservative tests are used: the same words in a different order, and at
   most 2 character edits on names of 10 or more characters. Only pairs where
   one side has 6 or more deals are suggested. 656 are open. An ACCEPT folds
   the smaller into the larger on the next build; a REJECT is never suggested
   again.
4. **Rulings are keyed on the cleaned name, never on `participant_id`**, which
   is reassigned on every rebuild. They live in `review_<env>.sqlite`, are
   mutable, and keep their time and note. The table is rebuilt nightly, so a
   ruling takes effect that evening.
5. **Fund houses come from a manual file** (Q21), `configs/fund_houses.yml`:
   32 AMCs, 658 participants grouped. A renamed house is one group (Reliance
   → Nippon India, IDFC → Bandhan, DSP BlackRock → DSP), and the file marks
   each rename for the owner to confirm. A merger of two houses is two groups
   (L&T stays apart from HSBC). Groups are AMCs, not conglomerates, so SBI
   Mutual Fund and SBI Life are not one group. The file's status is
   `proposed`.
6. **Nothing downstream reads `participant_id` yet.** The mart's PROP_HFT
   rule and both round-trip flags still key on the raw spelling. Moving them
   changes every eligible sample, so it is a separate decision.

## Found on the way

The `INDIVIDUAL` name pattern in participants.yml (Plan 1 §6.5) matches **any
name of two or three words**. "ZZYX HOLDINGS" is an individual under it, and
so is "PASTEL CAPITAL". 18,976 participants carry INDIVIDUAL, all at
confidence LOW. Some are companies, and none is reviewed. This is recorded
here and in the confidence grade, not silently fixed: the pattern is the
plan's, and changing it moves names out of the queue's sight.

## Cost accepted

- **No fuzzy matching, so some real duplicates stay apart** until someone
  rules. Hiding a finding is recoverable; inventing one by merging two
  institutions is not (0058's asymmetry).
- **The INDIVIDUAL pattern over-claims** (above).
- **The queue is long.** 681 type rulings and 656 merge suggestions is weeks
  of five-minute sessions. It is worked by rupee value, so the first few
  batches cover most of the money.

## What would reverse this

- A study that needs participant identity (consensus, persistence). The mart
  then moves to `participant_id`, and that move is its own decision with the
  N reported both ways.
- A reviewed audit of the INDIVIDUAL pattern that finds companies in it at a
  material rate. The pattern would then be tightened by a decision, with the
  queue size before and after.

## Measured 2026-10-04: what moving the mart to participant_id would change

| | raw spelling (today) | participant identity |
|---|---:|---:|
| participants | 29,645 | 27,772 |
| PROP_HFT | 332 | 306 |
| same-day round-trip stock-days | 81,390 | 81,402 |

Merging spellings makes 26 names look less like pure round-trippers and
moves round trips by 12. **The mart stays on raw spellings**: no live study
reads these flags, and a switch is its own decision when one does.

**What it showed instead.** Of the 5,980 deals the mart marks eligible as
institutional events:

- **1,581 are participants typed INDIVIDUAL and 1,567 are UNKNOWN**, more
  than half between them;
- 1,275 are FPI_OFFSHORE, 532 MUTUAL_FUND, 248 BANK, 226
  FOREIGN_INSTITUTION, 179 PENSION_SOVEREIGN, 175 INSURANCE and 173
  BROKER_SEC.

Track D's verdicts are closed and this does not reopen them, since a sample
polluted by non-institutions dilutes toward the null they returned. **Any
future deal study must declare which participant types count as
institutional**, now that the types exist.
