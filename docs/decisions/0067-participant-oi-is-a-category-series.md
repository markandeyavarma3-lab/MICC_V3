# 0067 — Participant-wise OI is a category series: one question, frozen before any mean

**Date:** 2026-09-16
**Decided by:** Owner. The cash-deals question is CLOSED (`VERDICT.md`,
exp_002 DEAD). This is the one new question the project is permitted to
ask, and this record freezes it before `src/research/oi_power.py` computes
a single dispersion number and before `scripts/register_exp003.py` writes
the registry row.
**Status:** accepted
**Related:** 0058 (the feed is named FII/DII derivatives positioning, not
flow), 0056 (entity-level attribution is unresearchable; the category IS
the unit), 0003 (portfolio gate), 0028 (bound scales with horizon), 0035
(power on the full universe, effects behind the guard), 0065 (the table is
current to 2026-09-15).

## The question, and what it is not

**Do daily changes in NSE participant-wise F&O open interest — FII, DII,
Pro, Client; index vs stock futures; net long minus short — contain a
category-level signal for the NIFTY that clears the project's existing
power and portfolio gates?**

Not: rank one institution against another (0056 measured that population
does not exist). Not: a copy of the cash bulk-deals study with a new feed
(that verdict is closed). Not: calendar effects (0026 stands).

**This is derivatives positioning, not cash flow.** `configs/sources.yml`
says so in capitals and every artefact of this study says it again: an
open-interest change is a change in *positions held*, which can move
without anyone buying anything today and can be hedging rather than a
view. The hypothesis is about whether that positioning has information for
the index, not about "FII buying".

## Frozen specification (the registry row is this, hashed)

| field | value |
|---|---|
| **hypothesis** | The sign of a category's daily net-OI change on index futures (primary) or stock futures (secondary) predicts the NIFTY 50's forward return: sessions in the top tercile of ΔOI differ from sessions in the bottom tercile at the primary horizon, per category, after multiplicity. |
| **prior** | Weak. Positioning data is widely watched; a large, persistent index-level edge visible in a public daily file would be arbitraged. The honest expectation is a small effect below the project's plausible bound, in which case the correct landing is UNDERPOWERED, not "a hint". |
| **unit of observation** | One session × one category: ΔOI = OI_t − OI_{t−1} of `index_fut_net` (long − short), and separately `stock_fut_net`. **Not a person, not a fund.** `TOTAL` is the market's sum row and is excluded (its net is identically zero). |
| **categories tested** | FII, DII, Pro, Client — four. |
| **signal columns** | `index_fut_net` (primary), `stock_fut_net` (secondary). Options columns are not tested: the table carries no stock-option shorts (migration 0004), so a net cannot be formed symmetrically across index and stock. |
| **data** | `participant_oi` 2014-01-01 → 2026-09-15 (15,359 seed + 280 collected rows, 0065); outcome series NIFTY 50 close, `seed:global_indices_daily` 2007-09-17 → 2026-07-07. Overlap: **3,067 sessions, 2014-01 → 2026-07**. |
| **horizons** | research.yml's `horizons_sessions` [1, 2, 3, 5, 10, 21] and `horizons_months` [3, 6, 12] (63, 126, 252 sessions). **Primary: 21 sessions.** research.yml's 12-month primary is a deal-event rule (0034/0038); a daily positioning series turns over in days and a 252-session label on daily observations overlaps 251/252 of every cohort, which is not a test of anything. Declared here, before measurement, as the one place this study departs from research.yml. |
| **benchmark** | **NIFTY 50 price index** (`seed:global_indices_daily`, symbol `NIFTY50`). Chosen because (a) the signal is index-level, so CHAR_MATCHED — a per-stock characteristic match — has no meaning here; (b) the official NIFTY 500 TRI exists only as archived bytes (`INDEX_TRI/`, decision pending) and is not in the warehouse. It is a **price** index and `benchmarks.py` says so; the dividend leg (~1.2 pp/yr) is a level effect common to both terciles and cancels in a difference. Swapping to the TRI when it lands is a spec change and re-registers. |
| **entry / exit** | Signal observed at session t's close (the file is published after close); position taken at t+1 open; exit at t+1+h close. No same-day close (research.yml `timing.no_same_day_close`). |
| **estimator** | Monthly-cohort mean of forward NIFTY return on top-tercile sessions minus the same on bottom-tercile sessions, per category × signal column; Bartlett serial correction with the lag covering the label overlap (0033). |
| **pass bar (0003)** | Event gate: the tercile difference at 21 sessions clears the serial-corrected MDE *and* the plausible bound, at BH-FDR 5% across the declared tests. **AND** portfolio gate: a long-short index position sized to `costs.yml`'s participation cap on NIFTY futures beats the benchmark net of the full statutory + impact stack over the evaluation period. Both, not either. |
| **kill criteria** | (1) MDE at the primary horizon > plausible bound (0.5%/month × horizon months, 0028) for a category → that category is UNDERPOWERED and is not fitted. (2) An effect that survives only when the position exceeds the participation/liquidity cap. (3) An effect present only at horizons ≤ 5 sessions and absent at 21 → temporary impact, not information. |
| **trial family** | **`TRACK_O_POSITIONING`**, new, `carried: 0`, declared in `configs/trials.yml` by this record. Not TRACK_D_DEALS: a different unit, estimator and outcome series, and 0022's rule that a family is a search space, not a filing cabinet. |
| **test count** | 4 categories × 2 signal columns × 1 primary horizon = **8**, BH-FDR 5%. Robustness horizons are reported, never tested. |
| **confounds** | Index-level, so the deal-study checklist mostly does not apply: **momentum** — APPLICABLE (positioning follows price; the tercile split is computed on ΔOI, and a momentum-neutral check on lagged 21s NIFTY return is reported); **expiry effect** — APPLICABLE (ΔOI mechanically spikes at monthly expiry; expiry sessions are reported separately and excluded from the primary); **market-relative benchmark** — NOT_APPLICABLE (the outcome IS the market); **size / liquidity tiers** — NOT_APPLICABLE (one instrument); **delisting / suspension** — NOT_APPLICABLE (an index does not delist); **industry** — NOT_APPLICABLE. |
| **split** | Formation 2014-01 → 2019-12 (72 months), evaluation 2020-01 → 2026-07 (touched once). Terciles are set on the formation period's ΔOI distribution and held fixed. |
| **what is computed first** | `src/research/oi_power.py`: n sessions per category, monthly-cohort n, cohort SD of forward NIFTY return, serial inflation, single-arm and two-arm MDE per horizon, verdict. **No mean return, no tercile split, no direction.** |

## Decision

exp_003 is registered with the specification above, `spec_hash` computed
by `src/common/hashing.spec_hash`, `trials_before` read from the
`TRACK_O_POSITIONING` ledger counter (0), via a plain `INSERT` — the
registry refuses a second registration of the same id rather than
rewriting it. Then, and only then, `oi_power.py` runs. If every category
is UNDERPOWERED at the primary horizon, that is the landing:
`docs/reports/OI_POWER.md` says so and no fit is run.

## Why

**Why this question at all.** 0058's reason for resuming collection was
that the category-level series is the best entity-attributable
positioning history in the warehouse — twelve years, daily, four
categories. It is the one thing the derivatives feeds were kept for.

**Why power first, again.** 0034 was decided on a number that was later
found to sit on its own detection floor; 0038 and 0043 closed two studies
by measuring their MDE before any effect. The same order here: dispersion
and n are free to look at (0035); a mean is not.

**Why a new family.** Charging this to TRACK_D_DEALS would let 171 prior
deal-study trials set the bar for a study of a different object, and let
this study's trials raise the bar on the closed one. 0023's families exist
to keep search spaces separate.

**Why 21 sessions and not 12 months.** Stated in the table; the point is
that it is stated *now*. Choosing the primary horizon after seeing which
one clears the bar is the abuse the frozen spec exists to prevent.

## What would reverse this

- The NIFTY 500 TRI landing under its own decision: the benchmark line
  changes, the spec re-hashes, and this becomes exp_003 v2 with the v1 row
  kept.
- Every category UNDERPOWERED at 21 sessions with n at its maximum (the
  series cannot grow faster than one session a day): the study is closed
  as unaskable, not parked.
- A category POWERED and fitted, but with the effect only inside the
  expiry-session subset or only at ≤ 5 sessions: kill criterion 3.

## Cost accepted

Eight tests on a family that starts at zero, so the bar is the honest one
for a virgin search. The benchmark is a price index until the TRI lands.
The study does not touch the cash-deals verdict and cannot revive it.

`trials_before = 0`. No effect is estimated by this record or by
`oi_power.py`.
