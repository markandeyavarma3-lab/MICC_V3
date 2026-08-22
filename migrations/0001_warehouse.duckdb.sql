-- 0001_warehouse.duckdb.sql
-- The data schema: Plan 1 §5 (raw archive), §6 (identity), §7 (marts),
-- and Plan 2 §7.3 (seasonality cells).
--
-- WHY THIS IS ARRIVING LATE. Phase 1 step 1.6 promised "0001_init.sql — every
-- table in Plan 1 §5-§7 and Plan 2 §2, §7.3, §8.1". Only the governance half was
-- built: `0001_governance.sqlite.sql` created the provenance DAG, experiment
-- registry, trial counter and study results, and NONE of the fourteen tables
-- below. Found by audit on 2026-08-23. It is why `src/ingest/parse.py` could
-- turn archived bytes into rows and then had nowhere to put them.
--
-- WHY DUCKDB AND NOT SQLITE. These are derived marts — regenerable from the raw
-- archive and the seed. The governance store is SQLite for one reason only: it
-- has triggers, and the write-once ledgers must be enforced by the database
-- rather than by convention. DuckDB has no triggers, and that is the correct
-- split rather than a shortcoming. A mart protected against UPDATE is a mart you
-- cannot rebuild.
--
-- NOT NULL IS USED AS A DESIGN INSTRUMENT, as it is on the governance side. The
-- columns that are mandatory here are the ones whose absence silently produced a
-- defect in the predecessor: `available_from` on a clean deal, `confidence` on an
-- identity claim, `n_tests_in_run` on a seasonality cell.

-- =============================================================================
-- Plan 1 §5 — the raw archive
-- =============================================================================

-- §5.2. UNIQUE(file_hash) makes re-fetching free and makes "did the source
-- change?" answerable: a new hash for a date already held is a REVISION, which
-- source_revisions handles explicitly rather than by overwriting.
CREATE TABLE deal_source_files (
    source_file_id    BIGINT PRIMARY KEY,
    exchange          TEXT NOT NULL,          -- NSE | BSE
    report_type       TEXT NOT NULL,          -- BULK | BLOCK | FII_DII | SHP
    source_url        TEXT NOT NULL,
    report_date       DATE NOT NULL,
    downloaded_at     TIMESTAMP NOT NULL,
    file_name         TEXT NOT NULL,
    file_hash         TEXT NOT NULL,          -- SHA-256 of the raw bytes
    file_bytes        BIGINT NOT NULL,
    parser_version    TEXT NOT NULL,
    row_count         INTEGER,
    -- A parse failure STILL archives the bytes and records the failure. That is
    -- the difference between a system that survives a source format change and
    -- one that silently loses a day.
    ingestion_status  TEXT NOT NULL CHECK (ingestion_status IN
                        ('OK','PARSE_FAILED','FETCH_FAILED','EMPTY')),
    error_message     TEXT,
    http_status       INTEGER,
    fetch_duration_ms INTEGER,
    UNIQUE (file_hash),
    UNIQUE (exchange, report_type, report_date, parser_version)
);

-- §5.3. Verbatim source rows. Never cleaned, never corrected. quantity and price
-- are TEXT because the source sometimes carries commas — cleaning happens
-- downstream where it can be versioned and undone.
CREATE TABLE institutional_deals_raw (
    raw_deal_id       BIGINT PRIMARY KEY,
    source_file_id    BIGINT NOT NULL REFERENCES deal_source_files (source_file_id),
    exchange          TEXT NOT NULL,
    deal_type         TEXT NOT NULL CHECK (deal_type IN ('BULK','BLOCK')),
    trade_date        DATE NOT NULL,
    symbol_raw        TEXT,
    security_name_raw TEXT,
    client_name_raw   TEXT,
    side_raw          TEXT,
    quantity_raw      TEXT,
    deal_price_raw    TEXT,
    remarks_raw       TEXT,
    raw_row_json      TEXT NOT NULL,          -- the complete original row
    row_index         INTEGER NOT NULL,       -- position within the file
    ingested_at       TIMESTAMP NOT NULL
);

-- §5.4. NSE and BSE silently restate. BOTH versions are kept: research uses the
-- version available at the decision date, because a restatement published in
-- 2020 cannot inform a 2015 signal. This is point-in-time discipline applied to
-- the source layer itself, which the predecessor never had.
CREATE TABLE source_revisions (
    revision_id       BIGINT PRIMARY KEY,
    exchange          TEXT NOT NULL,
    report_type       TEXT NOT NULL,
    report_date       DATE NOT NULL,
    prior_file_id     BIGINT NOT NULL REFERENCES deal_source_files (source_file_id),
    new_file_id       BIGINT NOT NULL REFERENCES deal_source_files (source_file_id),
    detected_at       TIMESTAMP NOT NULL,
    rows_added        INTEGER,
    rows_removed      INTEGER,
    rows_changed      INTEGER,
    review_status     TEXT NOT NULL DEFAULT 'PENDING'
);

-- =============================================================================
-- Plan 1 §6 — identity
-- =============================================================================

-- §6.1. merged_into_id matters: when a stock merges, its holder receives shares
-- in the acquirer. Treating that as a delisting-to-zero is a large downward
-- bias; ignoring it is an upward one. Both are wrong and the predecessor did
-- the second.
CREATE TABLE security_master (
    security_id       BIGINT PRIMARY KEY,
    isin              TEXT UNIQUE,
    canonical_symbol  TEXT NOT NULL,
    company_name      TEXT NOT NULL,
    listing_date      DATE,
    delisting_date    DATE,
    delisting_reason  TEXT,                   -- MERGER|ACQUISITION|SUSPENSION|UNKNOWN
    status            TEXT NOT NULL CHECK (status IN
                        ('ACTIVE','DELISTED','SUSPENDED','MERGED')),
    merged_into_id    BIGINT,
    source            TEXT NOT NULL,
    -- UNKNOWN beats inference (standing rule 9), so confidence is mandatory.
    confidence        TEXT NOT NULL CHECK (confidence IN ('HIGH','MEDIUM','LOW'))
);

-- §6.2. The point-in-time symbol map. Resolution goes through ONE function and a
-- test asserts no module builds its own lookup: 276 ISINs carry more than one
-- symbol and they account for 11.04% of deal rows.
CREATE TABLE symbol_history (
    symbol_history_id BIGINT PRIMARY KEY,
    security_id       BIGINT NOT NULL REFERENCES security_master (security_id),
    symbol            TEXT NOT NULL,
    exchange          TEXT NOT NULL,
    series            TEXT,
    valid_from        DATE NOT NULL,
    valid_to          DATE,                   -- NULL = current
    source            TEXT NOT NULL,
    UNIQUE (symbol, exchange, valid_from)
);

-- §6.3. The predecessor's dim_sector was current-only, which is a look-ahead: a
-- company classified "IT" today may have been "Textiles" in 2008. Where no
-- vintage exists the earliest known classification is carried backward and
-- marked LOW, and the outcome study reports those rows SEPARATELY.
CREATE TABLE sector_history (
    security_id       BIGINT NOT NULL REFERENCES security_master (security_id),
    sector            TEXT NOT NULL,
    industry          TEXT,
    classification    TEXT NOT NULL,          -- NIC|NSE|BSE|MANUAL
    valid_from        DATE NOT NULL,
    valid_to          DATE,
    confidence        TEXT NOT NULL,
    PRIMARY KEY (security_id, classification, valid_from)
);

-- §6.4/§6.5. Behaviour classifies before names do: Graviton never declares
-- itself a market maker, but 6,748 of 6,748 same-day round trips does.
CREATE TABLE participant_master (
    participant_id    BIGINT PRIMARY KEY,
    canonical_name    TEXT NOT NULL UNIQUE,
    participant_type  TEXT NOT NULL,
    classification_method TEXT NOT NULL CHECK (classification_method IN
                        ('BEHAVIOURAL','NAME_PATTERN','MANUAL')),
    parent_group_id   BIGINT,
    country           TEXT,
    confidence_level  TEXT NOT NULL CHECK (confidence_level IN
                        ('HIGH','MEDIUM','LOW','UNKNOWN')),
    first_seen        DATE,
    last_seen         DATE,
    deal_count        INTEGER,
    review_status     TEXT NOT NULL,          -- PENDING|REVIEWED|AUTO
    reviewed_by       TEXT,
    reviewed_at       TIMESTAMP,
    review_notes      TEXT
);

-- suggested_merge_id is how "no fuzzy auto-merge" is honoured: QE SECURITIES LLP
-- and QE SECURITIES get a suggestion recorded, stay separate entities, and the
-- owner decides. Nothing merges automatically.
CREATE TABLE participant_aliases (
    alias_id          BIGINT PRIMARY KEY,
    participant_id    BIGINT NOT NULL REFERENCES participant_master (participant_id),
    raw_name          TEXT NOT NULL UNIQUE,
    normalized_name   TEXT NOT NULL,
    mapping_method    TEXT NOT NULL CHECK (mapping_method IN ('EXACT','CLEANED','MANUAL')),
    mapping_confidence TEXT NOT NULL,
    suggested_merge_id BIGINT,                -- surfaced, never applied
    review_status     TEXT NOT NULL,
    reviewed_at       TIMESTAMP,
    review_notes      TEXT
);

-- §6.6. A deal is promoter-related when the participant matches a promoter
-- entity of that security VALID ON THE TRADE DATE — a point-in-time join, never
-- a current-list lookup.
CREATE TABLE promoter_entities (
    security_id       BIGINT NOT NULL REFERENCES security_master (security_id),
    entity_name       TEXT NOT NULL,
    normalized_name   TEXT NOT NULL,
    valid_from        DATE NOT NULL,
    valid_to          DATE,
    holding_pct       REAL,
    source_file_id    BIGINT,
    PRIMARY KEY (security_id, normalized_name, valid_from)
);

-- =============================================================================
-- Plan 1 §7 — the clean mart and outcomes
-- =============================================================================

-- §7.1. available_from is THE field the whole study rests on. It is a TIMESTAMP,
-- not a date, and it is established empirically (src/ingest/publication.py) —
-- never assumed. Where publication cannot be proven for a historical period it
-- takes the conservative bound and the row carries LOW confidence.
CREATE TABLE institutional_deals_clean (
    deal_id           BIGINT PRIMARY KEY,
    raw_deal_id       BIGINT NOT NULL REFERENCES institutional_deals_raw (raw_deal_id),
    security_id       BIGINT,
    participant_id    BIGINT,
    trade_date        DATE NOT NULL,
    available_from    TIMESTAMP NOT NULL,
    available_from_confidence TEXT NOT NULL CHECK (available_from_confidence IN
                        ('HIGH','MEDIUM','LOW')),
    entry_date        DATE NOT NULL,
    exchange          TEXT NOT NULL,
    deal_type         TEXT NOT NULL,
    side              TEXT NOT NULL CHECK (side IN ('BUY','SELL')),
    quantity          BIGINT NOT NULL,
    deal_price        REAL NOT NULL,
    gross_deal_value  REAL NOT NULL,
    adv20             REAL,
    deal_value_to_adv20 REAL,

    duplicate_group_id       BIGINT,
    same_day_round_trip_flag BOOLEAN NOT NULL,
    five_day_round_trip_flag BOOLEAN NOT NULL,
    internal_transfer_flag   BOOLEAN NOT NULL,
    promoter_related_flag    BOOLEAN NOT NULL,
    suspect_flag             BOOLEAN NOT NULL,
    unresolved_symbol_flag   BOOLEAN NOT NULL,
    -- Decision 0032: a symbol with no price coverage and no resolution route is
    -- excluded on coverage grounds, flagged rather than dropped, and counted in
    -- every study's exclusion table.
    uncovered_symbol_flag    BOOLEAN NOT NULL,
    eligible_for_research    BOOLEAN NOT NULL,
    -- Phase 4's gate: every clean deal either resolves or carries an explicit
    -- failure status. ZERO SILENT DROPS.
    ineligibility_reason     TEXT,

    clean_version     TEXT NOT NULL,
    created_at        TIMESTAMP NOT NULL
);

-- §7.2. The three interpretations, kept strictly separate and never silently
-- mixed.
CREATE TABLE deal_interpretation (
    interpretation_id BIGINT PRIMARY KEY,
    mode              TEXT NOT NULL CHECK (mode IN
                        ('INDIVIDUAL','ACCUMULATED','CONFIRMATION')),
    deal_id           BIGINT NOT NULL REFERENCES institutional_deals_clean (deal_id),
    position_id       BIGINT,
    sequence_index    INTEGER,
    is_initiation     BOOLEAN NOT NULL,
    is_confirmation   BOOLEAN NOT NULL,
    days_since_prior  INTEGER,
    cumulative_qty    BIGINT,
    cumulative_value  REAL,
    version           TEXT NOT NULL
);

-- §7.3. horizon_sessions is the primary unit (decision 0004); horizon_months
-- carries the 12-month primary horizon (decision 0034). Exactly one is set.
CREATE TABLE deal_forward_outcomes (
    outcome_id        BIGINT PRIMARY KEY,
    deal_id           BIGINT NOT NULL REFERENCES institutional_deals_clean (deal_id),
    interpretation_id BIGINT,
    horizon_sessions  INTEGER,
    horizon_months    INTEGER,
    entry_date        DATE NOT NULL,
    entry_price       REAL NOT NULL,
    exit_date         DATE NOT NULL,
    exit_price        REAL NOT NULL,
    -- Four cases, priced separately, aggregate reported under each. The
    -- predecessor's silent drop of delistings was worth roughly the whole
    -- measured effect.
    exit_reason       TEXT NOT NULL CHECK (exit_reason IN
                        ('HORIZON','DELISTED','MERGED','SUSPENDED')),
    recovery_factor   REAL,                   -- headline 0.0; 0.25/0.50 sensitivity

    stock_return      REAL NOT NULL,
    net_return        REAL NOT NULL,          -- after the Plan 2 §4 cost model

    max_adverse_excursion   REAL,
    max_favorable_excursion REAL,
    days_to_max_adverse     INTEGER,
    excursion_basis   TEXT NOT NULL CHECK (excursion_basis IN ('CLOSE','INTRADAY')),

    outcome_complete_flag BOOLEAN NOT NULL,
    calculation_version   TEXT NOT NULL,
    UNIQUE (deal_id, interpretation_id, horizon_sessions, horizon_months,
            recovery_factor, calculation_version)
);

-- Splitting benchmarks into their own table is what makes "at least 5
-- benchmarks" workable without nine near-identical columns, and lets a benchmark
-- be added later without a schema change. Every outcome carries all six.
CREATE TABLE outcome_benchmark_returns (
    outcome_id        BIGINT NOT NULL REFERENCES deal_forward_outcomes (outcome_id),
    benchmark_id      TEXT NOT NULL,
    benchmark_return  REAL NOT NULL,
    relative_return   REAL NOT NULL,
    -- CHAR_MATCHED degrades when a cell is thin. Recording the level used per
    -- event is the difference between a declared match and a silent one.
    match_fallback_level TEXT,
    PRIMARY KEY (outcome_id, benchmark_id)
);

-- =============================================================================
-- Plan 2 §7.3 — seasonality
-- =============================================================================

-- n_tests_in_run is NOT NULL and is the ACTUAL count for the run. The literal
-- 31,893,556 is never hard-coded anywhere and a test greps for it.
CREATE TABLE seasonality_cell (
    seasonality_cell_id BIGINT PRIMARY KEY,
    atlas_version     TEXT NOT NULL,
    entity_id         TEXT NOT NULL,
    entity_type       TEXT NOT NULL CHECK (entity_type IN ('STOCK','INDEX','POOLED')),
    window_days       INTEGER NOT NULL,
    alignment_scheme  TEXT NOT NULL,
    calendar_position TEXT NOT NULL,
    return_basis      TEXT NOT NULL,

    observation_count INTEGER NOT NULL,
    positive_count    INTEGER NOT NULL,
    positive_rate     REAL NOT NULL,
    mean_return       REAL NOT NULL,
    median_return     REAL NOT NULL,
    baseline_positive_rate REAL NOT NULL,     -- window-specific, MEASURED
    baseline_return   REAL NOT NULL,
    relative_edge     REAL NOT NULL,

    raw_p_value       REAL NOT NULL,
    corrected_p_value REAL,
    correction_method TEXT,
    permutation_p_value REAL,
    spa_p_value       REAL,

    near_duplicate_group_id BIGINT,
    group_member_count INTEGER,
    out_of_sample_status TEXT,                -- UNTESTED|PASS|FAIL
    cost_adjusted_status TEXT,                -- SURVIVES|DIES_ON_COSTS
    eligibility_status TEXT NOT NULL,         -- ELIGIBLE|TOO_FEW_OBS|DUPLICATE_ENTITY
    n_tests_in_run    BIGINT NOT NULL
);

CREATE INDEX idx_raw_deal_source ON institutional_deals_raw (source_file_id);
CREATE INDEX idx_raw_deal_date ON institutional_deals_raw (trade_date, symbol_raw);
CREATE INDEX idx_clean_deal_date ON institutional_deals_clean (trade_date, security_id);
CREATE INDEX idx_clean_eligible ON institutional_deals_clean (eligible_for_research, trade_date);
CREATE INDEX idx_symbol_history_lookup ON symbol_history (symbol, exchange, valid_from);
CREATE INDEX idx_outcome_deal ON deal_forward_outcomes (deal_id);
CREATE INDEX idx_seasonality_entity ON seasonality_cell (atlas_version, entity_id);
