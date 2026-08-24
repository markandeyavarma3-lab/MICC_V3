-- 0002_source_revisions_storable.duckdb.sql
-- Make a source revision physically storable. It was not.
--
-- THE DEFECT IS IN PLAN 1 ITSELF, NOT IN THE TRANSCRIPTION.
--
-- Plan 1 §5.2 specifies two constraints on deal_source_files:
--
--     UNIQUE (file_hash),
--     UNIQUE (exchange, report_type, report_date, parser_version)
--
-- Plan 1 §5.4 then specifies what happens to a restatement:
--
--     "A revision is a new file_hash for a (exchange, report_type, report_date)
--      already held. ... BOTH VERSIONS ARE KEPT. Research uses the version
--      available at the decision date — a restatement published in 2020 cannot
--      inform a 2015 signal."
--
-- These cannot both hold. The second constraint rejects the second version, so
-- the point-in-time discipline §5.4 exists to provide was unimplementable as
-- specified. Verified empirically 2026-08-23 rather than argued:
--
--     first file for NSE/BULK/2026-08-21         -> inserted
--     revision, same date, different file_hash   -> Constraint Error:
--         Duplicate key "exchange: NSE, report_type: BULK,
--         report_date: 2026-08-21, parser_version: v1"
--
-- THE SECOND CONSTRAINT ADDS NOTHING AND IS DROPPED. Its purpose was to stop the
-- same file being ingested twice — but UNIQUE(file_hash) already does that, and
-- does it better, because the same bytes carry the same hash however they are
-- named or dated. All the second constraint contributed was forbidding the one
-- thing §5.4 requires be allowed.
--
-- `revision_number` is added anyway, defaulting to 0: not to enforce anything,
-- but so a restatement can SAY it is the second version rather than leaving a
-- reader to infer it from downloaded_at.
--
-- WHY THIS REBUILDS SEVEN TABLES. DuckDB supports neither ALTER TABLE DROP
-- CONSTRAINT nor dropping a referenced table, so the constraint cannot be
-- removed in place and the parent cannot be replaced while anything points at
-- it. deal_source_files is the root of a chain seven deep:
--
--     deal_source_files <- institutional_deals_raw <- institutional_deals_clean
--       <- deal_interpretation
--       <- deal_forward_outcomes <- outcome_benchmark_returns
--     deal_source_files <- source_revisions
--
-- All of them are empty today, so the copies below are no-ops. They are written
-- anyway: a migration that only works on an empty database is not a migration.

CREATE TABLE _bk_obr AS SELECT * FROM outcome_benchmark_returns;
CREATE TABLE _bk_dfo AS SELECT * FROM deal_forward_outcomes;
CREATE TABLE _bk_di  AS SELECT * FROM deal_interpretation;
CREATE TABLE _bk_idc AS SELECT * FROM institutional_deals_clean;
CREATE TABLE _bk_idr AS SELECT * FROM institutional_deals_raw;
CREATE TABLE _bk_sr  AS SELECT * FROM source_revisions;

DROP TABLE outcome_benchmark_returns;
DROP TABLE deal_forward_outcomes;
DROP TABLE deal_interpretation;
DROP TABLE institutional_deals_clean;
DROP TABLE institutional_deals_raw;
DROP TABLE source_revisions;

CREATE TABLE deal_source_files_v2 (
    source_file_id    BIGINT PRIMARY KEY,
    exchange          TEXT NOT NULL,
    report_type       TEXT NOT NULL,
    source_url        TEXT NOT NULL,
    report_date       DATE NOT NULL,
    downloaded_at     TIMESTAMP NOT NULL,
    file_name         TEXT NOT NULL,
    file_hash         TEXT NOT NULL,
    file_bytes        BIGINT NOT NULL,
    parser_version    TEXT NOT NULL,
    row_count         INTEGER,
    ingestion_status  TEXT NOT NULL CHECK (ingestion_status IN
                        ('OK','PARSE_FAILED','FETCH_FAILED','EMPTY')),
    error_message     TEXT,
    http_status       INTEGER,
    fetch_duration_ms INTEGER,
    revision_number   INTEGER NOT NULL DEFAULT 0,
    UNIQUE (file_hash)
);

INSERT INTO deal_source_files_v2 (
    source_file_id, exchange, report_type, source_url, report_date, downloaded_at,
    file_name, file_hash, file_bytes, parser_version, row_count, ingestion_status,
    error_message, http_status, fetch_duration_ms, revision_number)
SELECT source_file_id, exchange, report_type, source_url, report_date, downloaded_at,
    file_name, file_hash, file_bytes, parser_version, row_count, ingestion_status,
    error_message, http_status, fetch_duration_ms, 0
FROM deal_source_files;

DROP TABLE deal_source_files;
ALTER TABLE deal_source_files_v2 RENAME TO deal_source_files;

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
    uncovered_symbol_flag    BOOLEAN NOT NULL,
    eligible_for_research    BOOLEAN NOT NULL,
    ineligibility_reason     TEXT,
    clean_version     TEXT NOT NULL,
    created_at        TIMESTAMP NOT NULL
);

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
    exit_reason       TEXT NOT NULL CHECK (exit_reason IN
                        ('HORIZON','DELISTED','MERGED','SUSPENDED')),
    recovery_factor   REAL,
    stock_return      REAL NOT NULL,
    net_return        REAL NOT NULL,
    max_adverse_excursion   REAL,
    max_favorable_excursion REAL,
    days_to_max_adverse     INTEGER,
    excursion_basis   TEXT NOT NULL CHECK (excursion_basis IN ('CLOSE','INTRADAY')),
    outcome_complete_flag BOOLEAN NOT NULL,
    calculation_version   TEXT NOT NULL,
    UNIQUE (deal_id, interpretation_id, horizon_sessions, horizon_months,
            recovery_factor, calculation_version)
);

CREATE TABLE outcome_benchmark_returns (
    outcome_id        BIGINT NOT NULL REFERENCES deal_forward_outcomes (outcome_id),
    benchmark_id      TEXT NOT NULL,
    benchmark_return  REAL NOT NULL,
    relative_return   REAL NOT NULL,
    match_fallback_level TEXT,
    PRIMARY KEY (outcome_id, benchmark_id)
);

INSERT INTO source_revisions SELECT * FROM _bk_sr;
INSERT INTO institutional_deals_raw SELECT * FROM _bk_idr;
INSERT INTO institutional_deals_clean SELECT * FROM _bk_idc;
INSERT INTO deal_interpretation SELECT * FROM _bk_di;
INSERT INTO deal_forward_outcomes SELECT * FROM _bk_dfo;
INSERT INTO outcome_benchmark_returns SELECT * FROM _bk_obr;

DROP TABLE _bk_obr;
DROP TABLE _bk_dfo;
DROP TABLE _bk_di;
DROP TABLE _bk_idc;
DROP TABLE _bk_idr;
DROP TABLE _bk_sr;

CREATE INDEX idx_raw_deal_source ON institutional_deals_raw (source_file_id);
CREATE INDEX idx_raw_deal_date ON institutional_deals_raw (trade_date, symbol_raw);
CREATE INDEX idx_clean_deal_date ON institutional_deals_clean (trade_date, security_id);
CREATE INDEX idx_clean_eligible ON institutional_deals_clean (eligible_for_research, trade_date);
CREATE INDEX idx_outcome_deal ON deal_forward_outcomes (deal_id);
CREATE INDEX idx_source_file_session ON deal_source_files (exchange, report_type, report_date);
