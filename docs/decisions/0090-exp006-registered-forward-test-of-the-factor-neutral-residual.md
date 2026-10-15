# 0090 — exp_006 registered: a forward test of the factor-neutral residual

**Date:** 2026-10-15
**Decided by:** Owner. Offered register / lapse / decide later (2026-10-11) they
chose "Register it"; asked for the pass bar, they left it to the build ("choose
the one which gives best output"); on 2026-10-15, after the audit, they wrote
"commit the changes and approve".
**Status:** REGISTERED
**Related:** 0085 (exp_005), 0086 (b), 0089 (re-measure), the audit
(`docs/reports/PROJECT_AUDIT_2026-10-15.md`), `docs/plan/EXP006_FORWARD_RESIDUAL_DRAFT.md`.

## What is registered

`exp_006_forward_residual`, family TRACK_S_PROCEDURE, registered 2026-10-15
22:26 IST at commit c8c0f38.

| | |
|---|---|
| spec_hash | d5791fbb639c7d7c5966b072449df3118d5fe6c4a9b37aad7689caa1c2187d23 (25 fields; the stored row reproduces it) |
| selection | 100 three-signal composites, keys and signs in the spec; sha256 a7d592f2…, identical to the 2026-10-11 rehearsal |
| training data | 2005-01-03 .. 2026-10-01, grid prices_hash 461f6e5d538b9a58 |
| scored | signal dates from the 22nd session after 2026-10-01 (~2026-11-03) only |
| read | once, at 96 complete 21-session blocks (~2034); a yearly health check shows counts, never an IC |
| pass bar | t >= 2.234 (one-sided Šidák over the family's four procedure tests) AND mean block IC >= 0.015 |
| kill | < 80 blocks with >= 100 names: UNDERPOWERED; > 20% of the 100 not computable: UNREADABLE |
| trials_before | 3 — after the late charges recorded the same evening |

## Why the bar is 2.234

The owner left the choice. It was not chosen by which bar is likeliest to pass;
that would void the test. One-sided because every selected sign is frozen;
Šidák over four because each test in a family raises the bar. 1.645 would
ignore the family; the family's two-sided 2.49 tests a direction already fixed.

## What was fixed before it could be registered

- The scan universe stopped at the seed's 2026-06-25 rebalance; it now extends
  monthly by the seed's own rule (`src/warehouse/pit_universe.py`).
- The selection's data had no fingerprint; it now carries its own manifest.
- Forward signals need seven years of history (five-year seasonal signals).
- The family ledger was missing exp_001/002/003/005's primary tests; the late
  charges were written first, so this row records trials_before 3, not 0.

## Prior, stated before any forward session

Weak. The 100 are mostly momentum, volatility and reversal composites;
neutralising two factors did not remove their families. A pass would most
likely mean known factor combinations kept a residual. UNDERPOWERED, or a
marginal result, is likely.

## What would reverse this

Only the kill criteria, measured at the read. A source retiring shows up in
the yearly health check long before 2034.

## Cost accepted

- **One trial** in TRACK_S_PROCEDURE: the family's next test faces a stricter bar.
- **About eight years of waiting** for one read, and a likely UNDERPOWERED or
  marginal answer.
- **The selection is fixed on today's data.** Any later correction to prices
  before 2026-10-01 does not move the 100; the manifest says which data they
  came from.
