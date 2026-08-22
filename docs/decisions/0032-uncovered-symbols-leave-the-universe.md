# 0032 — Symbols with no price coverage leave the universe

**Date:** 2026-08-23
**Decided by:** Owner, on a measurement that falsified a plan assumption
**Status:** ACTIVE

## Context

Plan 1 §1.3 **Finding D** is the justification for Phase 3 being the
highest-priority phase at four weeks:

> *"the 7,354 misses are **symbol-naming mismatches** between the deal feed and
> the price spine, not survivorship. Fixing the identity layer converts most of
> them into usable events."*

Measured 2026-08-22 against the rebuilt spine, that is **false**.

| | rows | share |
|---|---:|---:|
| deal rows (bulk + block) | 235,880 | |
| resolve on symbol | 215,349 | 91.30% |
| fail | 20,531 | 8.70% |
| …rights entitlements, already out of universe ([0015](0015-rights-entitlements-excluded.md)) | 1,401 | |
| **unresolved** | **19,130** | **8.16%** |

The recovery numbers are the finding:

- **0 of 680** unresolved symbols are recoverable by ISIN aliasing.
- **1 of 680** is known to *any* identity master — `isin_master` (3,735 rows) or
  `stock_registry` (2,382).

There is nothing to map these symbols *to*. The identity layer cannot convert
them, because conversion requires a target that does not exist.

### What they are, and what could not be established

93% first appear in **2018 or later** (634 of 680; only 3 pre-2012) — the inverse
of the resolved population, which skews pre-2012. The names are One Click
Logistics, Debock Sale & Marketing, Bright Solar, ASL Industries, A&M Jumbo Bags,
Nirman Agri Genetics, MOS Utility.

That profile points at **NSE Emerge / BSE SME platform listings**, and the
verification was attempted and **did not conclude**. `bse_scrip_master` does carry
a usable `segment_guess` (544 `sme` against 10,207 `mainboard`), but the
unresolved companies are largely absent from it entirely — ONECLICK, BRIGHT
SOLAR and MOS UTILITY all return zero matches. That is consistent with NSE Emerge
listings, and the seed holds no NSE SME master against which to check.

**So "these are SME listings" remains a plausible explanation, not a
demonstrated fact**, and this record does not rest on it.

## Decision

A symbol with **no price history in the spine and no resolution route through any
identity master** is excluded from the research universe, flagged
`uncovered_symbol`, and reported as an explicit exclusion count alongside every
study — never silently dropped.

## Why

The decision rests on coverage, which is proven, rather than on the SME
explanation, which is not. An event on a security with no price series has **no
forward return to measure**, whatever the reason for the gap. That is structurally
identical to the rights-entitlement case that [0015](0015-rights-entitlements-excluded.md)
already excludes on exactly this ground.

Options rejected:

- **Keep them, report with and without.** Honest, but the Phase 3 gate
  (unresolved rate < 5%) then fails permanently on rows that can never be
  resolved, blocking the outcome study on a condition nothing can satisfy.
- **Source SME price history.** Restores the events in principle. NSE does not
  serve this retrospectively — the same 503 that makes the daily collector
  time-critical — so it is speculative work with no guaranteed outcome, against a
  2026-11-30 checkpoint.

## What would reverse this

An NSE Emerge price series covering 2018+, from any route. That would convert
these from uncovered to merely unmapped, and the identity layer could then do
what Finding D claimed. It would also settle the SME question.

## Cost accepted

- **8.16% of the deal corpus leaves the study**, and the Phase 3 gate now passes
  by *exclusion* rather than by *resolution*. Every study must say so in those
  words; a gate that passes because the failing rows were removed is not the same
  claim as a gate that passes because they were fixed.
- The excluded events are **not random**. They concentrate in small, recently
  listed companies, so the universe is now explicitly a mainboard universe and
  any finding generalises only there. Small-cap institutional activity is exactly
  where an edge is most plausible, so this removes some of the most interesting
  data in the corpus.
- **Phase 3 loses its headline justification.** It remains necessary for PIT
  sectors, participant classification and delisting/merger handling, but the
  "recover 7,354 events" premise is dead and the four-week estimate built on it
  should be re-cut. Plan 1 §1.3 Finding D must be corrected rather than left
  reading as fact.
