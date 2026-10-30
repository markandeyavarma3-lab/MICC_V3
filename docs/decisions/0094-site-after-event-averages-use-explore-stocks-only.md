# 0094 — The website's after-event averages use EXPLORE stocks only

**Date:** 2026-10-31
**Decided by:** Owner, choosing "EXPLORE stocks only" when asked how the site should handle after-event averages.
**Status:** ACTIVE
**Related:** 0008 (the three-way split), 0035 (dispersion may use the full universe; effect estimates may not), 0092 (exp_004 v3 waits).

## Context

The owner asked for deeper analysis on the local website: a single-stock deep
dive, investor and fund tracking, market microstructure and an event-study
explorer. Three of those would show an average return after an event:

- the explorer (average abnormal path after an insider buy, a bulk deal, a
  pledge change, a results beat);
- a named investor's record after their bulk deals;
- a stock page's average move after its results.

Under 0035 each of those is an effect estimate. Computed across every stock,
they would show the answers to studies that are still pending (post-earnings
drift, the bulk-deal studies, exp_004 v3, the insider study) before those
studies are registered. A number seen cannot be unseen; the studies would lose
their pre-registered standing.

## Decision

- Any averaged after-event return on the site is computed over **EXPLORE-stratum
  stocks only** (`src.research.split.assign`). EXPLORE is the 30% that 0008
  set aside for free looking, uncharged.
- SELECT and CONFIRM stocks still show their events (dates, names, amounts) and
  their raw prices. They never show an averaged after-event return, and they
  never feed one.
- Every such number on the site says it is exploratory, not pre-registered, and
  shows its sample size.
- The site describes; it does not rank. No scores, no signal lists, no
  good/bad labels on stocks (owner, same day).
- **Where they may appear.** The website plan's line (§1, §3.2, §3.3: "Prices
  are shown, never returns after events") stands for every ordinary page; it
  was written for a public site. Asked again once the site became local only,
  the owner chose a walled-off section: after-event returns appear only in a
  separate **Research lab** section, from its own data folder (`lab/`). The
  export test keeps banning return-like fields everywhere outside `lab/`.
  The section is marked as one that must be removed before any publishing.

## Why

0008 built EXPLORE so that looking would be free and the confirmation half
would stay untouched. A website that averages across all stocks would be the
largest uncharged look the project has ever taken, made by a page rather than
by a study.

## What would reverse this

Every pending study that uses these events having been read, or retired by a
decision record. The relevant averages could then include the strata those
studies no longer need.

## Cost accepted

- The explorer works on about 30% of stocks, so its averages are noisier by
  roughly √(10/3) than a full-universe figure.
- A visitor to a SELECT or CONFIRM stock sees less than one to an EXPLORE stock,
  and the page has to say why.
