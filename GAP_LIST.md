# GAP_LIST.md — prioritized gaps

Audit 2026-09-12, commit `45fe5b0`. Severity = damage if left alone, not effort.
Every row cites evidence. Companion to `AUDIT.md` and `DATA_INVENTORY.csv`.

## P0 — existential

| # | Gap | Evidence | Why it is P0 |
|---|---|---|---|
| 1 | **Backup lags the irreplaceable data.** Backups DO run — 29 generations, newest 2026-09-10 17:04 UTC, off-machine, restore drill built in. But **73 archived sessions and 3 commits are not in the newest one**, and those sessions cannot be re-fetched (503). Root cause: `backup.sh` is the **last** of 14 daily stages, so any earlier failure leaves the day unprotected. | `docs/HEALTH.md:36-40` **AT RISK**; `docs/STATUS.md:46` step 1.10 WIRED; `scripts/collect_daily.sh:167` | NSE does not serve this history (`src/common/paths.py:60-70`). The window between collection and backup is exactly where unrecoverable data sits. |
| 2 | **Both DEAD verdicts are memo-only, not registered.** | `docs/reports/ENTITY_VERDICT.md`, `docs/reports/SEASONALITY_POWER.md`; *(inventory g7)* `experiment_registry` = 1 row | The project's whole claim is that findings live in an append-only ledger. Two headline results sit outside it. |

## P1 — correctness that fails silently

| # | Gap | Evidence | Why it is P1 |
|---|---|---|---|
| 3 | **CI is red; 17 unit-tier failures.** 11 = `#!/bin/zsh` script on a Linux runner; 5 = database-dependent tests mismarked `unit`; 1 = stale health fixture. | `pytest -m unit` → 372 pass/17 fail; `head -1 scripts/lib/prune_generations.zsh`; `command -v zsh` → NO | A suite that cannot pass in its own CI has stopped being a gate. |
| 4 | **`vix_regime_multiplier` consumes a series that does not exist.** | `src/research/costs.py:248`; no VIX table in `docs/DATA_INVENTORY.md` | A cost model silently fed a wrong or defaulted VIX widens/narrows every cost estimate with no error. |
| 5 | **`sector_history` is the declared PIT sector source and holds 0 rows.** | `configs/universe.yml` `sectors.source: sector_history` vs *(inventory g6)* `sector_history 0` | Config asserts a look-ahead-free sector source that is empty. Either sector analysis silently degrades or the claim is false. |
| 6 | **Historical price adjustment is inherited and has no classic-event golden test.** | `src/warehouse/spine.py:319` `seed_glob="stock_data_adj/**"`; `grep -rniE "reliance\|tcs\|infy" tests/` → no split test | A bad factor produces a plausible series, not an error. The 4 real-event tests (`test_corp_actions.py:133`) cover 2026 only and are `needs_data`, so never run in CI. |
| 7 | **7,354 unmatched deal events** — the repo calls this "the highest-value work in the project" and it is open. | `configs/universe.yml:8-9` | Until resolved, the tested deal population is a biased subset of disclosures. |
| 8 | **F&O collected but unparsed; `fno_spine` 28 days stale.** UDiFF names none of the legacy 16 columns the same way. | *(inventory g4)* `fno_spine … 28d STALE`; commit `472dfa8` | An invented mapping would silently corrupt 174 M rows. Correctly flagged, still open. |

## P2 — scope gaps vs the intended product

| # | Gap | Evidence | Severity |
|---|---|---|---|
| 9 | **BSE cash equities entirely absent.** No price source; both BSE deal routes 301 → error page. | `configs/sources.yml:89,104` UNPROVEN; no BSE price source anywhere | High — "all NSE+BSE from 2005" is half-delivered. |
| 10 | **Seasonality engine does not exist.** `seasonality_cell` 0 rows, no writer in `src/`. | `grep -rn "seasonality_cell" src/` → only `src/monitor/status.py:651-660` | High as scope; **but** `SEASONALITY_POWER.md` proves the vast version is underpowered by 1-2 orders of magnitude, so the gap is *resolved as infeasible*, not merely unbuilt. |
| 11 | **Quarterly holdings never reconstructed.** `participant_aliases`, `participant_master`, `promoter_entities`, `deal_interpretation` all 0 rows; SHP route UNPROVEN. | *(inventory g6)*; `configs/sources.yml:147` | Med-High — "smart money performance" is deals-only, and deals are prints, not positions. |
| 12 | **USDINR, currency and commodities missing entirely.** | grep across `configs/ src/ docs/DATA_INVENTORY.md` → nothing | Med — explicitly a "later" layer in the brief. |
| 13 | **Delivery %, short selling, fundamentals, macro, option greeks sit in the seed, unused.** | *(inventory g1)*; absent from group 4 | Med — real data already on disk with no pipeline into research. |
| 14 | **No product surface at all** — no UI, API, auth, users, structured logging. | zero framework imports; `pyproject.toml` concedes no structured logging | High for "eventual product", Low for today's single-operator use. |

## P3 — hygiene and risk

| # | Gap | Evidence | Severity |
|---|---|---|---|
| 15 | **Legal/ToS unreviewed for redistribution.** All sources public and unauthenticated, `respect_robots: true`, but the UA is a spoofed Chrome string and there is no licence review, attribution surface or terms file. | `configs/sources.yml:31`; `README.md` disclaims trading, not data redistribution | **High if productised.** NSE/BSE assert rights over derived data; entity-level "smart money" rankings naming real institutions add defamation and SEBI research-analyst exposure in India. MIT covers the code, not the data. |
| 16 | **README is stale** — "540 pass", "51 decision records", "Phase 1 of 9" vs actual 589 / 58 and a closed research phase. | `README.md:10,19,20` | Low technically, Med for trust. |
| 17 | **Hardcoded repo path in the scheduler.** `REPO="$HOME/Workspace/institutional-research"`; this checkout is `MICC_V3`. | `scripts/collect_daily.sh` | Med — the scheduler may be driving a different directory than the audited repo. |
| 18 | **`pyproject` requires ≥3.14; CI pins 3.12.** Works only because CI installs deps directly instead of the package. | `pyproject.toml:5` vs `.github/workflows/tests.yml` | Low-Med — CI does not test the declared interpreter. |
| 19 | **Inert MICCV2 recommendation/order tables carried in the seed** — `recommendations` 555, `oms_orders` 46, `idea_card` 46, `current_signals` 456. Nothing in `src/` reads them. | *(inventory g1)* | Low technically, Med reputationally: `oms_orders` in a repo advertising "no order-placement code exists". |
| 20 | **`python -m src.monitor.status` corrupts `STATUS.md` when run without the warehouse** — exits 0, downgrades 22 steps, writes *"0 observed sessions"* and blank spans. | Verified during this audit and reverted | Med — a generated doc that silently lies is worse than a stale one. |

## Not a gap — deliberate and correct

- **No ML / no self-learning.** `configs/trials.yml` charges every search against a monotonic trial counter. The project measured mass search and rejected it; absence here is a position, not an omission.
- **No buy/sell recommendations.** `pyproject.toml:4`; CI gate `pytest tests -k "order"`.
- **Pooled market-relative seasonality forbidden.** `configs/scan.yml` marks it `FORBIDDEN_IDENTICALLY_ZERO` — max |cross-sectional mean| = 1.698e-17. Refusing to report an undefined statistic is correct.
- **Delisted names retained in research.** `configs/universe.yml delisting.include_in_research: true` — better survivorship handling than most vendors.
