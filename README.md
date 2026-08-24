# Institutional Research Platform

Research platform for **disclosed institutional activity in Indian equities** —
NSE/BSE bulk and block deals, FII/DII flows, and calendar seasonality. It studies
whether any of it contains repeatable information.

It places **no orders**, holds **no money**, and has **no live-trading path**.
A test asserts no order-placement code exists anywhere in the repo.

> **In progress — Phase 1 of 9.** Published early on purpose: the findings here
> are mostly expected to be negative, and a platform whose negative results
> appear only after they're safe is not one you should trust.

## Status — 2026-08-23

| | |
|---|---|
| **Phase** | 1 of 9 — skeleton, migrations, warehouse rebuild |
| **Tests** | 336 pass |
| **Decision records** | 37 |
| **Research findings** | One, and it is a rejection: [Finding 001](docs/reports/FINDING_001_bulk_deal_avoidance.md) failed its own pre-registered bar |
| **Predecessor** | [MICCV2](../MICCV2) frozen at tag `frozen-2026-08-16` |

**Two things a reader should know before the numbers below.**

1. **Every SESSION horizon is underpowered; twelve months is not.** Decision
   [0028](docs/decisions/0028-plausible-bound-scales-with-horizon.md) made the
   plausible bound scale with horizon, which put every session horizon 1.7–3.9x
   beyond its detection floor — and, unnoticed for two days, inverted the
   reasoning behind [0004](docs/decisions/0004-horizons-in-sessions-not-months.md)
   that had dropped the long horizons. Detection floors grow with √horizon while
   the bound grows linearly, so long horizons became *easier*.
   [0034](docs/decisions/0034-twelve-month-becomes-the-primary-horizon.md) makes
   **12 months the primary horizon**: measured MDE 5.56% against a 6.00% bound on
   17,988 filtered events. That is **marginal** — a 7% margin, and 0.7% at the
   most conservative lag — and is reported as marginal, never as comfortable.
2. **There is no backup of any kind.** Decision
   [0014](docs/decisions/0014-no-remote-yet.md). Sessions archived from
   2026-08-17 onward cannot be re-fetched at any price, because the historical
   endpoint answers 503.

## Why this exists

The predecessor system, MICCV2, was a working research platform: 486 passing
tests, a 21-year warehouse, verified automation, real write-once ledgers. Its
strategy proved nothing — zero promoted edges across 22 KILL verdicts, a champion
whose trailing-24-month Sharpe was 0.11, and 24 live-forward days of which 9 were
genuinely captured live.

That's a research finding, not a software defect. This rebuild keeps the
discipline and drops the strategy.

## What the audit found before a line was written

The premise was tested on 2026-08-16 against data already held, and it did not
survive:

- **54.8% of bulk deals are same-day round trips.** The most active
  "institutions" are HFT market makers — Graviton 6,748 of 6,748 round-trips,
  HRTI 2,968 of 2,968, Tower Research and XTX both 100%. Block deals are clean at
  0.7%.
- After filtering the churn, 30,771 directional buy events: **1-month −0.12%
  (t = −0.77), 3-month −0.22% (t = −0.81)** market-relative.
- 12-month mean is +7.80% but the **median is −10.68%** and the hit rate 43% —
  right skew, not edge. Moving-block bootstrap: **95% CI [−2.46%, +22.81%]**,
  which contains zero.
- 45% of events were dropped on unresolved symbols and delistings. That was
  read as **naming mismatches, fixable by the identity layer** — and measurement
  on 2026-08-22 falsified it: of 680 unresolved symbols, **0 are recoverable by
  ISIN aliasing and 1 is known to any identity master**. They have no price
  coverage and no resolution route, so they leave the universe
  ([0032](docs/decisions/0032-uncovered-symbols-leave-the-universe.md)) and
  Phase 3 loses its headline justification.

Full detail: [`docs/plan/`](docs/plan/).

## What is being built

Rooms 1–3 only: raw archive, identity layer, clean deal mart, outcome research,
and a seasonality validation layer. **No engines and no paper portfolios** until
something passes its gates.

Four studies are pre-registered for Phase 6, in descending order of expected
value: **consensus** (multiple institutions converging), **selling** (34,270
events, never examined anywhere), **block deals** (cleanest data), and **bulk
buys** (the original premise, run properly — its registration must disclose the
exploratory pass above).

## Standing rules

1. No order-placement code. Not in tests, not commented out.
2. Raw files are never overwritten or deleted.
3. Verification is read-only. A verify command that writes is a bug.
4. Readers never touch a live database file — they read a snapshot.
5. `RESEARCH_ENV` must be explicit; unset fails loudly.
6. Every study is pre-registered, with its pass bar and kill criteria fixed first.
7. The trial counter only increases, and applies to incumbents too.
8. A fix is done when its test has been watched failing.
9. UNKNOWN beats inference.

Each of these exists because its absence caused a specific, documented defect in
the predecessor. They are not aspirations.

## Layout

```
configs/      sources, costs, benchmarks, universe, participants, research
migrations/   forward-only, checksummed SQL
src/common/   paths, hashing, migrations
docs/plan/    the three planning documents + PDFs
tests/        mirrors src/
data/         gitignored — raw archive (immutable) + derived warehouse
db/           gitignored — research.duckdb, governance.sqlite, review.sqlite
```

## Running

```bash
RESEARCH_ENV=dev python -m pytest tests -q
```
