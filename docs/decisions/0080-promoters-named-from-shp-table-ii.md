# 0080 — Promoters named from SHP Table II, point in time, flags only

**Date:** 2026-09-30
**Decided by:** Owner ("build whats next"); the step is Plan 3's 3.11 and 4.4,
unbuilt since the plan was written.
**Status:** accepted
**Related:** Plan 1 §6.6 (the promoter list) and §7.1 (the two flags), 0074
(the SHP sweep that supplies the filings), 0055 (a foreign key that froze the
mart), 0058 (`entity_names.normalize`).

## Context

`institutional_deals_clean` has carried `promoter_related_flag` and
`internal_transfer_flag` since Phase 4, FALSE on every row, because no list
of promoters existed. A deal by a company's own promoter is not institutional
activity. It is the owner selling down or moving shares between family members
and holding companies. Measured before building (any-date name match, so an
upper bound): 1,435 of 30,713 otherwise-eligible sells and 668 of 12,850 block
deals are a promoter of the same company.

Every shareholding-pattern filing names its promoter-group holders in Table II.
The SHP sweep had already archived 26,319 of those filings; nothing read the
names.

## Decision

1. **Source: the named holders in the Table II XBRL axes.** The eight axes in
   `src/ingest/shp.py::PROMOTER_AXES` were chosen by measurement, not from
   the taxonomy's labels. On 3,000 random filings the named holders sum to the
   filing's own Promoter total within 0.15pt in 2,935 of 2,938. The other 36
   report no promoter holding at all. `DetailsOfSharesHeldByFinancialInstitutionOrBanks`
   is excluded: in the 2018–2022 taxonomy it is also the PUBLIC
   financial-institutions line.
2. **Point in time on the broadcast date.** An entity is a promoter of a
   security from the broadcast date of the first filing naming it until the
   broadcast date of the first later filing that does not. The quarter-end is
   not used: excluding a deal because of a filing published after it is a
   look-ahead.
   - A filing whose promoter total is above zero but which names nobody is
     skipped (167), not read as the promoters leaving.
   - An omission published on or before the listing it would end is older
     news and is ignored (6,653).
   - Overlapping runs of one entity are merged into one.
3. **Exact match after `entity_names.normalize`.** Nothing fuzzy is used.
   Missing a real promoter under-flags, which can be recovered. Flagging a
   stranger as a promoter cannot.
4. **Flags only; eligibility is unchanged.** Whether a study excludes promoter
   deals is a registration decision. Removing them from inside the mart would
   change every study's sample without one.
   - `internal_transfer` is a promoter-related deal with a DIFFERENT promoter
     of the same security on the opposite side in the same session.
5. **The identity rebuild empties `promoter_entities` first.** The table
   references `security_master`, and DuckDB refuses a master delete while
   children exist. That is 0055's frozen mart again. `src/identity/promoters.py`
   runs straight after identity and before the mart, and rebuilds the table
   whole.

## First build (2026-09-30)

| | |
|---|---:|
| filings read | 26,282 |
| securities with a list | 1,479 |
| promoter entities / validity runs | 42,339 / 45,847 |
| ISINs with no security_master row | 135 |
| deals with a promoter list in force | 43,738 (18.1%) |
| `promoter_related` | 993 |
| of which eligible (buys) | 31 |
| `internal_transfer` | 199 |

993 is below the 2,374 any-date upper bound. The difference is
point-in-time: filings reach bulk coverage only from 2021, and most deals
(back to 2006) predate every filing for their company. Those deals read FALSE
for want of a list, and `list_in_force` says which ones those are.

## Cost accepted

- **Lag.** A promoter who first appears mid-quarter is not flagged until a
  filing publishes it.
- **Under-flagging.** A promoter spelled differently in a deal (initials,
  a missing middle name) is missed.
- **Older deals.** About 82% of deals, mostly before 2021, have no promoter
  list in force and read FALSE for want of evidence.
- **Nightly work.** The identity stage now empties one more table, and a
  failed promoters stage leaves every flag FALSE until the next run. The
  mart's report says so in capitals.

## What would reverse this

- The sweep reaches 95% (0074). Coverage rises and the counts with it. The
  table is rebuilt nightly, so no action is needed.
- A registration that studies sells. Promoter sells are the case this exists
  for, and that registration must say whether it excludes them.
- Evidence that exact matching misses a large share, such as initials in deal
  names. The remedy is a reviewed alias table (step 3.9), not fuzzy matching.
