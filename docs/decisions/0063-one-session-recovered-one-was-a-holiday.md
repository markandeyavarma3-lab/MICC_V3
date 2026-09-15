# 0063 — One session recovered, one was a holiday: 0059's gaps corrected

**Date:** 2026-09-15
**Decided by:** Owner, on the evidence of the 20:31 IST collector run the
same evening. Executed at 20:50 IST from the log and the manifest; nothing
was re-fetched.
**Status:** accepted
**Supersedes:** the gap acknowledgements in 0059 (six `acknowledged_gaps`
entries for 2026-09-11 and 2026-09-14). 0059's scheduler decision is untouched.
**Related:** 0053 (why an acknowledgement must match an observed gap), 0060
(the 20:30 slot that did the recovering).

## Context

0059, written at 10:27 IST, acknowledged `nse_bulk_deals`, `nse_block_deals`
and `fii_dii_cash` for 2026-09-11 and 2026-09-14 as permanently lost: the
machine was off from Friday 17:19 to Tuesday 09:33, the deal file is a rolling
current-day snapshot, and the historical route answers 503. Two of those
premises were tested by the first run under the new calendar, at 20:31 IST:

```
  STORED     nse_bulk_deals     session=2026-09-11 rows=218 sha=a86a69b9
  STORED     nse_block_deals    session=2026-09-11 rows=39 sha=85ff5403
  STORED     fii_dii_cash       session=2026-09-15 rows=0 sha=02337817
  ...
  none  2026-09-14  404 on a past date: holiday or no session      (prices)
DERIVATIVES nse_participant_oi: 3 session(s) to fetch  NO_SESSION 1  STORED 2
```

- **2026-09-14 did not trade.** The dated price archive and participant-OI
  feed both return 404 for it. A holiday cannot be a lost session; the
  acknowledgement was a claim about a day that never existed.
- **2026-09-11 bulk and block deals were still being served on Tuesday
  evening.** With no session on Monday and Tuesday's file not yet published
  at 20:31, NSE's "current day" was Friday. The rolling window is not one
  calendar day; it is *until the next publish*. That is a fact about the
  route this project did not know, and it is why the Saturday/Sunday 08:30
  slots in 0060 are worth more than 0060 claimed.
- **`fii_dii_cash` 2026-09-11 is genuinely lost.** `/api/fiidiiTradeReact`
  served 09-15 (0 rows) at 20:31; the manifest holds no 09-11 record and
  tonight's HEALTH.md lists it under permanently missing. It is OPTIONAL in
  `health.py` and never paged.
- `tests/test_health.py::test_the_acknowledged_list_only_covers_gaps_that_are_real`
  had been red since 10:27 for exactly this reason — the entries were ahead
  of the evidence — and is green again after the change below.

## Decision

`configs/sources.yml` `acknowledged_gaps`: the five entries for
`nse_bulk_deals` / `nse_block_deals` 2026-09-11 and all three for 2026-09-14
are **deleted**. `fii_dii_cash` 2026-09-11 **stays**, with its reason
rewritten to say why it alone was not recovered. 0059 carries a one-line
supersession pointer and is otherwise unedited, per the README's rule.

## Why

An acknowledgement silences an alert; 0053 made the rule that it must
correspond to a gap `health.read()` actually observes. Two of the three
feeds for 09-11 now have archived bytes, and 09-14 was never a session, so
five of six entries would have silenced nothing and misled anyone reading
the list. The sixth is a real loss and must keep paging into HEALTH.md's
"permanently missing" table, which is what an acknowledgement is for.

The instruction was to delete all six. Deleting the `fii_dii_cash` 09-11
entry would have turned a documented loss back into an undocumented one;
the evidence, not the instruction, decided that line.

## What would reverse this

- A `fii_dii_cash` file for 2026-09-11 appearing from any route. Then that
  entry goes too.
- Evidence that the 218 bulk / 39 block rows stored as session 2026-09-11 are
  not Friday's deals (the `Date` column in the CSV is the check; the parser
  reads it, and `land` accepted them). Then 0059 was right after all.

## Cost accepted

0059 stood for ten hours saying two sessions were gone when one was
recoverable and the other never existed. The cost is the record itself: a
decision written before its premise was tested, corrected the same day. The
lesson is cheap and specific — *a rolling file rolls on publish, not on the
calendar* — and is now in `sources.yml`'s note for both deal feeds' readers
to find.

No trials. Nothing here touches an estimate.
