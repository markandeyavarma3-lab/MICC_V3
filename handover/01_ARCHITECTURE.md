# 01 — Architecture, as it actually exists (not as planned)

Sources: `src/` (read via AST — every module docstring + function/class signature
extracted, see `code_map.json`), `docs/STATUS.md` (derived 2026-09-11 at commit
`472dfa8`), `docs/reports/VERDICT.md` (2026-09-10, closing verdict), decisions
0055–0058 (most recent), and `AUDIT_README.md` (external audit, 2026-09-02,
commit `f79ac5d` — **treat as historical**, 20 commits behind HEAD; several of
its CRITICAL findings — the `land()` crash (BUG-1), the `status.py`
self-reference bug — read as fixed in the later `STATUS.md` and are noted as
such below).

## 1. What this project is

A solo research platform testing whether **disclosed institutional activity in
Indian equities** (NSE/BSE bulk & block deals, FII/DII cash flow, F&O
participant OI) contains information a disciplined observer could have traded
on. No live trading, no order-placement code, no broker integration. Python
3.14, DuckDB (derived marts) + SQLite (append-only governance ledgers with
enforcing triggers), pandas/numpy/scipy, parquet on local disk. No frontend,
no API, no server. Scheduling via macOS `launchd` + cron (`scripts/collect_daily.sh`).

**The headline result (docs/reports/VERDICT.md, 2026-09-10): the core question
is answered "no" and closed.** 0 of 15 (population, horizon) pairs reach
pre-registered statistical power. The one large-looking effect (sells, −22.7%
at 12mo) is confounded (strongest in untradeable names, fails liquidity and
survivorship checks). The one "skilled" participant is a passive ETF measured
over two months — a leaderboard artifact. A second track (seasonality, "Engine
2") was killed on pure power arithmetic before touching any data (a calendar
cell fires once a year; 21 years of history can never reach the observation
count needed at any multiplicity correction).

**What is still active (as of the last 3 commits, 2026-09-11/12):**
- **Decision 0058**: F&O participant-OI and bhavcopy *collection* resumed
  (deliberately collection-only, no parsing/analysis) as the best
  entity-attributable flow series available, now that decision 0056 showed the
  deals track cannot support entity-level ranking (only 7 participants reach
  12 months of activity).
- **Governance hardening**: the last commit (`45fe5b0`) closed a real
  `INSERT OR REPLACE` bypass of the frozen-specification trigger that was
  supposed to make pre-registration tamper-proof (migration 0003 sqlite +
  `src/governance/ledger.py`).
- Workstream 3 ("the deals verdict") is referenced as still the live front in
  the newest commit messages.

## 2. Data flow, as it actually runs

```
NSE endpoints (rolling current-day only — historical endpoint answers 503)
   │  src/archive/{stopgap,prices,insider,corporate_actions,derivatives}.py
   ▼  raw bytes, sha256, gzip, NEVER overwritten
data/raw/archive/**  +  manifest.jsonl (append-only)
   │  src/ingest/{parse,land}.py                  src/ingest/{bhavcopy,corp_actions,insider}.py
   ▼  → research_prod.duckdb                       ▼ → data/raw/collected/**.parquet
  institutional_deals_raw                         price_spine / price_spine_adj / fno_spine
   │  src/identity/master.py                       │  (src/warehouse/spine.py, seed.py, reconcile.py)
   ▼  security_master / symbol_history              │
  deal_resolution (view)                            │
   │  src/mart/clean.py  ◄─────────────────────────┘
   ▼
  institutional_deals_clean  (239,480 rows per DATA_INVENTORY.md 2026-09-11)
   │
   ▼  src/research/{measure,consensus,selling,entity_verdict,outcomes}.py
  MDE grids, power verdicts → docs/reports/*.md, governance study_result rows
```

**Daily job** (`scripts/collect_daily.sh`, run 3×/session by launchd+cron):
`stopgap` → `prices` → `bhavcopy` → `corporate_actions` → `corp_actions` →
`derivatives` (0058) → `insider` → `ingest.insider` → **spine rebuild** →
`land` → `identity.master` → `mart.clean` → `charmatch` → `outcomes` →
`health` → `backup.sh`. The script accumulates a failure flag (`note()`) and
propagates a non-zero exit — this was fixed (see comment at line ~44 of the
script referencing the prior all-stages-report-success-anyway bug, closed
2026-09-03). `land`/`identity`/`mart` **are** in the daily job as of this
version of the script (the AUDIT_README's BUG-1 "land() crashes and isn't in
the daily job" appears to be resolved — verify against current `src/ingest/parse.py`
before relying on this).

## 3. Package map (see `code_map.json` for full function/class inventory)

| Package | Role | Key modules |
|---|---|---|
| `src/archive/` | Fetch raw bytes only, never parse. sha256 dedupe, gzip, temp-then-rename. | `stopgap.py` (bulk/block deals, current-day only), `prices.py` (daily bhavcopy feed), `insider.py` (SEBI XBRL filings), `corporate_actions.py`, `derivatives.py` (participant OI + F&O bhavcopy, decision 0058) |
| `src/common/` | Shared primitives. | `paths.py` (every fs/db location, `RESEARCH_ENV`-scoped, raises `EnvironmentNotSet` rather than defaulting), `calendar.py` (OBSERVED trading calendar, never generated — 5,358 sessions incl. 3 Saturdays), `hashing.py` (content addressing for provenance), `migrate.py` (forward-only checksummed migrations) |
| `src/governance/` | Write-once discipline layer. | `provenance.py` (content-addressed DAG: `artefact`/`artefact_edge`/`merkle_log`), `ledger.py` (added 2026-09-12: `require_populated_ledger`, `require_not_already_registered` — guards against writing to an empty/missing ledger or silently replaying a registration) |
| `src/identity/` | Point-in-time symbol resolution. | `master.py` — builds `security_master` (3,421 rows) + `symbol_history` (3,735 rows) from the ISIN master; the join that is *supposed* to prevent a recycled ticker attributing one company's deal to another's prices |
| `src/ingest/` | Bytes → typed rows → warehouse, without ever losing the bytes. | `parse.py`, `land.py` (the only path collected deals enter the DB), `bhavcopy.py`, `corp_actions.py`, `insider.py`, `publication.py` (measures `available_from` empirically), `seed_deals.py` (lands the 20-year predecessor corpus) |
| `src/mart/` | The clean, classified deal table. | `clean.py` → `institutional_deals_clean`, zero-silent-drops by construction (raw count == clean count, every row carries an eligibility reason); `eligibility.py` — a **second, partially divergent** classifier implementation (see §5) |
| `src/monitor/` | Self-derived reporting — never hand-asserted. | `status.py` (generates `docs/STATUS.md`, 73-step phase ledger), `health.py` (generates `docs/HEALTH.md`, session-gap detection), `inventory.py` (generates `docs/DATA_INVENTORY.md`), `backup_state.py` |
| `src/research/` | The study modules — where every verdict is computed. | `power.py` + `multiplicity.py` + `design.py` (the statistical core — MDE-before-fit, Bartlett-kernel serial correction, Gumbel best-of-N bars — **the strongest code in the repo**), `split.py` (EXPLORE/SELECT/CONFIRM guards), `families.py` (trial-counter charging), `confounds.py` (the standing 9-point checklist), `measure.py`/`consensus.py`/`selling.py`/`entity_verdict.py` (the actual studies), `outcomes.py` (`deal_forward_outcomes` builder), `costs.py`, `charmatch.py` (CHAR_MATCHED benchmark panel), `seasonality_power.py` (Engine 2 feasibility, killed the track), `insider_power.py`, `nullcal.py` (null-label calibration), `delisting.py`, `roles.py`, `entity_names.py` |
| `src/warehouse/` | Price/F&O spine construction. | `seed.py` (carries the 2.5 GB predecessor seed, hash-verified), `spine.py` (`build`/`build_adjusted`/`build_all` — the reconciled price and F&O spines), `reconcile.py` (Phase-1 gate, tolerance 0), `benchmarks.py` (6-benchmark daily panel), `participant_oi.py` (loads the F&O positioning proxy) |

## 4. Signal logic, portfolio rules, costs, risk limits (the actual numbers, from configs/)

**These are config-declared rules. `docs/STATUS.md` / `AUDIT_README.md`
previously found several configs were unparsed by any code — verify each
value's live binding against the module listed before trusting a downstream
number. `sources.yml` and `scan.yml` were confirmed unparsed as of the last
audit; `research.yml`, `costs.yml`, `participants.yml`, `split.yml`,
`trials.yml`, `universe.yml`, `benchmarks.yml`, `confounds.yml` had at least
partial live bindings.**

### Horizons & power (`configs/research.yml`)
- Primary horizon: **12 months**. Session-grid horizons `[1,2,3,5,10,21]` retained as robustness, all underpowered.
- Plausible effect bound: **0.5%/month**, and it **scales with horizon** (decision 0028): `bound(h sessions) = 0.005 * h / 21`.
- Power target: 80%, alpha 0.05, estimator = monthly-cohort mean, 10,000 bootstrap draws.
- Underpowered rule: `MDE > plausible bound` → verdict is UNDERPOWERED regardless of p-value.
- Room 2B: 6 pre-declared slices (side, deal_type, liquidity_tier, participant_category, regime, deal_size), NOT crossed — each tested independently, Romano-Wolf corrected.

### Portfolio gate (`configs/research.yml`, added after Finding 001 failed it)
- **Both** an event gate (abnormal return significant vs. matched control, MDE below plausible bound) **and** a portfolio gate (constructed book beats identical book without the signal, net of costs on incremental turnover, paired block-bootstrap CI excludes zero) must pass.
- Construction: top500 point-in-time universe, equal-weighted, month-end rebalance, paired difference, min 30 names, cost basis = incremental turnover only.
- This gate is why Finding 001 (bulk-deal avoidance) was killed: event t = −3.93, portfolio t = −0.25 — the signal touched only 1.2% of the book.

### Costs (`configs/costs.yml`)
- Statutory: STT 0.10% both legs (equity delivery), NSE TXN 0.00307%, BSE TXN 0.00375%, SEBI ₹10/crore, GST 18% on (brokerage+SEBI+TXN), STAMP 0.015% buy-side only.
- Brokerage: headline 0.03% (29.33 bps round trip, NSE), floor 0% (22.25 bps round trip).
- Spread: Corwin-Schultz primary / Abdi-Ranaldo cross-check, 21-session rolling window.
- Impact: square-root law, `impact = Y * sigma_daily * sqrt(Q/ADV)`, Y=0.8 base (alternates 0.5/1.0), ADV window 20 sessions.
- **Participation cap: 10% of ADV base (5% conservative for smallest tier), max 5 sessions to build a position — beyond this an event is `TOO_LARGE` and excluded.** This is the rule that reversed the 12-month "POWERED" verdict (decision 0038): 72% of eligible events failed it.
- Three reporting levels: gross / base / pessimistic, varying brokerage/impact-Y/participation/spread assumptions.

### Universe & eligibility (`configs/universe.yml`, `configs/participants.yml`)
- Universe: point-in-time, month-end rebalance, ranked by 20-session median turnover, tiers top100/top250/top500.
- Delisting: detected from last-traded date (20 stale sessions), classified MERGER/ACQUISITION/SUSPENSION/UNKNOWN, **included in research rather than dropped**.
- Eligibility (`clean.py`): exclude PROP_HFT, exclude same-day round-trip, min deal value ₹1 crore, min 0.5% of 20-day ADV.
- PROP_HFT classifier: behavioural first (round-trip ratio ≥ 0.95 over ≥20 client-stock-days), then name-pattern regex for MUTUAL_FUND/INSURANCE/PENSION_SOVEREIGN/BANK/FPI_OFFSHORE/BROKER_SEC/INDIVIDUAL, then UNKNOWN. No fuzzy auto-merge — only suggested merges, applied manually.

### EXPLORE/SELECT/CONFIRM split (`configs/split.yml`)
- Three-way, not two: EXPLORE 30% (free mining, uncharged), SELECT 20% (candidate comparison, charged), CONFIRM 50% (registered-experiment-only, charged, carries the statistical burden).
- **Keyed on ISIN, never symbol** (decision 0009) — 276 ISINs carry >1 symbol, 11.04% of deal rows would be split-contaminated under a symbol key.
- Assignment: deterministic `sha256(key) % 1000`, half-open buckets EXPLORE [0,300) SELECT [300,500) CONFIRM [500,1000).
- Enforcement: `ConfirmationGuard`/`ScanGuard` in `src/research/split.py` — **per STATUS.md step 3.6/AUDIT_README, these guards historically had zero production call sites; check current wiring before assuming enforcement is live.**

### Trial counter / multiplicity (`configs/trials.yml`, `src/research/families.py`, `src/research/multiplicity.py`)
- Hierarchical, not global: each family (`TRACK_D_DEALS`, `TRACK_S_CALENDAR`, `TRACK_S_SIGNALS`, `TRACK_S_PROCEDURE`) carries its own monotonic counter, enforced by SQLite triggers on `family_charge` (append-only, monotonic — migration 0002 sqlite).
- Project-level bar = sum of all family counters, reported alongside every project-level claim.
- `TRACK_D_DEALS` carried 171 trials (68 predecessor + ~100 exploratory pass on 2026-08-16) as of `trials.yml`'s writing.
- Romano-Wolf stepdown for participant ranking; Benjamini-Yekutieli primary / BH + Storey-q secondary for seasonality; Hansen SPA for best-of-family.

### Confound checklist (`configs/confounds.yml`)
9 blocking confounds for event studies (microstructure, volatility, size, momentum_reversal, liquidity, time_concentration, sector_concentration, survivorship, same_day_roundtrip, dilution) + 5 Track-S-specific (multiple_testing_declared, null_is_measured_not_assumed, fold_independence, bid_ask_bounce, prior_search_of_this_space). Every confound must be measured or explicitly marked NOT_APPLICABLE with a written reason — silence is not permitted by the schema.

## 5. CLI / how to run

Every module has a `main()` — see `05_RUNBOOK.md` for the exact invocation list.
No packaging/entry-point wrapper exists; everything runs as `python -m src.<pkg>.<module>`.

## 6. Known bugs, TODOs, hardcoded paths (verify each against current HEAD — some are from the 2026-09-02 audit and may be fixed)

**Hardcoded absolute paths found by grep (still present at HEAD):**
- `scripts/com.institutional-research.collect.plist` — `/Users/satya_03/Workspace/institutional-research/...` (×3, macOS launchd plist)
- `scripts/build_report.py:34` — `/Applications/Google Chrome.app/Contents/MacOS/Google Chrome`
- `scripts/collect_daily.sh:16` — `$HOME/Workspace/institutional-research` (less severe, uses `$HOME`)
- `src/common/paths.py` — docstring *references* a predecessor bug (`/Users/satya_03/Workspace/MICCV2/...` hardcoded in 166 views) as the reason `paths.py` exists; not itself hardcoded.

**No TODO/FIXME/HACK/XXX markers found in `src/`, `scripts/`, `configs/`, `migrations/`** except one self-referential mention inside `status.py`'s own docstring explaining why it excludes such markers from its predicates.

**Open items as of the last audit (2026-09-02, commit f79ac5d) — RE-VERIFY before acting, since 20 commits have landed since:**
1. `land()` raising `_csv.Error` on real archive PRICE/INSIDER files — audit's BUG-1. STATUS.md (472dfa8) step 2.1 reads VERIFIED with no crash noted; `land` is now in `collect_daily.sh`. **Likely fixed**, but not independently re-verified here.
2. `status.py` self-referential predicates inflating 12 step grades (incl. Romano-Wolf "VERIFIED" from zero implementation). STATUS.md (472dfa8) step 6.8 now reads VERIFIED with a substantive note referencing decision 0056 and a real participant leaderboard — **appears fixed**, not independently re-verified.
3. Governance guards (`ConfirmationGuard`, `StudyDesign`, `commit_charge`) historically had zero production call sites; `family_charge` was 0 rows. **Status uncertain** — `family_charge` now has a real schema (migration 0002 sqlite) and DATA_INVENTORY (2026-09-11) shows `family_charge`: 5 rows, so at least some charging is happening. Confirm which study modules construct `StudyDesign` before relying on this.
4. Two divergent PROP_HFT classifier implementations (`eligibility.py` vs `clean.py`) — 0.5% divergence measured at audit time. Not confirmed fixed.
5. `security_id` computed and stored by the identity layer but historically **not used to join prices** in `measure.py`/`consensus.py`/`selling.py` (studies joined on raw symbol instead) — the exact failure the identity layer exists to prevent. Not confirmed fixed; check these three modules directly if the deals verdict is being extended.
6. `collect_daily.sh` — the version read here **does** propagate exit codes (fixed 2026-09-03 per the script's own comment).
7. 9 unexplained >35% price discontinuities in `price_spine_adj` (audit time), 4 of them ETF units decision 0040 says should have left the universe. Not confirmed fixed.
8. Two bulk-deal sessions (2026-08-19, 2026-08-27) and one FII/DII session (2026-08-19) are **permanently and unrecoverably lost** — the historical NSE endpoint returns 503, only the rolling current-day file is fetchable. This is architectural, not a bug: `sources.yml`'s `acknowledged_gaps` block lists them by design so they stay visible without re-alerting forever.
9. `fno_spine` sits **28 days STALE** per `docs/DATA_INVENTORY.md` (2026-09-11) — collection resumed under decision 0058 but nothing parses the F&O bhavcopy into the spine yet (deliberate — analysis is deferred until the deals verdict lands).
10. `configs/sources.yml` (241 lines) and `configs/scan.yml` (365 lines) were confirmed **never parsed by any code** at audit time — their values exist only as documentation / duplicated Python literals.

## 7. Test suite

Per `pyproject.toml`: markers `unit` / `data` / `research` / `regression` /
`needs_data` / `needs_data` / `slow`. CI (`tests.yml`) runs **unit tier only**
on Python 3.12 (project declares `requires-python = ">=3.14"` — a known
mismatch, unpinned deps in CI). The data/research/regression tiers require a
populated `data/`+`db/` and are a **local-machine-only gate** — they cannot
run in this container or in CI as currently configured.

Run locally: `RESEARCH_ENV=dev python -m pytest tests -q` (unit tier will
pass with no data; full suite needs the real warehouse).
