# 0077 — The headline benchmark is the official total-return index, not a table that never existed

**Date:** 2026-09-19
**Decided by:** Owner, asked directly whether exp_004's market-relative leg
should move to the NIFTY 500 total return before registration. They chose to
move it. The benchmark wiring itself was not a choice — the config had been
naming a table nothing wrote.
**Status:** accepted
**Related:** 0054 (the benchmark panel was specified and unbuilt), 0074 (SHP
bytes before the registration), 0076 (reserved for exp_004's registration,
unwritten), 0035 (dispersion-only power runs are allowed).

## The gap, and how long it was open

`configs/benchmarks.yml` has declared six benchmarks since 2026-08-18 and
named `NIFTY500_TR` its `reporting.headline_index` — the broad-market
comparison every result is supposed to carry. It sourced that benchmark from
`warehouse.benchmark_n500tr`, a cap-weighted-price-plus-dividend-yield
construction, with the note:

> niftyindices' own TRI series is not free-fetchable.

No code in this repository ever wrote `warehouse.benchmark_n500tr`. There is
no such table in the warehouse or the seed. `src/warehouse/benchmarks.py`
recorded this honestly — a declared `UNAVAILABLE` constant, reported in the
output rather than left to be inferred from a short list — and that honesty
is why it survived 33 days: the panel said "five of six" every time it ran,
which reads as a known limitation rather than a thing to fix.

The claim in the note was false. On 2026-09-15 a probe found the official
series answering a POST to `niftyindices.com/BackPage/getTotalReturnIndexString`,
and 32 annual slices were archived by hand. That was bytes, not a collector,
so the series then stopped at 2026-09-10 — a probe is not a collector. On
2026-09-19 it got both: `src/archive/index_tri.py` (one POST per run, 45-day
window, chunked a year at a time for a backfill) and `src/ingest/index_tri.py`
(one row per session, latest slice wins). 7,860 sessions, 1995-01-01 onward,
refreshed nightly, reconciled at zero difference between the top-up and the
backfill on all 27 overlapping sessions.

## Decision

**1. `NIFTY500_TR` is sourced from `collected.index_tri`.** `method:
official_tri` — the exchange's own total-return level, nothing constructed.
`_nifty500_tri_sql()` in `src/warehouse/benchmarks.py` joins the panel, which
now builds five daily series and defers one to the per-event path: six of six,
`UNAVAILABLE` empty for the first time.

**2. `tri`, never `ntr`.** The archive carries both: the gross total-return
level and the net-of-withholding one. `ntr` is NULL on 4,957 of 7,860 rows,
because the host did not compute it before ~2014. Reading it would not fail —
it would silently start the headline benchmark nineteen years late. Pinned by
a test and by a perturbation in both places the column is read.

**3. `UNAVAILABLE` stays as a constant, empty.** The machinery is the point,
not the entry: the next benchmark that cannot be built must be declared and
reported, not dropped from the panel. Deleting an empty guard because it is
empty is how the guard is missing when it is next needed.

**4. `NIFTY50_TR` does not move.** It remains the seed's price index, still
declared `total_return: true`, still reporting its own deviation. exp_003 is
REGISTERED against it and a registered benchmark is frozen. The panel now
holds one series whose total-return claim is true and one whose claim is
false, and both say so.

**5. exp_004's market-relative leg becomes the NIFTY 500 total return.** This
is the owner's decision and the only part of this record that is a judgement
rather than a repair. `mkt_rel` subtracts the market's return from the name's,
and a price index omits dividends — ~1.2%/yr on the NIFTY 500, ~0.3% per
quarter, against exp_004's own plausible-effect bound of 1.5% per quarter. A
fifth of the bound, in the flattering direction, from using a series as
something it is not. CHAR_MATCHED remains the PRIMARY measure; this is the
secondary one, and exp_004 is not yet registered, so nothing frozen moves.
`docs/plan/EXP004_HOLDINGS_REGISTRATION_DRAFT.md` had already promised the TRI
while `scripts/register_exp004.py` said NIFTY 50; they now agree.

**6. The preliminary power run uses the same leg**, imported from the study
module rather than restated, so the preview and the study measure the same
return. A test pins that the market leg is the ONLY thing that file borrows
from the study module — an unrestricted import would be the way around the AST
guard that keeps signal columns out of it.

## What this changed in the numbers

The preliminary dispersion run (0035; random deciles, no signal read) was
re-run the same day on the larger panel and the new leg:

| | 2026-09-18 | 2026-09-19 |
|---|---|---|
| companies | 220 | 449 |
| stock-quarters | 3,092 | 6,749 |
| quarters | 18 | 19 |
| market leg | seed NIFTY 50 price, ends 2026-07-07 | NIFTY 500 total return, current |
| MDE / quarter | 12.05% (8.03x bound) | 9.36% (6.24x) |
| winsorised | 4.89% (3.26x) | 3.39% (2.26x) |

It improves as the sweep brings companies in and is not on a path to 1x.
UNDERPOWERED remains the likeliest landing, which is what the registration
already says.

## What would reverse this

- niftyindices stops serving `/BackPage/getTotalReturnIndexString`, or changes
  the `cinfo` body it parses. The collector records an empty list as FAILED
  with the reason rather than as an empty day, so this surfaces as a stage
  alert within a day rather than as a benchmark that quietly stops advancing.
- Two slices disagreeing on a session. The parser keeps the later slice and
  records `source_file`, so a restatement is visible in the table rather than
  silent; a restatement large enough to matter would mean the series is being
  revised and the level is not a fact.
- A registered study needing `ntr` (net of withholding) — a different series,
  and one the host does not carry far enough back to use here.

## Cost accepted

**`outcome_benchmark_returns` gains a sixth benchmark id on the next nightly
outcomes run.** Additive: no existing row changes and no registered
experiment's definition moves. The table grows by roughly one row per event
that falls inside 1995-2026, which is most of them.

**The panel is now internally inconsistent about what "TR" means** — one true
total-return series and one price index sharing the suffix. Fixing the name
would rename a benchmark exp_003 froze. The deviation is declared in the
panel's own output, as it has been since 0054.
