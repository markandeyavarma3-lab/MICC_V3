-- schemas.sql — FINAL-STATE schema (all migrations applied), reconstructed
-- for the handover pack. Two engines, two files logically:
--   DuckDB   : db/research_prod.duckdb   (or research_dev.duckdb under RESEARCH_ENV=dev)
--   SQLite   : db/governance_prod.sqlite (or governance_dev.sqlite)
--
-- This is a CONSOLIDATED reconstruction combining:
--   migrations/0001_warehouse.duckdb.sql
--   migrations/0002_source_revisions_storable.duckdb.sql   (drops a constraint, adds revision_number)
--   migrations/0003_symbol_history_allows_isin_change.duckdb.sql  (UNIQUE key gains security_id)
--   migrations/0004_participant_oi.duckdb.sql
-- and
--   migrations/0001_governance.sqlite.sql
--   migrations/0002_trial_families.sqlite.sql              (adds family_charge)
--   migrations/0003_registration_replace_is_not_an_amendment.sqlite.sql  (adds a trigger)
--
-- DO NOT run this file directly against a fresh database — use
-- src/common/migrate.py's migrate_duckdb()/migrate_sqlite() against the
-- individual migrations/ files in order, so schema_migrations is populated
-- correctly. This file exists for READING the current shape only.

-- =============================================================================
-- DuckDB — db/research_prod.duckdb
-- =============================================================================

-- Raw archive ------------------------------------------------------------

CREATE TABLE deal_source_files (
    source_file_id    BIGINT PRIMARY KEY,
    exchange          TEXT NOT NULL,          -- NSE | BSE
    report_type       TEXT NOT NULL,          -- BULK | BLOCK | FII_DII | SHP
    source_url        TEXT NOT NULL,
    report_date       DATE NOT NULL,
    downloaded_at     TIMESTAMP NOT NULL,
    file_name         TEXT NOT NULL,
    file_hash         TEXT NOT NULL,          -- SHA-256 of raw bytes
    file_bytes        BIGINT NOT NULL,
    parser_version    TEXT NOT NULL,
    row_count         INTEGER,
    ingestion_status  TEXT NOT NULL CHECK (ingestion_status IN
                        ('OK','PARSE_FAILED','FETCH_FAILED','EMPTY')),
    error_message     TEXT,
    http_status       INTEGER,
    fetch_duration_ms INTEGER,
    revision_number   INTEGER NOT NULL DEFAULT 0,   -- added 0002
    UNIQUE (file_hash)
    -- NOTE: the original UNIQUE (exchange, report_type, report_date, parser_version)
    -- was DROPPED in migration 0002 — it made a legitimate same-day revision
    -- unstorable, which contradicted source_revisions' own stated purpose.
);

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
    raw_row_json      TEXT NOT NULL,
    row_index         INTEGER NOT NULL,
    ingested_at       TIMESTAMP NOT NULL
);

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

-- Identity -----------------------------------------------------------------

CREATE TABLE security_master (
    security_id       BIGINT PRIMARY KEY,
    isin              TEXT UNIQUE,
    canonical_symbol  TEXT NOT NULL,
    company_name      TEXT NOT NULL,
    listing_date      DATE,
    delisting_date    DATE,
    delisting_reason  TEXT,                   -- MERGER|ACQUISITION|SUSPENSION|UNKNOWN
    status            TEXT NOT NULL CHECK (status IN ('ACTIVE','DELISTED','SUSPENDED','MERGED')),
    merged_into_id    BIGINT,
    source            TEXT NOT NULL,
    confidence        TEXT NOT NULL CHECK (confidence IN ('HIGH','MEDIUM','LOW'))
);

CREATE TABLE symbol_history (
    symbol_history_id BIGINT PRIMARY KEY,
    security_id       BIGINT NOT NULL REFERENCES security_master (security_id),
    symbol            TEXT NOT NULL,
    exchange          TEXT NOT NULL,
    series            TEXT,
    valid_from        DATE NOT NULL,
    valid_to          DATE,
    source            TEXT NOT NULL,
    UNIQUE (symbol, exchange, valid_from, security_id)   -- security_id added 0003: a symbol CAN begin two lives on the same date (e.g. GREENLAM, ISIN change)
);
CREATE INDEX idx_symbol_history_lookup ON symbol_history (symbol, exchange, valid_from);

CREATE TABLE sector_history (        -- 0 rows as of last measurement
    security_id       BIGINT NOT NULL REFERENCES security_master (security_id),
    sector            TEXT NOT NULL,
    industry          TEXT,
    classification    TEXT NOT NULL,          -- NIC|NSE|BSE|MANUAL
    valid_from        DATE NOT NULL,
    valid_to          DATE,
    confidence        TEXT NOT NULL,
    PRIMARY KEY (security_id, classification, valid_from)
);

CREATE TABLE participant_master (    -- 0 rows as of last measurement
    participant_id    BIGINT PRIMARY KEY,
    canonical_name    TEXT NOT NULL UNIQUE,
    participant_type  TEXT NOT NULL,
    classification_method TEXT NOT NULL CHECK (classification_method IN ('BEHAVIOURAL','NAME_PATTERN','MANUAL')),
    parent_group_id   BIGINT,
    country           TEXT,
    confidence_level  TEXT NOT NULL CHECK (confidence_level IN ('HIGH','MEDIUM','LOW','UNKNOWN')),
    first_seen        DATE,
    last_seen         DATE,
    deal_count        INTEGER,
    review_status     TEXT NOT NULL,
    reviewed_by       TEXT,
    reviewed_at       TIMESTAMP,
    review_notes      TEXT
);

CREATE TABLE participant_aliases (   -- 0 rows as of last measurement
    alias_id          BIGINT PRIMARY KEY,
    participant_id    BIGINT NOT NULL REFERENCES participant_master (participant_id),
    raw_name          TEXT NOT NULL UNIQUE,
    normalized_name   TEXT NOT NULL,
    mapping_method    TEXT NOT NULL CHECK (mapping_method IN ('EXACT','CLEANED','MANUAL')),
    mapping_confidence TEXT NOT NULL,
    suggested_merge_id BIGINT,                -- surfaced, never auto-applied
    review_status     TEXT NOT NULL,
    reviewed_at       TIMESTAMP,
    review_notes      TEXT
);

CREATE TABLE promoter_entities (     -- 0 rows as of last measurement
    security_id       BIGINT NOT NULL REFERENCES security_master (security_id),
    entity_name       TEXT NOT NULL,
    normalized_name   TEXT NOT NULL,
    valid_from        DATE NOT NULL,
    valid_to          DATE,
    holding_pct       REAL,
    source_file_id    BIGINT,
    PRIMARY KEY (security_id, normalized_name, valid_from)
);

-- Clean mart + outcomes ------------------------------------------------------

CREATE TABLE institutional_deals_clean (
    deal_id           BIGINT PRIMARY KEY,
    raw_deal_id       BIGINT NOT NULL REFERENCES institutional_deals_raw (raw_deal_id),
    security_id       BIGINT,
    participant_id    BIGINT,
    trade_date        DATE NOT NULL,
    available_from    TIMESTAMP NOT NULL,
    available_from_confidence TEXT NOT NULL CHECK (available_from_confidence IN ('HIGH','MEDIUM','LOW')),
    entry_date        DATE NOT NULL,
    exchange          TEXT NOT NULL,
    deal_type         TEXT NOT NULL,
    side              TEXT NOT NULL CHECK (side IN ('BUY','SELL')),
    quantity          BIGINT NOT NULL,
    deal_price        REAL NOT NULL,
    gross_deal_value  REAL NOT NULL,
    adv20             REAL,
    deal_value_to_adv20 REAL,
    duplicate_group_id       BIGINT,           -- NULL on all rows as of last audit
    same_day_round_trip_flag BOOLEAN NOT NULL,
    five_day_round_trip_flag BOOLEAN NOT NULL, -- FALSE on all rows as of last audit
    internal_transfer_flag   BOOLEAN NOT NULL, -- FALSE on all rows as of last audit
    promoter_related_flag    BOOLEAN NOT NULL, -- FALSE on all rows as of last audit
    suspect_flag              BOOLEAN NOT NULL, -- FALSE on all rows as of last audit
    unresolved_symbol_flag   BOOLEAN NOT NULL,
    uncovered_symbol_flag    BOOLEAN NOT NULL,
    eligible_for_research    BOOLEAN NOT NULL,
    ineligibility_reason     TEXT,             -- single-priority-ordered; see decision 0056 amendment 3
    clean_version     TEXT NOT NULL,
    created_at        TIMESTAMP NOT NULL
);
CREATE INDEX idx_clean_deal_date ON institutional_deals_clean (trade_date, security_id);
CREATE INDEX idx_clean_eligible ON institutional_deals_clean (eligible_for_research, trade_date);

CREATE TABLE deal_interpretation (   -- 0 rows as of last measurement
    interpretation_id BIGINT PRIMARY KEY,
    mode              TEXT NOT NULL CHECK (mode IN ('INDIVIDUAL','ACCUMULATED','CONFIRMATION')),
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
    exit_reason       TEXT NOT NULL CHECK (exit_reason IN ('HORIZON','DELISTED','MERGED','SUSPENDED')),
    recovery_factor   REAL,                    -- headline 0.0; sensitivity 0.25/0.50
    stock_return      REAL NOT NULL,
    net_return        REAL NOT NULL,           -- after the full cost model
    max_adverse_excursion   REAL,
    max_favorable_excursion REAL,
    days_to_max_adverse     INTEGER,
    excursion_basis   TEXT NOT NULL CHECK (excursion_basis IN ('CLOSE','INTRADAY')),
    outcome_complete_flag BOOLEAN NOT NULL,
    calculation_version   TEXT NOT NULL,
    UNIQUE (deal_id, interpretation_id, horizon_sessions, horizon_months, recovery_factor, calculation_version)
);
CREATE INDEX idx_outcome_deal ON deal_forward_outcomes (deal_id);

CREATE TABLE outcome_benchmark_returns (
    outcome_id        BIGINT NOT NULL REFERENCES deal_forward_outcomes (outcome_id),
    benchmark_id      TEXT NOT NULL,
    benchmark_return  REAL NOT NULL,
    relative_return   REAL NOT NULL,
    match_fallback_level TEXT,                 -- CHAR_MATCHED degradation level, recorded not silent
    PRIMARY KEY (outcome_id, benchmark_id)
);

-- Seasonality (schema exists; 0 rows — Engine 2 killed on power arithmetic
-- before any cell was ever computed, decision 2026-09-12) --------------------

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
    baseline_positive_rate REAL NOT NULL,
    baseline_return   REAL NOT NULL,
    relative_edge     REAL NOT NULL,
    raw_p_value       REAL NOT NULL,
    corrected_p_value REAL,
    correction_method TEXT,
    permutation_p_value REAL,
    spa_p_value       REAL,
    near_duplicate_group_id BIGINT,
    group_member_count INTEGER,
    out_of_sample_status TEXT,
    cost_adjusted_status TEXT,
    eligibility_status TEXT NOT NULL,
    n_tests_in_run    BIGINT NOT NULL          -- the ACTUAL run count, never the hardcoded 31,893,556 literal
);
CREATE INDEX idx_seasonality_entity ON seasonality_cell (atlas_version, entity_id);

-- F&O participant-wise OI (migration 0004, decision 0058) -------------------

CREATE TABLE participant_oi (
    session_date        DATE NOT NULL,
    category             VARCHAR NOT NULL CHECK (category IN ('FII','DII','Pro','Client','TOTAL')),
    index_fut_long       DOUBLE, index_fut_short  DOUBLE, index_fut_net DOUBLE,
    index_call_long      DOUBLE, index_call_short DOUBLE,
    index_put_long       DOUBLE, index_put_short  DOUBLE,
    stock_fut_long       DOUBLE, stock_fut_short  DOUBLE, stock_fut_net  DOUBLE,
    stock_call_long      DOUBLE, stock_put_long   DOUBLE,
    source               VARCHAR NOT NULL DEFAULT 'v1_export',
    loaded_at            TIMESTAMP NOT NULL DEFAULT current_timestamp,
    UNIQUE (session_date, category)
);

-- Other indexes carried from 0001 -------------------------------------------
CREATE INDEX idx_raw_deal_source ON institutional_deals_raw (source_file_id);
CREATE INDEX idx_raw_deal_date ON institutional_deals_raw (trade_date, symbol_raw);
CREATE INDEX idx_source_file_session ON deal_source_files (exchange, report_type, report_date);

-- Also present in the live warehouse but NOT DDL-migrated tables (built by
-- src/warehouse/spine.py, benchmarks.py, charmatch.py directly, no migration
-- file defines their DDL — infer shape from those modules if needed):
--   price_spine, price_spine_adj, fno_spine, char_panel, benchmark_daily

-- =============================================================================
-- SQLite — db/governance_prod.sqlite   (PRAGMA foreign_keys = ON)
-- =============================================================================

CREATE TABLE artefact (
    artefact_hash    TEXT PRIMARY KEY,
    artefact_type    TEXT NOT NULL CHECK (artefact_type IN ('SOURCE','TABLE','FEATURE','RESULT','FIGURE','CONFIG')),
    logical_name     TEXT NOT NULL,
    produced_by      TEXT NOT NULL,
    code_commit      TEXT NOT NULL,
    produced_at      TEXT NOT NULL,
    row_count        INTEGER,
    byte_size        INTEGER,
    params_json      TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX idx_artefact_name ON artefact (logical_name, produced_at);
CREATE INDEX idx_artefact_type ON artefact (artefact_type);
-- TRIGGERS: artefact_no_update, artefact_no_delete — both raise unconditionally (append-only, content-addressed)

CREATE TABLE artefact_edge (
    child_hash       TEXT NOT NULL REFERENCES artefact (artefact_hash),
    parent_hash      TEXT NOT NULL REFERENCES artefact (artefact_hash),
    edge_role        TEXT NOT NULL,
    PRIMARY KEY (child_hash, parent_hash)
);
CREATE INDEX idx_edge_parent ON artefact_edge (parent_hash);
-- TRIGGERS: artefact_edge_no_update, artefact_edge_no_delete — both raise unconditionally

CREATE TABLE merkle_log (
    as_of_date       TEXT PRIMARY KEY,
    merkle_root      TEXT NOT NULL,
    artefact_count   INTEGER NOT NULL,
    computed_at      TEXT NOT NULL
);
-- TRIGGER: merkle_log_no_update — raises unconditionally

CREATE TABLE trial_counter (        -- legacy flat counter; superseded by family_charge (see below)
    trial_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    source           TEXT NOT NULL,
    description      TEXT NOT NULL,
    recorded_at      TEXT NOT NULL
);
-- TRIGGERS: trial_counter_no_delete, trial_counter_no_update — both raise unconditionally

CREATE TABLE experiment_registry (
    experiment_id    TEXT PRIMARY KEY,
    engine_id        TEXT,
    hypothesis       TEXT NOT NULL,
    prior_belief     TEXT NOT NULL,
    created_at       TEXT NOT NULL,
    created_by       TEXT NOT NULL,
    data_version     TEXT NOT NULL,
    universe_definition TEXT NOT NULL,
    participant_definition TEXT,
    interpretation_mode TEXT,
    holding_period   TEXT NOT NULL,
    entry_policy     TEXT NOT NULL,
    exit_policy      TEXT NOT NULL,
    cost_policy      TEXT NOT NULL,
    benchmark_policy TEXT NOT NULL,
    training_period  TEXT NOT NULL,
    validation_period TEXT NOT NULL,
    final_test_period TEXT NOT NULL,
    search_space_definition TEXT NOT NULL,
    test_count       INTEGER NOT NULL CHECK (test_count > 0),
    multiple_testing_policy TEXT NOT NULL,
    permutation_policy TEXT NOT NULL,
    pass_bar         TEXT NOT NULL,
    kill_criteria    TEXT NOT NULL,
    exploratory_prior_run TEXT,
    spec_hash        TEXT NOT NULL UNIQUE,
    trials_before    INTEGER NOT NULL,
    configuration_json TEXT NOT NULL,
    code_commit_hash TEXT NOT NULL,
    status           TEXT NOT NULL CHECK (status IN
                        ('DRAFT','REGISTERED','RUNNING','REJECTED','VALIDATED','PAPER_TRIAL','PROMOTED','RETIRED','PAUSED')),
    decision_reason  TEXT
);
-- TRIGGERS:
--   experiment_spec_frozen (BEFORE UPDATE, when OLD.status != 'DRAFT' and any
--     of spec_hash/hypothesis/pass_bar/kill_criteria/test_count/holding_period/
--     cost_policy/benchmark_policy changes) — raises
--   experiment_no_delete (BEFORE DELETE) — raises unconditionally
--   experiment_replace_is_not_an_amendment (BEFORE INSERT, migration 0003 —
--     closes the INSERT OR REPLACE bypass: SQLite implements REPLACE as
--     delete-then-insert, which neither of the above two triggers catches)
--     — raises when an existing non-DRAFT row with the same experiment_id
--     would have any of the frozen fields change; an IDENTICAL re-registration
--     is still allowed (idempotent)

CREATE TABLE study_result (
    result_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id    TEXT NOT NULL REFERENCES experiment_registry (experiment_id),
    stratum          TEXT NOT NULL,
    stratum_type     TEXT NOT NULL,
    horizon_months   INTEGER,
    benchmark_id     TEXT,
    n_events         INTEGER NOT NULL,
    n_independent    INTEGER NOT NULL,
    mean_return      REAL,
    median_return    REAL,
    hit_rate         REAL,
    raw_p_value      REAL,
    corrected_p_value REAL,
    correction_method TEXT NOT NULL,
    n_tests_in_family INTEGER NOT NULL CHECK (n_tests_in_family > 0),
    bootstrap_ci_low  REAL,
    bootstrap_ci_high REAL,
    verdict          TEXT NOT NULL CHECK (verdict IN ('PASS','FAIL','UNDERPOWERED')),
    input_hashes     TEXT NOT NULL,
    code_commit      TEXT NOT NULL,
    computed_at      TEXT NOT NULL
);
CREATE INDEX idx_result_experiment ON study_result (experiment_id, stratum);
-- TRIGGERS: study_result_no_update, study_result_no_delete — both raise unconditionally

CREATE TABLE fee_schedule (
    fee_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    component        TEXT NOT NULL CHECK (component IN ('STT','TXN','SEBI','GST','STAMP','BROKERAGE')),
    segment          TEXT NOT NULL CHECK (segment IN ('EQ_DELIVERY','EQ_INTRADAY')),
    exchange         TEXT CHECK (exchange IN ('NSE','BSE') OR exchange IS NULL),
    side             TEXT NOT NULL CHECK (side IN ('BUY','SELL','BOTH')),
    rate             REAL NOT NULL,
    rate_basis       TEXT NOT NULL CHECK (rate_basis IN ('PCT_TURNOVER','PER_CRORE','PCT_OF_BASE')),
    applies_to_base  TEXT,
    effective_from   TEXT NOT NULL,
    effective_to     TEXT,
    source_url       TEXT NOT NULL,
    source_note      TEXT NOT NULL,
    verified         INTEGER NOT NULL DEFAULT 0,
    verified_at      TEXT
);
CREATE INDEX idx_fee_lookup ON fee_schedule (component, segment, exchange, effective_from);

CREATE TABLE engine_config (         -- 0 rows by design — no trading engine enabled
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
    false_discovery_policy TEXT NOT NULL,
    enabled_status   TEXT NOT NULL DEFAULT 'DISABLED' CHECK (enabled_status IN ('DISABLED','SHADOW','ENABLED')),
    version          TEXT NOT NULL
);

CREATE TABLE institutional_signal_ledger (   -- 0 rows by design
    signal_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    engine_id        TEXT NOT NULL REFERENCES engine_config (engine_id),
    as_of_date       TEXT NOT NULL,
    deal_id          INTEGER,
    security_id      INTEGER,
    participant_id   INTEGER,
    interpretation_mode TEXT NOT NULL,
    intended_horizon INTEGER,
    signal_type      TEXT NOT NULL,
    signal_status    TEXT NOT NULL CHECK (signal_status IN ('APPROVED','REJECTED','BLOCKED','SKIPPED')),
    reason           TEXT NOT NULL,
    seasonality_cell_id INTEGER,
    engine_config_version TEXT NOT NULL,
    experiment_id    TEXT REFERENCES experiment_registry (experiment_id),
    input_hashes     TEXT NOT NULL,
    code_commit      TEXT NOT NULL,
    created_at       TEXT NOT NULL
);
-- TRIGGERS:
--   signal_requires_enabled_engine (BEFORE INSERT, when the referenced
--     engine_config.enabled_status = 'DISABLED') — raises. A disabled engine
--     emitting a signal fails at the database rather than in a result.
--   signal_no_update, signal_no_delete — both raise unconditionally

CREATE TABLE family_charge (         -- migration 0002 — makes trial families actually accumulate
    charge_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    family_id        TEXT    NOT NULL,
    trials_added     INTEGER NOT NULL CHECK (trials_added >= 0),
    trials_after     INTEGER NOT NULL CHECK (trials_after >= 0),
    dof              INTEGER,
    required_t       REAL    NOT NULL CHECK (required_t > 0),
    experiment_id    TEXT,                    -- NULL only for exploratory episodes, still charged
    description      TEXT    NOT NULL,
    code_commit_hash TEXT,
    recorded_at      TEXT    NOT NULL
);
CREATE INDEX idx_family_charge_family ON family_charge (family_id, charge_id);
-- TRIGGERS:
--   family_charge_no_update, family_charge_no_delete — both raise unconditionally
--   family_charge_monotonic (BEFORE INSERT, when NEW.trials_after < the
--     family's current MAX(trials_after)) — raises
