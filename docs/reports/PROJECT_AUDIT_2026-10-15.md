# Project audit — 2026-10-15

A full check of the institutional-research project and its public-site
companion (`deal-lens`): what exists, whether it runs, whether the pieces are
connected, what was broken and what was fixed. Every figure below was measured
on 2026-10-15, not copied from earlier reports.

## 1. In brief

- **The machine works.** Every scheduled job ran cleanly on each evening the
  Mac was on (13 and 14 October: 32 of 32 stages, twice a day). Every feed is
  current to the last session (14 October). The off-machine backup is current.
  1,132 automated tests pass (two skipped by design).
- **The research is finished for now, by design.** All six registered
  experiments have verdicts; none found repeatable information at the
  project's bound. Three series are waiting on time and are scheduled for
  re-measurement (2027). One new forward test, exp_006, is built, rehearsed and
  waiting for the owner's "approve" before about 3 November.
- **The public site is built and complete** (five parts, 10 sections, 4,287
  stock pages, 33,029 participant pages, 2,176 fund-scheme pages, every
  cross-link resolves) but **not published**: the GitHub repository does not
  exist yet.
- **The audit found one serious governance gap** — the trial ledger never
  recorded the primary tests of four experiments — plus three smaller faults.
  The small ones are fixed. The ledger fix is prepared and rehearsed but, being
  an append-only write, waits for the owner (§8).

## 2. What the project is

A pre-registered research platform on Indian institutional disclosures: bulk
and block deals, FII/DII flows, participant-wise derivatives positioning,
shareholding patterns, insider trades, mutual-fund portfolios. It asks whether
any of these disclosures carries repeatable information about later returns,
under rules fixed before looking (write-once registry, hashed specifications,
family-wise trial counting). Paper research only: no orders, no live trading.

| | research repo | site repo (`deal-lens`) |
|---|---|---|
| purpose | collect, store, test | show the data, descriptively |
| code | 103 Python modules, 28,027 lines | Astro 5, 10 sections |
| tests | 92 files, 15,217 lines, 1,132 tests | built nightly; link check below |
| history | 251 commits since 2026-08-16 | 9 commits |
| decisions | 89 records, all indexed | — |
| data on disk | archive 2.0 GB, warehouse 6.1 GB, databases 951 MB | 380 MB of page data |

## 3. The pipeline, and what runs it

```
NSE / NSDL / SEBI / fund-house sites
   │  archive: bytes as served, gzipped, sha256-deduplicated, one manifest row per fetch
   ▼
data/raw/archive  (22 source folders)
   │  ingest: parse into tables
   ▼
data/raw/collected  ──►  warehouse (price spine, adjusted spine, benchmarks, universe)
   │                              │
   ▼                              ▼
research database: deals mart, identity, participants, outcomes
   │
   ├──► research modules (power, studies) ──► governance db (registry, ledger, results)
   └──► site export ──► deal-lens/public/data ──► Astro build ──► (GitHub Pages, once the repo exists)
```

| job (launchd) | when | what | state |
|---|---|---|---|
| `collect` | 18:30 and 21:00 daily | 32 stages: deals, prices, F&O, flows, OI, indices, corporate actions, insider, filings, spine, universe, mart, outcomes, health, backup, site | loaded; last two days ALL CLEAN |
| `shp` | 18:45 daily | shareholding filings sweep and parse, named holders | loaded; clean |
| `results` | 21:20 daily | quarterly results backfill (90 min), mutual-fund portfolios, site rebuild | loaded; clean when it ran |
| `bot` | always on | Telegram status bot | running; see §8 |

All four installed job files are byte-identical to the copies in the repo.

**Wiring check.** Every module in `src` was traced through the import graph.
All collectors, parsers, warehouse builders, the mart, outcomes, the site
export and the bot are reached from a scheduled job. Three power previews run
from `configs/remeasure.yml`. The rest are run by hand on purpose: one-off
studies (avoidance, consensus, selling, seasonality, FPI and OI power), the
inventory and status generators, and two one-time loaders. Nothing is
orphaned, and every module has tests.

## 4. Data held, and how fresh

| data | latest | size |
|---|---|---|
| bulk/block deals (mart) | 2026-10-14 | 243,929 deals |
| raw price spine / adjusted spine | 2026-10-14 | 7.84 M rows each |
| F&O spine | 2026-10-14 | 175.7 M rows |
| participant-wise OI | 2026-10-14 | 15,739 rows |
| FII/DII cash flows | 2026-10-14 | daily, 3 sessions lost and recorded |
| benchmarks (six, incl. NIFTY 500 TRI) | 2026-10-14 | 28,230 rows |
| index closes / NIFTY 500 TRI | 2026-10-14 | 147,979 / 7,877 rows |
| insider trades | 2026-10-14 | 6,316 collected rows (+ seed) |
| corporate actions | 2026-10-13 | 1,932 |
| shareholding filings / named holders / promoters | 2026-10-12 | 1.76 M / 1.01 M / 0.67 M rows |
| quarterly results | 2026-09-30 | 5,545 quarters, 747 companies (backfill continues) |
| mutual-fund portfolios | 2026-09-30 | 1.67 M holdings, 17 fund houses, back to 2015-12 |
| deal outcomes | capped at 2026-08-31 | 52,365 — **by design**, see below |

Deal outcomes stop at 2026-08-31 on purpose: `measure.REPRODUCIBILITY_HORIZON`
freezes them so every published figure reproduces; moving it is a recorded
decision, not a refresh.

**12 October** was missed entirely (the Mac was off or asleep on 11 and 12
October). Every feed recovered it from dated archives on the 13th except
FII/DII, which NSE serves for the current day only; that loss is now recorded
in `configs/sources.yml`.

## 5. The research record

| experiment | question | verdict |
|---|---|---|
| exp_001 | Does avoiding stocks with bulk-deal selling help? | REJECTED — failed both holdouts (+0.24%/yr, t 3.11, below the +0.25% bar; test half −0.02%) |
| exp_002 | Do particular entities' deals persist? | REJECTED — no top-tier entity passed BH-FDR 5% |
| exp_003 | Does a participant category's derivatives positioning predict returns? | UNDERPOWERED, closed — every category 4.05x short of its bound |
| exp_004 | (retired: registered by a probe without the owner, 0076) | RETIRED UNRUN |
| exp_004 v2 | Do quarterly changes in FPI / foreign / MF holdings predict returns? | UNDERPOWERED — 2.4x, 2.0x and 1.12x short |
| exp_005 | Does a wide signal search work out of sample (2016+)? | NO_SEARCH_SKILL — no top-N passed after BH |

Decision 0089 re-measured every verdict on the corrected price spine; none
changed.

**Waiting, scheduled** (`configs/remeasure.yml`, flagged in the daily digest 30
days before due):

| series | why it waits | next look | reaches its bound |
|---|---|---|---|
| promoter insider sells | 1.13x short at 12 months | 2027-09-15 | ~2029 |
| MF holding change, quarterly | 1.12x short at 63 sessions | 2027-10-15 | ~2028 |
| MF holding change, monthly (new, 2026-10-15) | 1.12x short at 21 sessions | 2027-10-15 | ~2029 — no shortcut over the quarterly route |
| exp_006 forward health (once registered) | counts only, never an IC | 2027-11-03 | read ~2034 |

**exp_006**, built 2026-10-11: freezes the 100 factor-neutral selections from
the 2005–2026 grid and scores them only on sessions after 3 November 2026; one
read at 96 forward blocks (~2034), pass bar t >= 2.234 (one-sided Šidák over
the family's four tests). Rehearsed: spec hash d5791fbb, selection reproduces
exactly. The 100 are mostly momentum, volatility and reversal composites, so a
pass would most likely mean known factor families persisted. **It needs the
owner's "approve" before about 3 November** — and the ledger fix in §8 first.

## 6. Governance

- **Registry:** six rows, every one with a final status and a reason; every
  spec stored row reproduces its hash.
- **Ledger (`family_charge`):** see §8 — incomplete until the backfill runs.
- **Decision records:** 89, all indexed in `docs/decisions/README.md`.
- **Security:** no credential pattern in any tracked file; the three secret
  files (`~/.micc_kite`, `~/.micc_kite_token`, `~/.micc_telegram_token`) are
  mode 600; Kite data is read by nothing the site exports (a test pins it).

## 7. The public site (`deal-lens`)

Five parts built (who owns what, market structure, fundamentals, screener and
search, mutual-fund portfolios). The audit followed every link type in the
page data — search to page, screener to stock, stock to fund, fund to stock,
stock to holder, participant to stock, deal to participant — over the indexes
and samples of every page type: **no broken link**. The site rebuilds every
evening. It is **not public**: `site_publish.sh` reports "NOT published: no
origin remote" until the owner creates the `deal-lens` repository.

## 8. Findings

### Fixed today

| # | finding | fix |
|---|---|---|
| 1 | Every JSON source logged `rows=0` — FII/DII every day since August, with both rows present. The data was always stored and reached the site; the log line was wrong, and it is the line that would hide a genuinely empty day. | `stopgap._row_count` counts JSON records; test added. |
| 2 | The 12 October FII/DII session was an open gap in health. | Recorded as lost, with the reason, in `configs/sources.yml`. |
| 3 | (earlier this week) The scan universe stopped at the seed's June 2026 rebalance; the panel, benchmarks and exp_006 would have used June's membership indefinitely. | `src/warehouse/pit_universe.py`, the seed's rule matched to the rupee, nightly (commit 75acc99). |
| 4 | (earlier this week) A results filing with no XBRL file ("-") tripped the sweep's breaker and ended a night after 73 companies. | Skipped; 404s no longer count (2295be4). |

### Found, prepared, waiting for the owner

**The trial ledger is missing the primary tests of four experiments.**
`family_charge` records the exploration charges and exp_004's three tests, and
nothing for exp_001 (2 tests), exp_002 (24), exp_003 (8) or exp_005 (3
configurations): their run paths never called `families.commit_charge`. So:

| family | counter now | should be | bar for the next test |
|---|---:|---:|---|
| TRACK_D_DEALS | 215 | 241 | \|t\| >= 3.84 |
| TRACK_O_POSITIONING | 0 | 8 | \|t\| >= 2.77 |
| TRACK_S_PROCEDURE | 0 | 3 | \|t\| >= 2.39 |

No verdict changes — all four experiments are already rejected — but every
future test in those families would have faced too low a bar, and exp_006
would have been stored with "trials before: 0". `scripts/
backfill_family_charges.py` writes the four charges, each marked as recorded
late; it was rehearsed on a copy and produced exactly the table above. The
ledger is append-only, so it waits for an explicit go-ahead
(`--commit`).

### Known and accepted

- **The bot restarts at boot.** It exits when it starts before the network is
  up (23 times in its log, all at boot or wake) and launchd starts it again;
  it has run continuously since. A network-wait loop is deliberately not added
  — the owner asked for no power, sleep or network-wait code in the project.
- **118 pre-existing lint findings** in older files; ruff is not a gate here.
  Every file changed since 2026-10-10 is lint-clean.
- **Coverage gaps by source**, all recorded: Kotak and Bandhan refuse
  automated browsers; Axis, UTI, Franklin and HSBC portfolios are not yet
  mapped; nine sessions in 2026 are permanently lost (rolling endpoints);
  BSE deals are unproven.
- **STATUS levels:** 46 verified, 10 wired, 8 built-but-unconsumed, 13 not
  started (mostly Phase 7 seasonality, deliberately not built after its power
  verdict), 2 impossible (historical deal backfill: NSE answers 503).

## 9. What the owner decides next

1. **Go-ahead for the ledger backfill** (§8) — needed before exp_006.
2. **exp_006: "approve" to register**, before about 3 November.
3. **Create the `deal-lens` GitHub repository** to publish the site, and check
   NSE's data terms before it goes public.
4. The site's name.
