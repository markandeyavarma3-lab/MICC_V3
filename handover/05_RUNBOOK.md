# 05 — Runbook: exact commands

Every module below has a `main()` and is invoked as `python -m src.<pkg>.<module>`
(no packaging entry points exist). `RESEARCH_ENV` must be set explicitly —
`src/common/paths.py` raises `EnvironmentNotSet` rather than defaulting, by
design (the predecessor once ran a "dev" verification against the prod
warehouse). Values used in this repo: `dev`, `prod`.

**None of this can be run inside a container without `data/` and `db/`
populated.** Set-up first: see §0.

## 0. Environment setup

```bash
git clone <repo-url> MICC_V3 && cd MICC_V3
python3.14 -m venv .venv && source .venv/bin/activate      # project declares requires-python >=3.14
pip install -e .
pip install -e ".[dev]"        # pytest, pytest-cov, ruff — NOT installed by default

# Populate data/ and db/ from the owner's machine — see 06_REBUILD_PROMPT.md.
# There is no seed-download script; data/raw/v1_export + v1_increments (2.5 GB)
# are the irreplaceable predecessor carry and must be copied byte-for-byte.

export RESEARCH_ENV=dev   # or prod — required, no default
```

## 1. Tests

```bash
# Unit tier only — no data/db required. This is what CI runs (Python 3.12
# there vs. the project's declared >=3.14 — a known mismatch).
RESEARCH_ENV=dev python -m pytest tests -m unit -q

# Full suite — requires data/ and db/ populated locally.
RESEARCH_ENV=dev python -m pytest tests -q

# The order-placement guard specifically (what the README's safety claim rests on):
RESEARCH_ENV=dev python -m pytest tests -k "order" -q
```

## 2. Warehouse bootstrap (one-time, after data/ is populated)

```bash
python -m src.common.migrate            # if this module has no main, use migrate.migrate_duckdb / migrate_sqlite directly, targeting db/research_prod.duckdb and db/governance_prod.sqlite
python -m src.warehouse.seed             # carry() — hash-verifies and copies the 2.5 GB predecessor seed
python -m src.warehouse.spine            # build_all() — rebuilds price_spine, price_spine_adj, fno_spine
python -m src.warehouse.reconcile        # the Phase-1 gate, tolerance 0 — must be 20/20 before trusting anything downstream
python -m src.ingest.seed_deals          # land the 20-year deal corpus from the seed
python -m src.identity.master            # build security_master + symbol_history
python -m src.mart.clean                 # build institutional_deals_clean
```

## 3. Daily collection cycle (what `scripts/collect_daily.sh` actually runs, in order)

This is the real pipeline entrypoint — reproduce it manually stage-by-stage if
debugging, or just run the script (macOS/zsh, launchd+cron scheduled 3×/session
at 20:00, 22:30, 08:00 next morning — the morning slot is a genuine catch-up
for a missed evening fetch, not a repeat, because NSE serves only the current
day and does not republish):

```bash
export RESEARCH_ENV=prod
python -m src.archive.stopgap                                    # bulk + block deals, current-day only
python -m src.archive.prices                                     # daily bhavcopy
python -m src.ingest.bhavcopy                                    # -> price spine increment
python -m src.archive.corporate_actions --start "$(date -v-90d +%Y-%m-%d)"   # 90-day trailing window
python -m src.ingest.corp_actions
python -m src.archive.derivatives                                # participant OI + F&O bhavcopy, decision 0058 — collection only
python -m src.archive.insider --start "$(date -v-30d +%Y-%m-%d)" # 30-day trailing window
python -m src.ingest.insider
python -c "
from src.warehouse import spine
import duckdb
c = duckdb.connect()
spine.build(spine.PRICE, env='prod', con=c)
spine.build_adjusted(env='prod', con=c)
"
python -m src.ingest.land          # the ONLY path collected deals enter the database
python -m src.identity.master
python -m src.mart.clean
python -m src.research.charmatch   # rebuild the CHAR_MATCHED characteristic panel BEFORE outcomes
python -m src.research.outcomes    # deal_forward_outcomes — depends on a fresh mart (FK cascade deletes on mart rebuild, decision 0055)
python -m src.monitor.health       # writes docs/HEALTH.md, alerts (desktop + best-effort email)
./scripts/backup.sh                # off-machine backup + prune, run AFTER collection every time
```

Or simply: `./scripts/collect_daily.sh` (hardcodes `$HOME/Workspace/institutional-research`
as `$REPO` — **edit this path for any other checkout location**). Propagates a
non-zero exit code if any stage failed (fixed 2026-09-03; previously always
exited 0 regardless of stage failures).

## 4. Monitoring / status (regenerate the project's self-report)

```bash
python -m src.monitor.status       # regenerates docs/STATUS.md from code + db state — DERIVED, never hand-edit
python -m src.monitor.health       # regenerates docs/HEALTH.md
python -m src.monitor.inventory    # regenerates docs/DATA_INVENTORY.md
python -m src.monitor.backup_state # off-machine backup freshness check (read-only)
```

## 5. Research / study modules

```bash
python -m src.research.measure          # the power grid decision 0034 rests on (regenerates on demand)
python -m src.research.consensus        # multi-institution convergence study
python -m src.research.selling          # the selling study (34,270 events)
python -m src.research.entity_verdict   # exp_002 — entity persistence study
python -m src.research.nullcal          # null-label calibration (permutation test)
python -m src.research.delisting        # delisting/merger recovery-factor pricing
python -m src.research.insider_power    # power analysis on insider-filing populations
python -m src.research.seasonality_power # Engine 2 feasibility arithmetic — no data query, pure power math (already run, VERDICT DEAD, docs/reports/SEASONALITY_POWER.md)
python -m src.warehouse.benchmarks      # rebuild the 6-benchmark daily panel
python -m src.warehouse.participant_oi  # load the F&O positioning proxy (decision 0058)
```

## 6. Pre-registration / governance (run BEFORE any new study reads CONFIRM data)

```bash
python scripts/register_exp001.py           # freezes exp_001's spec (bulk-deal avoidance, already run/killed)
python scripts/register_exp002.py           # freezes exp_002's spec (entity persistence) — uses plain INSERT since 2026-09-12 fix, refuses if ledger is missing/empty/already-identically-registered
python scripts/register_engine2_verdict.py  # records the Engine 2 DEAD verdict as a governance artefact (memo only, no experiment — nothing is going to be run)
```

**Ordering matters**: registration must happen before the study code runs, and
the frozen-spec triggers (migrations 0001+0003 sqlite) will refuse any change
to a spec once `status != 'DRAFT'`, including via `INSERT OR REPLACE`.

## 7. Report build

```bash
python scripts/build_report.py    # Markdown -> PDF via headless Chrome
# Hardcodes /Applications/Google Chrome.app/Contents/MacOS/Google Chrome (macOS only)
# and needs `npm install` in docs/report/build/ for mermaid diagram rendering (network required).
```

## 8. Backup / restore

```bash
./scripts/backup.sh                         # bundle + tarball db/ + data/raw/archive/ + logs/, watched restore drill, prune to 3 generations
# Destination: iCloud Drive (macOS-specific — not portable to another OS without editing the script)
# NOTE: at last audit, data/raw/v1_export (the irreplaceable 2.5GB seed) was
# EXCLUDED from this backup by design (it "should" rebuild from source, but
# the source repos were deleted 2026-09-01). Take a separate cold copy of
# v1_export + v1_increments before relying on backup.sh alone.
```

## 9. Linting

```bash
ruff check .     # pyproject.toml: line-length 100, target py314, select E/F/W/I/UP/B/SIM, ignore E501
```
