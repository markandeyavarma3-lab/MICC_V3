# NEXT_TASKS.md — next 10 agent tasks

Audit 2026-09-12, commit `45fe5b0`. Sequential, small, **data correctness and durability before any surface**.
Each task is executable by a coding agent without further design input.

> **Prerequisite for tasks 1, 4, 5, 6, 7, 8, 9:** a machine with `db/research_prod.duckdb`,
> `db/governance_prod.sqlite`, `data/raw/v1_export/` and Python 3.14. Per `scripts/backup.sh:60`
> that is the owner's Mac. Tasks 2, 3 and 10 run anywhere.

---

### 1. Bring the backup to zero sessions-at-risk, and move it to the front of the day
- **Files:** `scripts/collect_daily.sh` (line 167), `scripts/backup.sh`, `src/monitor/backup_state.py`, new `scripts/register_backup.py`
- **Context:** backups already work — 29 generations, newest 2026-09-10, restore drill included. The defect is **ordering**: `backup.sh` is the **last** of 14 stages, so any earlier failure collects a day and never protects it. `docs/HEALTH.md:36` grades the result **AT RISK — 3 commit(s) and 73 archived session(s) not in it**, and those sessions cannot be re-fetched (503).
- **Do:** run `./scripts/backup.sh` now to clear the 73; then move the backup invocation to run **first** in `collect_daily.sh` (protect yesterday before risking today) and keep a second run at the end; register each snapshot as a `RESULT` artefact via `provenance.register_file` with an edge to the warehouse artefacts it covers.
- **DoD:** `docs/HEALTH.md` "Off-machine backup" section reports **0 archived session(s) not in it**; `backup.sh` appears before the first collection stage; a governance artefact `backup_<date>` exists with ≥1 inbound edge; restore drill prints a matching HEAD.
- **Deps:** none. **Do this before anything else in this list.**

### 2. Port the retention script from zsh to Python
- **Files:** create `src/monitor/prune_generations.py`; delete `scripts/lib/prune_generations.zsh`; rewrite `tests/test_backup_prune.py` to import the module instead of `subprocess.run`
- **Do:** reimplement generation retention in Python, preserving every behaviour the 11 existing tests assert (empty listing never authorises a delete; a glob matching nothing is not an error; the newest run of each kept day survives; the generation just written is never pruned; a stamp absent from the index refuses to delete).
- **DoD:** `tests/test_backup_prune.py` passes on Linux with no zsh installed; the `.zsh` file is gone; `scripts/backup.sh` calls the Python module.
- **Deps:** 1 (do not change backup code before a backup exists).

### 3. Fix test-marker hygiene and the stale health fixture
- **Files:** `tests/test_costs.py` (line 19 `pytestmark`), `tests/test_doc_config_binding.py` (class `TestVerdictMatchesTheEvidence`), `tests/test_health.py:270`
- **Do:** re-mark the 5 database-dependent tests from `unit` to `data` + `needs_data`; remove the stale acknowledgement for `nse_bulk_deals 2026-08-19` that the health test correctly flags as *"not a gap … would silence a future loss."*
- **DoD:** `RESEARCH_ENV=dev pytest -m unit -q` passes with **zero** failures and no database present; the GitHub Actions run on `main` is green.
- **Deps:** 2.

### 4. Register the two DEAD verdicts in the real ledger
- **Files:** `scripts/register_exp002.py`, `scripts/register_engine2_verdict.py` (both already guarded)
- **Do:** run both against `db/governance_prod.sqlite`. If `register_exp002.py` refuses because exp_002 is already registered, **record the refusal and do not force it** — that guard exists because `INSERT OR REPLACE` previously bypassed both freeze triggers (`migrations/0003_registration_replace_is_not_an_amendment.sqlite.sql`).
- **DoD:** `SELECT logical_name, artefact_hash FROM artefact WHERE logical_name LIKE '%verdict%'` returns both Engine 1 and Engine 2 rows; `params_json` on the Engine 2 row contains `final_alpha_candidate_verdict: true`; both hashes printed into `docs/reports/`.
- **Deps:** 1.

### 5. Corporate-action golden tests against classic events
- **Files:** `tests/test_corp_actions.py`
- **Do:** add assertions that the adjusted series is flat on ex-date for ≥6 pre-2020 events — RELIANCE 1:1 bonus (Sep 2017), INFY bonus (2014, 2018), TCS 1:1 bonus (2018), WIPRO bonus, HDFCBANK 1:2 split (Sep 2019). Same shape as the existing 2026 test at `tests/test_corp_actions.py:133` (close/prev ratio within 0.7-1.4).
- **DoD:** all 6 pass against `price_spine_adj`; each cites its ex-date source; a deliberate factor inversion makes them fail (watch it fail once); the spine build refuses on failure.
- **Deps:** 3.

### 6. Close the VIX hole
- **Files:** `src/research/costs.py:248`, new `src/ingest/vix.py`, `configs/sources.yml`
- **Do:** either land a real India-VIX daily series into the warehouse with a recorded date span and add it to `src/monitor/inventory.py`, **or** make `vix_regime_multiplier` raise on a missing/None VIX. No silent default in either branch.
- **DoD:** `grep -n "vix" docs/DATA_INVENTORY.md` returns a row with a span, **or** a test asserts the function raises when VIX is unavailable. Every existing caller updated.
- **Deps:** 3.

### 7. Resolve the 7,354 unmatched deal events
- **Files:** `src/identity/master.py`, `src/mart/clean.py`, `migrations/` (populate `participant_aliases`)
- **Do:** publish the unmatched count before and after; resolve symbol-name mismatches against `symbol_history` + `isin_renames`; every merge must be either rule-derived **with a test** or human-reviewed with a recorded reviewer. **Do not promote `src/research/entity_names.normalize` to the alias table** — its own docstring (`entity_names.py:3`) says it is counting-grade and explicitly not step 3.6.
- **DoD:** unmatched count published in a decision record; `participant_aliases` non-empty with a provenance artefact; `institutional_deals_clean` unresolved-flag rate drops measurably; no merge lacks a test or a reviewer.
- **Deps:** 5.

### 8. Decide `sector_history`: fill it or drop the claim
- **Files:** `configs/universe.yml`, `src/warehouse/`, a new decision record
- **Do:** either backfill PIT sectors from `index_membership` (13,163 rows already carry `effective_from`/`effective_to`) with `backfill_confidence: LOW` honoured and reported separately as the config already requires, **or** change `sectors.source` and cite decision 0057's IMPOSSIBLE finding in-config.
- **DoD:** `sector_history` is non-empty **or** `configs/universe.yml` no longer names it as the source; either way a decision record explains which and why.
- **Deps:** 3.

### 9. Map UDiFF → `fno_spine` explicitly, or freeze F&O
- **Files:** `src/archive/derivatives.py`, `src/warehouse/spine.py:96`
- **Do:** produce an explicit, reviewed 16-column mapping from the UDiFF schema (34 columns) to the legacy `fno_spine` columns, validated on one overlapping session where both formats exist. If no overlapping session exists, mark `fno_spine` FROZEN and record its staleness. **Never infer the mapping** — commit `472dfa8` flagged that UDiFF names none of the 16 the same way.
- **DoD:** a mapping table in code with a test on a real session, **or** `fno_spine` marked FROZEN in `docs/DATA_INVENTORY.md` with the 28-day gap recorded in a decision.
- **Deps:** 3.

### 10. Make README and STATUS tell the truth
- **Files:** `README.md`, `docs/STATUS.md`, `tests/test_doc_config_binding.py`
- **Do:** derive the test count and decision count rather than typing them (the binding test already exists for test count — extend it to decisions); replace "Phase 1 of 9" with the real state (research phase closed, Engine 1 and Engine 2 both DEAD and registered); add an explicit scope line stating NSE-only, cash-only, no BSE/currency/commodities.
- **DoD:** README numbers are test-enforced; `grep -c "540\|51 " README.md` finds no stale figures; a reader learns the scope limits in the first screen.
- **Deps:** 4.

---

## Explicitly NOT next, and why

- **Any dashboard, API or multi-user surface.** Nothing is durable yet (task 1) and the suite does not pass its own CI (task 3).
- **A BSE price collector.** Real and large (gap #9), but it multiplies the data that currently has no backup. After task 1-4.
- **Any new seasonality code.** `docs/reports/SEASONALITY_POWER.md` shows the full-scope scan is underpowered by 1-2 orders of magnitude, and that even at **m = 1 with zero multiplicity correction** a monthly cell needs 219 bps/month against published effects of 50-300 bps. Building the engine would spend weeks to measure its own blindness.
- **Reviving the inert MICCV2 `recommendations` / `oms_orders` tables.** Quarantine them (AUDIT.md §10); do not wire them in.
