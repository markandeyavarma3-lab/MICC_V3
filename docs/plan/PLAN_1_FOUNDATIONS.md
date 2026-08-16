# Institutional Research Platform — Plan 1 of 3: Foundations

**Repo:** `~/Workspace/institutional-research` · **Author:** Claude (Opus 5) for Markandeya Varma
**Date:** 2026-08-16 · **Status:** Phase 0 deliverable — awaiting owner approval before any code
**Predecessor:** MICCV2 at `~/Workspace/MICCV2`, to be frozen read-only

<!--TOC-->

---

## 0. What this document is, and what it is not

This is the Phase 0 audit and architecture specification that the owner's plan
§25 requires *before* production code is written. It covers foundations: what
gets torn down, what gets carried, the repository layout, the technology
choices, and the complete schema for Rooms 1–3.

**Plan 2** covers research methodology — cost models, benchmarks, walk-forward
design, multiple-testing control, and the seasonality validation layer.
**Plan 3** covers execution — phase-by-phase steps, week-by-week schedule, what
exists versus what must be built, risks, and the questions still open.

Nothing in this document is a promise that the research will find an edge. On
the evidence measured during this audit, the most likely outcome is a rigorous
negative result. That is stated here at the top so it cannot be read as a
surprise later.

---

## 1. The audit findings that shaped this plan

Every number below was measured directly during this session, not taken from
MICCV2's documentation.

### 1.1 What MICCV2 actually is

| Verified | Result |
|---|---|
| Tests | **486 pass**, 18.5s |
| `verify_suite` | 163 checks · 162 pass · 0 critical-fail · 1 warn |
| `verify_v3` (prod) | 44/44 GREEN, 428s |
| Book CAGR (recomputed) | 7.96% vs benchmark 8.89% |
| Warehouse | 7,749,148 price rows · 174,616,363 F&O rows · 4,200 symbols · 2005-01-03 → 2026-08-14 |
| Write-once ledgers | Real — SQLite triggers blocked both a test UPDATE and DELETE |
| Automation | launchd genuinely running; `last_success=2026-08-14` |

The engineering works. The **strategy** proved nothing: zero promoted edges,
22 verdicts all KILL or CONTEXT, champion trailing-24m Sharpe 0.11, and only
**24 live-forward days of which 9 were captured LIVE**. That is the finding
that motivated this rebuild, and it is a research finding, not a software
defect.

### 1.2 Defects found in MICCV2 that this rebuild must not inherit

These were found during the audit and are listed so the new architecture can
design them out rather than rediscover them.

| # | Defect | Design response in the new system |
|---|---|---|
| 1 | 7 of 12 dashboard pages return HTTP 500 whenever any writer holds the DuckDB lock; `verify_dashboard` tests in-process on an idle machine and never sees it | Readers use an immutable snapshot, never the live file. Availability tested *under* a held writer lock |
| 2 | `verify_v3.py` defaults to `dev`, and in `dev` reports 2 critical failures | Env must be explicit; unset fails loudly. No silent default |
| 3 | A `dev`-env verification shells out and rebuilds the **prod** warehouse, including live network fetches | Verification is strictly read-only. Rebuild and verify are separate verbs |
| 4 | Two walk-forward implementations; the live one (`wf_threshold`) includes the current period's own forward return | One implementation, one call site, a test asserting the training window ends strictly before the decision date |
| 5 | Backtest gate and live gate read different source tables and disagree on **13 of 259 rebalances (5.0%)**; 11 flip the decision | Single source of truth per computed quantity; a test asserting research and production read the same table |
| 6 | Champion Sharpe never deflated, while every challenger is | The trial counter applies to everything, incumbent included |
| 7 | Empty `data/raw/nse|bse|fno|global|macro|shp` — daily fetches archive nothing | Raw archive is mandatory and hash-verified before any parse |
| 8 | 166 warehouse views hard-code `/Users/satya_03/...` inside `read_parquet()` | All paths relative to a resolved repo root; a test asserts no absolute path appears in any view DDL |
| 9 | `db/app_state.sqlite` tracked in git despite docs saying otherwise | `.gitignore` verified by a test that greps `git ls-files` |

### 1.3 The institutional premise — measured, and it fails

The owner's plan assumes disclosed institutional deals carry repeatable
information. That was testable today against `v1seed.bulk_deals` (223,450 rows,
2006-01-02 → 2026-07-08) and `v1seed.block_deals` (12,430 rows).

**Finding A — 54.8% of bulk deals are same-day round trips.**

| Client | Client-stock-days | Round trips | % |
|---|---:|---:|---:|
| GRAVITON RESEARCH CAPITAL LLP | 6,748 | 6,748 | **100%** |
| HRTI PRIVATE LIMITED | 2,968 | 2,968 | **100%** |
| TOWER RESEARCH CAPITAL | 1,165 | 1,165 | **100%** |
| XTX MARKETS LLP | 857 | 857 | **100%** |
| **All bulk deals** | 144,053 | 79,012 | **54.8%** |
| *All block deals* | *11,962* | *80* | *0.7%* |

The most active "institutions" in the dataset are high-frequency market makers
whose bulk-deal disclosure is a mechanical consequence of crossing the 0.5%
volume threshold intraday. They end the day flat. Block deals are clean.

**Finding B — after filtering the churn, 30,771 directional buy events, entry
at next-session open, market-relative to Nifty 500 TR:**

| Horizon | n | Mean rel. | Median rel. | Hit rate | Naive *t* |
|---|---:|---:|---:|---:|---:|
| 1 month | 17,339 | −0.12% | −1.55% | 44.7% | −0.77 |
| 3 months | 16,594 | −0.22% | −4.81% | 42.0% | −0.81 |
| 12 months | 15,498 | **+7.80%** | **−10.68%** | **43.0%** | +11.61 |

One and three months are flat. The twelve-month mean is positive only because
of right skew — **the median event loses 10.68% to the market and 57%
underperform**. The naive *t* of 11.61 ignores that 12-month windows overlap
heavily. Corrected:

```
monthly cohort t       = +3.61
moving-block bootstrap = +9.67%  95% CI [-2.46%, +22.81%]   <- includes zero
P(mean > 0)            = 93.7%                              <- fails a 95% bar
```

**Finding C — and that is measured on survivors.** 13,928 of 30,771 events
(45%) were dropped: 7,354 symbols absent from the price spine, 6,574 hitting a
delisting or gap inside the window.

**Finding D — the good news: the attrition is fixable, not fatal.** The price
spine *does* contain dead stocks — 1,497 of 4,200 symbols stopped trading
before August 2026 (314 pre-2010, 667 in 2010-2019, 322 in 2020-2024, 194 in
2025-2026). So the 7,354 misses are **symbol-naming mismatches between the deal
feed and the price spine, not survivorship**. Fixing the identity layer
(§5) converts most of them into usable events. The 6,574 delisting cases are
real information and will be carried as realized outcomes, not dropped.

**Consequence for scope.** This is why the owner chose research-only with no
engines. Engines A, B, E and G in the original plan are not being built. §2.2
records why.

### 1.4 Seasonality — already answered

The existing atlas in `db/v3_prod.duckdb` holds **31,893,556 cells** and already
implements every dimension the plan's §11.2 specifies:

| Plan asks for | Atlas has |
|---|---|
| 13 windows (1…90) | ✅ exactly those |
| 4 alignment schemes | ✅ CALENDAR_DATE 15,083,303 · TRADING_DAY_OF_YEAR 12,818,902 · MONTH_END 1,997,179 · MONTH_START 1,994,172 |
| Price + market-relative | ✅ 16,105,466 / 15,788,090 |
| Stocks, indices, pooled | ✅ 3,638 stocks · 46 indices · 1 pooled |
| Window-specific baseline | ✅ `base_rate` per cell |
| Multiple-testing correction | ✅ Benjamini–Yekutieli, 14,036 survive q<0.05 |
| Permutation test | ✅ White's Reality Check, 300 circular rotations |

And its own verdict: **1,579,659 "significant" cells observed against 1,497,584
expected by chance — a ratio of 1.05.** The best NIFTY50 pattern sits at the
**94th percentile of what randomly rotated data produces.**

Per owner decision Q42, the atlas is **rebuilt from scratch with new code**, not
carried. The validation layer described in Plan 2 §7 is the genuinely new work.

---

## 2. Scope

### 2.1 In scope for v1

| Room | Contents | Status |
|---|---|---|
| **Room 1** | Raw archive (SHA-256, gzipped originals + parsed parquet), NSE + BSE bulk/block collectors, FII/DII collector, participant-OI proxy | Build |
| **Room 2A** | Individual deal outcomes across 9 horizons | Build |
| **Room 2B** | Institutional behaviour analysis (descriptive; no participant *ranking* without correction) | Build |
| **Room 2C** | Three deal interpretations — individual / accumulated / confirmation | Build |
| **Room 3** | Seasonality atlas rebuild + validation layer | Build |
| **Room 6** | Monitoring, data-quality gates, pause logic | Build (research-scope) |

### 2.2 Explicitly out of scope for v1, with reasons

| Deferred | Reason |
|---|---|
| **Engine A** (participant) | The most active directional buyer has 268 buys in 20 years; SBI MF has 80. Skill cannot be separated from luck at that sample size with 12-month overlapping horizons |
| **Engine B** (fund house) | Same power problem, plus parent-relationship data does not exist |
| **Engine E** (FII/DII regime) | `fii_dii_data` holds **22 days** (2026-06-17 → 2026-07-08). Cannot be researched until history accrues |
| **Engine G** (institutional × seasonality) | Combining two individually-null signals multiplies false-discovery risk. The single most dangerous item in the original plan |
| **Room 5** (paper portfolios) | Owner decision Q6: no paper book until something passes gates |
| **Engines C, D** | Deferred, not rejected. The schemas are designed so they drop in (§7) |

### 2.3 The plan's blind spot, and how this design closes it

The original plan applies rigorous false-discovery control to seasonality (§11)
and **none at all** to participant selection (§12). Choosing "the best of 27,417
participants" is a larger multiple-testing problem than 31.9M seasonality cells,
because each participant has far fewer observations.

**Design response:** the participant-ranking correction is specified in Plan 2
§6 *before* any leaderboard is computed, and `study_result` (§7.4) cannot store a
participant-level claim without a populated `correction_method` and
`corrected_p_value`. The schema makes the omission impossible rather than
discouraged.

---

## 3. Teardown and migration

Owner decision: full teardown, new repo, MICCV2 frozen read-only, carrying raw
data and dropping derived data.

### 3.1 What is carried

| Source | Size | Disposition |
|---|---|---|
| `MICCV2/data/raw/v1_export/` | 1.2 GB, 126 parquet files | **Copy.** Irreplaceable — NSE does not serve 21 years of history. This is the seed for everything |
| `MICCV2/db/miccv2.duckdb` | 274 KB | **Read-only reference** during migration; not carried into the new warehouse |
| `MICCV2/db/app_state.sqlite` | 148 KB | **Extract only** the cumulative trial counter (N=47 + 21 legacy) per Q47 |
| Trading-calendar logic | code | **Port**, do not re-derive. 5,339 observed sessions, verified complete |
| Cost-model constants | config | **Port as the floor**, then extend per Plan 2 §4 |

### 3.2 What is dropped

| Dropped | Size | Why |
|---|---|---|
| `MICCV2/data/warehouse/` | 1.5 GB | Derived. Rebuilt by new code from `v1_export` |
| `MICCV2/data/v3/` | 2.3 GB | Derived, including the seasonality atlas (rebuilt per Q42) |
| All `src/` strategy code | ~27k lines | Champion, GCE, engines, ML tracks, factory — the research paths that proved nothing |
| `src/dashboard/` | 12 pages | Deferred to Phase 8 per Q51 |
| Docker / CI image work | — | Skipped per Q52 |

### 3.3 Freezing MICCV2 — exact steps

Per Q50, all analysing agents are removed. This is the only step in this plan
that touches the existing machine, and it is reversible.

```bash
# 1. Unload the launchd agents (stops all writes to carried data)
launchctl bootout gui/$(id -u)/com.miccv2.daily
launchctl bootout gui/$(id -u)/com.miccv2.dashboard
launchctl bootout gui/$(id -u)/com.miccv3.heartbeat

# 2. Move the plists out of the load path (kept, not deleted)
mkdir -p ~/Workspace/MICCV2/_frozen_agents
mv ~/Library/LaunchAgents/com.miccv2.daily.plist      ~/Workspace/MICCV2/_frozen_agents/
mv ~/Library/LaunchAgents/com.miccv2.dashboard.plist  ~/Workspace/MICCV2/_frozen_agents/
mv ~/Library/LaunchAgents/com.miccv3.heartbeat.plist  ~/Workspace/MICCV2/_frozen_agents/

# 3. Tag the final state, so the 107-commit history stays addressable
cd ~/Workspace/MICCV2 && git tag -a frozen-2026-08-16 -m "final state before rebuild"

# 4. Verify nothing is still running
launchctl list | grep -i micc     # expect: no output
```

**Not done:** deleting MICCV2 from disk. It stays as a read-only reference until
the new system reproduces the warehouse and the owner says otherwise.

### 3.4 Migration verification gate

The new warehouse is not accepted until it reproduces MICCV2's numbers from the
same seed. This is the one place the old system is genuinely useful — as an
oracle.

| Check | Expected |
|---|---|
| Price rows | 7,749,148 |
| Distinct symbols | 4,200 |
| Date span | 2005-01-03 → 2026-08-14 |
| F&O rows | 174,616,363 |
| Bulk deals | 223,450 |
| Block deals | 12,430 |
| Trading sessions | 5,339 |
| Dead symbols (last trade < 2026-08-01) | 1,497 |

A mismatch on any row is a blocking failure, investigated before proceeding.

---

## 4. Repository layout and stack

### 4.1 Stack decision

**Python 3.14 · DuckDB · Parquet · SQLite · pytest.** Rationale, given the
owner's "job level" framing:

What reads as senior in a quant portfolio, in order: point-in-time correctness ·
reproducible deterministic builds · pre-registration and honest negative results ·
tests that pin behaviour · clean module boundaries. Database choice is far down
that list. A reviewer will try to *clone and run* the project first — a
zero-server stack wins there.

| Layer | Choice | Why |
|---|---|---|
| Immutable raw archive | Parquet + gzipped originals, SHA-256 | Plan §5. Append-only, never rewritten |
| Analytics + relational marts | DuckDB | 174M rows already scan fine on this laptop. Arrow-native, zero-server, the current research standard |
| Append-only ledgers | SQLite | Only because it has real triggers. MICCV2's write-once enforcement genuinely works — verified |
| Review queue / mutable state | SQLite | 27,417 names is small; needs transactions, not analytics |
| Migrations | Plain SQL files + `schema_migrations` table | No ORM. MICCV2's V2 store drifted to 1 table vs prod's 15 precisely because it had none |

**Rejected: Postgres.** It adds a running service, connection management, and a
migration of 7.7M + 174M rows, for no capability this workload needs. A sharp
interviewer would ask why, and there is no good answer at this scale.

### 4.2 Directory layout

```text
institutional-research/
├── README.md                    honest status, leads with what is NOT working
├── pyproject.toml               uv-managed, Python 3.14 pinned
├── configs/
│   ├── sources.yml              every source: URL, cadence, licence, contact
│   ├── costs.yml                the advanced cost model (Plan 2 §4)
│   ├── benchmarks.yml           the 6-benchmark set (Plan 2 §5)
│   ├── universe.yml             liquidity and eligibility rules
│   ├── participants.yml         classification patterns + behavioural thresholds
│   └── research.yml             horizons, CPCV folds, correction methods
├── migrations/
│   └── 0001_init.sql …          forward-only, checksummed, never edited
├── src/
│   ├── common/                  paths, config, logging, calendar, hashing
│   ├── archive/                 Room 1 — fetch, hash, store, verify
│   ├── ingest/                  parsers: nse_bulk, nse_block, bse_bulk, bse_block, fii_dii
│   ├── identity/                security master, symbol_history, participants
│   ├── warehouse/               spine, universe, benchmarks, PIT sectors
│   ├── mart/                    institutional_deals_clean, interpretations
│   ├── research/                outcomes, cost model, CPCV, corrections
│   ├── seasonality/             atlas build + validation layer
│   ├── governance/              experiment registry, provenance DAG, trial counter
│   └── monitor/                 Room 6 — DQ gates, pause logic, alerts
├── tests/                       mirrors src/ one-to-one
├── scripts/                     one-shot tools, report builder, launchd plists
├── docs/
│   ├── plan/                    these three documents
│   ├── decisions/               one file per owner decision, dated and attributed
│   └── reports/                 generated markdown + PDF
├── data/                        gitignored
│   ├── raw/                     immutable archive, never rewritten
│   ├── warehouse/               parquet marts, regenerable
│   └── snapshots/               read-only DB copies for readers
└── db/                          gitignored
    ├── research.duckdb          analytics + marts
    ├── governance.sqlite        append-only ledgers
    └── review.sqlite            participant review queue
```

### 4.3 Standing engineering rules

Carried from MICCV2 where they earned their place, plus new ones from §1.2.

1. **No order-placement code.** Not in tests, not commented out.
2. **No live trading.** Ever, in this repo.
3. **Readers never touch a live database file.** They read `data/snapshots/`.
4. **Verification is read-only.** A verify command that writes is a bug.
5. **The environment must be explicit.** Unset `RESEARCH_ENV` fails loudly.
6. **No absolute paths in any stored view DDL.** Tested.
7. **A fix is done when its test has been watched failing**, not when the code changes.
8. **UNKNOWN beats inference.** Where something cannot be established, it says so.
9. **Raw files are never overwritten or deleted.**
10. **Every study is pre-registered.** No exceptions (Q44).

---

## 5. Room 1 — Raw archive and collection

### 5.1 Design

Owner decisions: both daily and historical endpoints (Q7) · backfill the
2026-07-08 → present gap first (Q8) · collect BSE too (Q9) · browser-like
session with rate limiting (Q10) · store original bytes gzipped *and* parsed
parquet (Q11) · retain forever (Q12) · automated from day one (Q13).

```text
fetch  ──►  bytes in memory
             │
             ├──► SHA-256 ──► if hash already in deal_source_files: STOP (idempotent)
             │
             ├──► write raw/institutional_deals/<ex>/<type>/year=YYYY/month=MM/<name>.gz
             │
             ├──► parse ──► write the same path as .parquet
             │
             └──► INSERT deal_source_files (status=OK | PARSE_FAILED | FETCH_FAILED)
```

A parse failure **still archives the bytes** and records the failure. That is
the difference between a system that can recover from a source format change and
one that silently loses a day.

### 5.2 `deal_source_files`

```sql
CREATE TABLE deal_source_files (
    source_file_id   BIGINT PRIMARY KEY,
    exchange         TEXT    NOT NULL,      -- NSE | BSE
    report_type      TEXT    NOT NULL,      -- BULK | BLOCK | FII_DII | SHP
    source_url       TEXT    NOT NULL,
    report_date      DATE    NOT NULL,
    downloaded_at    TIMESTAMP NOT NULL,
    file_name        TEXT    NOT NULL,
    file_hash        TEXT    NOT NULL,      -- SHA-256 of the raw bytes
    file_bytes       BIGINT  NOT NULL,
    parser_version   TEXT    NOT NULL,
    row_count        INTEGER,
    ingestion_status TEXT    NOT NULL,      -- OK|PARSE_FAILED|FETCH_FAILED|EMPTY
    error_message    TEXT,
    http_status      INTEGER,
    fetch_duration_ms INTEGER,
    UNIQUE (file_hash),
    UNIQUE (exchange, report_type, report_date, parser_version)
);
```

`UNIQUE(file_hash)` makes re-fetching free and makes "did the source change?"
answerable — a new hash for a date already collected is a **revision**, which
§5.4 handles explicitly.

### 5.3 `institutional_deals_raw`

Verbatim source rows. Never cleaned, never corrected.

```sql
CREATE TABLE institutional_deals_raw (
    raw_deal_id      BIGINT PRIMARY KEY,
    source_file_id   BIGINT NOT NULL REFERENCES deal_source_files,
    exchange         TEXT   NOT NULL,
    deal_type        TEXT   NOT NULL,       -- BULK | BLOCK
    trade_date       DATE   NOT NULL,
    symbol_raw       TEXT,
    security_name_raw TEXT,
    client_name_raw  TEXT,
    side_raw         TEXT,
    quantity_raw     TEXT,                  -- TEXT: source sometimes has commas
    deal_price_raw   TEXT,
    remarks_raw      TEXT,
    raw_row_json     TEXT   NOT NULL,       -- the complete original row
    row_index        INTEGER NOT NULL,      -- position within the file
    ingested_at      TIMESTAMP NOT NULL
);
```

### 5.4 Source revisions

NSE and BSE silently restate. A revision is a new `file_hash` for a
`(exchange, report_type, report_date)` already held.

```sql
CREATE TABLE source_revisions (
    revision_id      BIGINT PRIMARY KEY,
    exchange         TEXT NOT NULL,
    report_type      TEXT NOT NULL,
    report_date      DATE NOT NULL,
    prior_file_id    BIGINT NOT NULL REFERENCES deal_source_files,
    new_file_id      BIGINT NOT NULL REFERENCES deal_source_files,
    detected_at      TIMESTAMP NOT NULL,
    rows_added       INTEGER,
    rows_removed     INTEGER,
    rows_changed     INTEGER,
    review_status    TEXT NOT NULL DEFAULT 'PENDING'
);
```

**Both versions are kept.** Research uses the version available at the decision
date — a restatement published in 2020 cannot inform a 2015 signal. This is the
point-in-time discipline applied to the source layer itself, and it is a thing
MICCV2 never had.

### 5.5 Collection schedule

| Source | Cadence | Window | Notes |
|---|---|---|---|
| NSE bulk | daily 19:00 IST | T | Published after close |
| NSE block | daily 19:00 IST | T | |
| BSE bulk | daily 19:15 IST | T | New — never collected before |
| BSE block | daily 19:15 IST | T | New |
| FII/DII | daily 19:30 IST | T | Starts accruing now (Q4 route: both) |
| SHP / promoter | quarterly | filing dates | For promoter list (Q25) |

Rate limit 1 request / 2 s, honest User-Agent, exponential backoff, and **the
retry never re-fetches a hash already held**.

---

## 6. Identity layer

This is the highest-priority component (Q16) because it directly determines
whether the outcome study is biased. 7,354 of 30,771 events currently fail to
resolve, and §1.3 Finding D established these are naming mismatches, not
delistings.

### 6.1 `security_master` — wraps the existing masters (Q15)

```sql
CREATE TABLE security_master (
    security_id      BIGINT PRIMARY KEY,
    isin             TEXT UNIQUE,
    canonical_symbol TEXT NOT NULL,
    company_name     TEXT NOT NULL,
    listing_date     DATE,
    delisting_date   DATE,                  -- populated from last-trade detection
    delisting_reason TEXT,                  -- MERGER|ACQUISITION|SUSPENSION|UNKNOWN
    status           TEXT NOT NULL,         -- ACTIVE|DELISTED|SUSPENDED|MERGED
    merged_into_id   BIGINT REFERENCES security_master,
    source           TEXT NOT NULL,
    confidence       TEXT NOT NULL          -- HIGH|MEDIUM|LOW
);
```

`merged_into_id` matters: when a stock merges, its holder receives shares in the
acquirer. Treating that as a delisting-to-zero is a large downward bias; ignoring
it is an upward one. Both are wrong and MICCV2 did the second.

### 6.2 `symbol_history` — the point-in-time map

```sql
CREATE TABLE symbol_history (
    symbol_history_id BIGINT PRIMARY KEY,
    security_id      BIGINT NOT NULL REFERENCES security_master,
    symbol           TEXT NOT NULL,
    exchange         TEXT NOT NULL,
    series           TEXT,
    valid_from       DATE NOT NULL,
    valid_to         DATE,                  -- NULL = current
    source           TEXT NOT NULL,
    UNIQUE (symbol, exchange, valid_from)
);
```

**Resolution rule, enforced in one function and one only:**

```python
def resolve(symbol: str, exchange: str, on_date: date) -> SecurityId | Unresolved:
    """The symbol identity valid ON the transaction date — never today's."""
```

Every caller uses it. A test asserts no module builds its own symbol lookup.

### 6.3 `sector_history` — point-in-time sectors (Q31)

The owner chose to build PIT sectors. MICCV2's `dim_sector` is current-only,
which is a look-ahead: a company classified "IT" today may have been "Textiles"
in 2008.

```sql
CREATE TABLE sector_history (
    security_id      BIGINT NOT NULL REFERENCES security_master,
    sector           TEXT NOT NULL,
    industry         TEXT,
    classification   TEXT NOT NULL,         -- NIC|NSE|BSE|MANUAL
    valid_from       DATE NOT NULL,
    valid_to         DATE,
    confidence       TEXT NOT NULL,
    PRIMARY KEY (security_id, classification, valid_from)
);
```

Sources, in preference order: NSE index-membership history (`index_membership`
has 13,163 rows with `effective_from`/`effective_to`), BSE scrip master
vintages, then manual. Where no vintage exists, the earliest known
classification is carried backward and marked `confidence='LOW'` — and the
outcome study reports sector-relative results **separately** for LOW-confidence
rows so the reader can discount them.

### 6.4 Participant identity

Owner decisions: exact-after-cleaning, no fuzzy auto-merge (Q19) · variants stay
separate until the owner rules (Q20) · manual mapping file for fund houses (Q21)
· HFT flagged as a category (Q18).

```sql
CREATE TABLE participant_master (
    participant_id   BIGINT PRIMARY KEY,
    canonical_name   TEXT NOT NULL UNIQUE,
    participant_type TEXT NOT NULL,         -- see §6.5
    classification_method TEXT NOT NULL,    -- BEHAVIOURAL|NAME_PATTERN|MANUAL
    parent_group_id  BIGINT REFERENCES participant_master,
    country          TEXT,
    confidence_level TEXT NOT NULL,         -- HIGH|MEDIUM|LOW|UNKNOWN
    first_seen       DATE,
    last_seen        DATE,
    deal_count       INTEGER,
    review_status    TEXT NOT NULL,         -- PENDING|REVIEWED|AUTO
    reviewed_by      TEXT,
    reviewed_at      TIMESTAMP,
    review_notes     TEXT
);

CREATE TABLE participant_aliases (
    alias_id         BIGINT PRIMARY KEY,
    participant_id   BIGINT NOT NULL REFERENCES participant_master,
    raw_name         TEXT NOT NULL UNIQUE,
    normalized_name  TEXT NOT NULL,
    mapping_method   TEXT NOT NULL,         -- EXACT|CLEANED|MANUAL
    mapping_confidence TEXT NOT NULL,
    suggested_merge_id BIGINT REFERENCES participant_master,  -- surfaced, never applied
    review_status    TEXT NOT NULL,
    reviewed_at      TIMESTAMP,
    review_notes     TEXT
);
```

`suggested_merge_id` is how Q20 is honoured: `QE SECURITIES LLP` and
`QE SECURITIES` get a suggestion recorded, stay separate entities, and the owner
decides later. Nothing merges automatically.

### 6.5 Classification — behavioural first, then name

The audit established that the best classifier for the largest category is
**behaviour, not name**. This is the single most useful thing found.

| Category | Rule | Names | % of deals |
|---|---|---:|---:|
| `PROP_HFT` | ≥20 client-stock-days AND ≥95% same-day round-trip | 327 | **44.0%** |
| `INDIVIDUAL` | name matches personal-name pattern | 12,891 | 22.9% |
| `BROKER_SEC` | `SECURITIES\|BROKING\|BROKERS\|STOCK` | 947 | 7.3% |
| `FPI_OFFSHORE` | `MAURITIUS\|SINGAPORE\|CYPRUS\|CAYMAN\|GLOBAL MARKETS` | 852 | 1.9% |
| `MUTUAL_FUND` | `MUTUAL FUND\|ASSET MANAGE\|AMC` | 806 | 1.1% |
| `BANK` | `\bBANK\b` | 235 | 0.5% |
| `INSURANCE` | `INSURANCE\|ASSURANCE` | 137 | 0.2% |
| `PENSION_SOVEREIGN` | `PENSION\|SOVEREIGN\|MONETARY AUTH` | 32 | 0.0% |
| `UNKNOWN` | everything else | 11,190 | 22.2% |

**Manual review queue: 1,515 names** — those UNKNOWN with ≥6 deals. This is the
better answer Q17 invited: classification is 78% mechanical, and the mechanical
part for the biggest category is behavioural, which is far more defensible than
a hand-maintained name list. Graviton never declares itself a market maker;
6,748 of 6,748 round-trips does.

Ordering matters: **behavioural runs first.** A firm named
`… SECURITIES PRIVATE LIMITED` that round-trips 100% of the time is `PROP_HFT`,
not a broker. Name patterns only see what behaviour did not already classify.

**Where the 95% / 20 thresholds come from, and how they are defended.** They
were not tuned. The observed distribution is close to bimodal: the top twenty
participants by activity sit at 100.0%, 100.0%, 100.0%, 98.9%, 85.6%, 62.0%,
52.9% … — a dense cluster at ~100% and a long tail below 90%. 95% sits inside
the gap; 20 client-stock-days is the point at which the round-trip ratio stops
being dominated by small-sample noise.

Both are configuration, and **both get a sensitivity table in every study**:

```yaml
prop_hft_classifier:
  roundtrip_ratio: 0.95        # sensitivity: 0.80, 0.90, 0.99
  min_client_stock_days: 20    # sensitivity: 10, 50
```

The reported N of eligible events at each of the nine combinations is published
alongside the headline. A finding that depends on whether the cut is 0.90 or
0.95 is a finding about the cut, not about institutions — and this is a 44%-of-
data filter, so that check is not optional.

### 6.5.1 Review queue ordering

The 1,515-name queue is worked in descending order of **`deal_value × current
contribution to the unresolved-symbol rate`**, not raw deal count. That front-
loads the names which most affect the Phase 3 gate (unresolved rate < 5%), so
the gate can pass before the queue is exhausted. Progress against the gate is
printed after every batch.

### 6.6 Promoter list (Q25)

No promoter list exists. Built from shareholding-pattern (SHP) filings, which
disclose promoter-group entity names per company per quarter.

```sql
CREATE TABLE promoter_entities (
    security_id      BIGINT NOT NULL REFERENCES security_master,
    entity_name      TEXT NOT NULL,
    normalized_name  TEXT NOT NULL,
    valid_from       DATE NOT NULL,         -- the quarter's filing date
    valid_to         DATE,
    holding_pct      REAL,
    source_file_id   BIGINT REFERENCES deal_source_files,
    PRIMARY KEY (security_id, normalized_name, valid_from)
);
```

A deal is `promoter_related_flag = TRUE` when the participant's normalized name
matches a promoter entity of that security **valid on the trade date** — a
point-in-time join, not a current-list lookup.

---

## 7. Room 2 — the clean mart and research schemas

### 7.1 `institutional_deals_clean`

Owner decisions: keep NSE/BSE duplicates with a group id (Q24) · add a 5-day
round-trip flag alongside the same-day one (Q23) · treat a client's multiple
same-day rows as **separate** events (Q28) · exclude `PROP_HFT` from
`eligible_for_research` by default but keep the rows (Q27) · size filter
`deal_value_to_adv20 ≥ 0.5%` and ≥ ₹1cr, configurable (Q26).

```sql
CREATE TABLE institutional_deals_clean (
    deal_id          BIGINT PRIMARY KEY,
    raw_deal_id      BIGINT NOT NULL REFERENCES institutional_deals_raw,
    security_id      BIGINT REFERENCES security_master,
    participant_id   BIGINT REFERENCES participant_master,
    trade_date       DATE NOT NULL,
    available_from   TIMESTAMP NOT NULL,    -- when the disclosure was observable
    entry_date       DATE NOT NULL,         -- first tradable session after that
    exchange         TEXT NOT NULL,
    deal_type        TEXT NOT NULL,
    side             TEXT NOT NULL,         -- BUY | SELL
    quantity         BIGINT NOT NULL,
    deal_price       REAL NOT NULL,
    gross_deal_value REAL NOT NULL,
    adv20            REAL,
    deal_value_to_adv20 REAL,

    duplicate_group_id      BIGINT,
    same_day_round_trip_flag BOOLEAN NOT NULL,
    five_day_round_trip_flag BOOLEAN NOT NULL,
    internal_transfer_flag  BOOLEAN NOT NULL,
    promoter_related_flag   BOOLEAN NOT NULL,
    suspect_flag            BOOLEAN NOT NULL,
    unresolved_symbol_flag  BOOLEAN NOT NULL,
    eligible_for_research   BOOLEAN NOT NULL,
    ineligibility_reason    TEXT,

    clean_version    TEXT NOT NULL,
    created_at       TIMESTAMP NOT NULL
);
```

**`available_from` is the field the whole study rests on.** It is a timestamp,
not a date, and it is established empirically in Phase 1 by recording the
observed publication time of each report over several weeks — never assumed. If
publication time cannot be established for a historical period, `available_from`
is set to the conservative bound (next session open) and the row carries
`confidence='LOW'`.

### 7.2 The three interpretations (plan §10)

Kept strictly separate, never silently mixed.

```sql
CREATE TABLE deal_interpretation (
    interpretation_id BIGINT PRIMARY KEY,
    mode             TEXT NOT NULL,      -- INDIVIDUAL|ACCUMULATED|CONFIRMATION
    deal_id          BIGINT NOT NULL REFERENCES institutional_deals_clean,
    position_id      BIGINT,             -- groups an accumulation sequence
    sequence_index   INTEGER,            -- 1 = initiating deal
    is_initiation    BOOLEAN NOT NULL,
    is_confirmation  BOOLEAN NOT NULL,
    days_since_prior INTEGER,
    cumulative_qty   BIGINT,
    cumulative_value REAL,
    version          TEXT NOT NULL
);
```

Accumulation grouping rule: same `participant_id` + `security_id`, same side,
gaps ≤ N trading days (configurable, default 63). A gap longer than N closes the
position and a later deal starts a new one.

### 7.3 `deal_forward_outcomes`

Owner decisions: nine horizons — 1/3/6/8/10/**15**/12/**18**/24 months (Q29) ·
delisted stocks used, not dropped (Q32) · five-plus benchmarks (Q30) ·
intraday excursions pending clarification (Q33, see Plan 3 §5).

```sql
CREATE TABLE deal_forward_outcomes (
    outcome_id       BIGINT PRIMARY KEY,
    deal_id          BIGINT NOT NULL REFERENCES institutional_deals_clean,
    interpretation_id BIGINT REFERENCES deal_interpretation,
    horizon_months   INTEGER NOT NULL,     -- 1,3,6,8,10,12,15,18,24
    entry_date       DATE NOT NULL,
    entry_price      REAL NOT NULL,
    exit_date        DATE NOT NULL,
    exit_price       REAL NOT NULL,
    exit_reason      TEXT NOT NULL,        -- HORIZON|DELISTED|MERGED|SUSPENDED

    stock_return     REAL NOT NULL,
    net_return       REAL NOT NULL,        -- after the Plan 2 §4 cost model

    -- one row per benchmark, see benchmark_returns below
    max_adverse_excursion   REAL,
    max_favorable_excursion REAL,
    days_to_max_adverse     INTEGER,
    excursion_basis         TEXT NOT NULL, -- CLOSE|INTRADAY

    outcome_complete_flag BOOLEAN NOT NULL,
    calculation_version   TEXT NOT NULL,
    UNIQUE (deal_id, interpretation_id, horizon_months, calculation_version)
);

CREATE TABLE outcome_benchmark_returns (
    outcome_id       BIGINT NOT NULL REFERENCES deal_forward_outcomes,
    benchmark_id     TEXT NOT NULL,
    benchmark_return REAL NOT NULL,
    relative_return  REAL NOT NULL,
    PRIMARY KEY (outcome_id, benchmark_id)
);
```

Splitting benchmarks into their own table is what makes Q30's "at least 5
benchmarks" workable without nine near-identical columns, and lets a benchmark
be added later without a schema change.

**Delisting handling (Q32).** `exit_reason` distinguishes four cases and each is
priced differently: `HORIZON` normal · `DELISTED` exit at last traded price with
a configurable recovery haircut · `MERGED` roll into `merged_into_id` at the
exchange ratio and continue the horizon · `SUSPENDED` mark to last price and flag.
The choice materially moves the headline number, so all four are reported
separately and the aggregate is shown under each assumption.

### 7.4 `study_result` — replaces the signal ledger for v1

**This is the answer to owner question Q2.** The full reasoning is in Plan 3 §1;
the short version: the *experiment registry* is required now, the *signal ledger*
is not, because a signal ledger records engine decisions and there are no engines.
What research needs instead is a result store.

```sql
CREATE TABLE study_result (
    result_id        BIGINT PRIMARY KEY,
    experiment_id    TEXT NOT NULL REFERENCES experiment_registry,
    stratum          TEXT NOT NULL,        -- 'ALL' | 'sector=IT' | 'participant=SBI_MF'
    stratum_type     TEXT NOT NULL,
    horizon_months   INTEGER,
    benchmark_id     TEXT,
    n_events         INTEGER NOT NULL,
    n_independent    INTEGER NOT NULL,     -- after overlap adjustment
    mean_return      REAL,
    median_return    REAL,
    hit_rate         REAL,
    raw_p_value      REAL,
    corrected_p_value REAL,
    correction_method TEXT NOT NULL,       -- NOT NULL: the §2.3 guard
    n_tests_in_family INTEGER NOT NULL,
    bootstrap_ci_low  REAL,
    bootstrap_ci_high REAL,
    verdict          TEXT NOT NULL,        -- PASS|FAIL|UNDERPOWERED
    input_hashes     TEXT NOT NULL,        -- provenance DAG, Plan 2 §8
    code_commit      TEXT NOT NULL,
    computed_at      TIMESTAMP NOT NULL
);
```

`correction_method` and `n_tests_in_family` are `NOT NULL`. A participant-level
claim cannot physically be stored without declaring how many participants were
tested. That is §2.3's blind spot closed in the schema.

### 7.5 Engine schemas — designed now, unpopulated (Q1)

Per owner decision Q1, engine tables are created so engines drop in later
without a migration that rewrites research history.

```sql
CREATE TABLE engine_config (
    engine_id        TEXT PRIMARY KEY,
    engine_name      TEXT NOT NULL,
    purpose          TEXT NOT NULL,
    data_inputs      TEXT NOT NULL,
    participant_level TEXT NOT NULL,
    allowed_sides    TEXT NOT NULL,
    interpretation_mode TEXT NOT NULL,
    holding_periods  TEXT NOT NULL,
    entry_policy     TEXT NOT NULL,
    exit_policy      TEXT NOT NULL,
    liquidity_policy TEXT NOT NULL,
    risk_policy      TEXT NOT NULL,
    benchmark_policy TEXT NOT NULL,
    minimum_history_policy TEXT NOT NULL,
    false_discovery_policy TEXT NOT NULL,   -- required before an engine may run
    enabled_status   TEXT NOT NULL DEFAULT 'DISABLED',
    version          TEXT NOT NULL
);

CREATE TABLE institutional_signal_ledger (
    signal_id        BIGINT PRIMARY KEY,
    engine_id        TEXT NOT NULL REFERENCES engine_config,
    as_of_date       DATE NOT NULL,
    deal_id          BIGINT REFERENCES institutional_deals_clean,
    security_id      BIGINT REFERENCES security_master,
    participant_id   BIGINT REFERENCES participant_master,
    interpretation_mode TEXT NOT NULL,
    intended_horizon INTEGER,
    signal_type      TEXT NOT NULL,
    signal_status    TEXT NOT NULL,        -- APPROVED|REJECTED|BLOCKED|SKIPPED
    reason           TEXT NOT NULL,
    seasonality_cell_id BIGINT,
    engine_config_version TEXT NOT NULL,
    experiment_id    TEXT REFERENCES experiment_registry,
    input_hashes     TEXT NOT NULL,
    code_commit      TEXT NOT NULL,
    created_at       TIMESTAMP NOT NULL
);
```

Both tables are created empty in migration `0001`, with a test asserting they
stay empty while `enabled_status='DISABLED'` for every engine. When engines are
built, the schema does not move.

---

## 8. What exists, what must be built

| Component | Status | Source |
|---|---|---|
| 21-year price history | ✅ Have | `v1_export`, 7.7M rows, 4,200 symbols incl. 1,497 dead |
| F&O history | ✅ Have | 174.6M rows, 2005-2026 |
| Bulk deals | ✅ Have to 2026-07-08 | 223,450 rows; needs 5-week backfill |
| Block deals | ✅ Have to 2026-07-08 | 12,430 rows |
| Trading calendar | ✅ Have | 5,339 sessions, verified complete |
| ISIN master + renames | 🟡 Partial | 276 rename rows — insufficient for 7,354 misses |
| Index history | 🟡 Partial | NIFTY 50/100/200/Midcap100 good; **Smallcap has 15 rows** |
| Nifty 500 TR benchmark | ✅ Have | cap-weighted + dividends, 2011-2026 |
| Participant OI (FII/DII proxy) | ✅ Have | 15,359 rows, 2014-2026 |
| FII/DII cash | ❌ 22 days | Must collect forward |
| BSE bulk/block | ❌ None | Must build |
| Raw archive | ❌ None | Must build — dirs exist and are empty |
| PIT sectors | ❌ None | Must build from `index_membership` |
| Promoter list | ❌ None | Must build from SHP |
| Participant identity | ❌ None | Must build; 78% automatable |
| Seasonality atlas | 🔄 Rebuild | 31.9M cells exist; rebuilding per Q42 |

**The three genuine gaps that need outside input:** a smallcap index history
(Plan 2 §5 proposes constructing one), FII/DII cash history (unobtainable —
accrues forward only), and the publication-time evidence for `available_from`
(measured over the first weeks of collection).

---

*Continues in **Plan 2 — Research Methodology** and **Plan 3 — Execution**.*
