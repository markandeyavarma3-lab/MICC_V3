-- 0001_governance.sqlite.sql
-- Append-only governance store: provenance DAG, experiment registry, trial
-- counter, study results, and the engine tables that stay empty in v1.
--
-- SQLite rather than DuckDB for exactly one reason: it has triggers, and the
-- write-once property has to be enforced by the database rather than by
-- convention. Its predecessor's equivalent triggers were verified working during
-- the 2026-08-16 audit — an UPDATE and a DELETE against a prediction were both
-- refused.

PRAGMA foreign_keys = ON;

-- =============================================================================
-- Provenance DAG (Plan 2 §8)
-- =============================================================================

CREATE TABLE artefact (
    artefact_hash    TEXT PRIMARY KEY,
    artefact_type    TEXT NOT NULL CHECK (artefact_type IN
                        ('SOURCE','TABLE','FEATURE','RESULT','FIGURE','CONFIG')),
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

CREATE TABLE artefact_edge (
    child_hash       TEXT NOT NULL REFERENCES artefact (artefact_hash),
    parent_hash      TEXT NOT NULL REFERENCES artefact (artefact_hash),
    edge_role        TEXT NOT NULL,
    PRIMARY KEY (child_hash, parent_hash)
);

CREATE INDEX idx_edge_parent ON artefact_edge (parent_hash);

-- Append-only. Walking the DAG backwards must reach the same bytes every time,
-- which an editable node would not guarantee.
CREATE TRIGGER artefact_no_update BEFORE UPDATE ON artefact
BEGIN
    SELECT RAISE(ABORT, 'artefacts are content-addressed and immutable: a changed artefact is a new hash, not an edit');
END;

CREATE TRIGGER artefact_no_delete BEFORE DELETE ON artefact
BEGIN
    SELECT RAISE(ABORT, 'artefacts are append-only: deleting one orphans every result derived from it');
END;

CREATE TRIGGER artefact_edge_no_update BEFORE UPDATE ON artefact_edge
BEGIN
    SELECT RAISE(ABORT, 'provenance edges are immutable');
END;

CREATE TRIGGER artefact_edge_no_delete BEFORE DELETE ON artefact_edge
BEGIN
    SELECT RAISE(ABORT, 'provenance edges are append-only');
END;

-- One verifiable fingerprint per day over the whole graph.
CREATE TABLE merkle_log (
    as_of_date       TEXT PRIMARY KEY,
    merkle_root      TEXT NOT NULL,
    artefact_count   INTEGER NOT NULL,
    computed_at      TEXT NOT NULL
);

CREATE TRIGGER merkle_log_no_update BEFORE UPDATE ON merkle_log
BEGIN
    SELECT RAISE(ABORT, 'the merkle log is append-only');
END;

-- =============================================================================
-- Trial counter (Plan 2 §2.2)
-- =============================================================================
-- Carried from MICCV2 at 47 + 21 legacy = 68, monotonic, never reset.
-- Applied to everything. MICCV2 deflated challengers while exempting its
-- incumbent champion; that asymmetry is the self-deception this counter exists
-- to prevent.

CREATE TABLE trial_counter (
    trial_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    source           TEXT NOT NULL,
    description      TEXT NOT NULL,
    recorded_at      TEXT NOT NULL
);

CREATE TRIGGER trial_counter_no_delete BEFORE DELETE ON trial_counter
BEGIN
    SELECT RAISE(ABORT, 'the trial counter only increases: removing a trial understates how many times we looked');
END;

CREATE TRIGGER trial_counter_no_update BEFORE UPDATE ON trial_counter
BEGIN
    SELECT RAISE(ABORT, 'trial records are immutable');
END;

-- =============================================================================
-- Experiment registry (Plan 2 §2.1)
-- =============================================================================

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
    -- Non-null where an exploratory pass preceded registration. Study 4
    -- (bulk buys) carries the 2026-08-16 audit result here. A registration
    -- that conceals a prior look is not a registration.
    exploratory_prior_run TEXT,

    spec_hash        TEXT NOT NULL UNIQUE,
    trials_before    INTEGER NOT NULL,
    configuration_json TEXT NOT NULL,
    code_commit_hash TEXT NOT NULL,
    status           TEXT NOT NULL CHECK (status IN
                        ('DRAFT','REGISTERED','RUNNING','REJECTED','VALIDATED',
                         'PAPER_TRIAL','PROMOTED','RETIRED','PAUSED')),
    decision_reason  TEXT
);

-- Status may advance; the specification may not. Amending a spec after seeing a
-- result is the same experiment wearing a new name.
CREATE TRIGGER experiment_spec_frozen BEFORE UPDATE ON experiment_registry
WHEN OLD.status != 'DRAFT' AND (
       NEW.spec_hash        != OLD.spec_hash
    OR NEW.hypothesis       != OLD.hypothesis
    OR NEW.pass_bar         != OLD.pass_bar
    OR NEW.kill_criteria    != OLD.kill_criteria
    OR NEW.test_count       != OLD.test_count
    OR NEW.holding_period   != OLD.holding_period
    OR NEW.cost_policy      != OLD.cost_policy
    OR NEW.benchmark_policy != OLD.benchmark_policy
)
BEGIN
    SELECT RAISE(ABORT, 'the specification is frozen once REGISTERED: register a new experiment instead of amending this one');
END;

CREATE TRIGGER experiment_no_delete BEFORE DELETE ON experiment_registry
BEGIN
    SELECT RAISE(ABORT, 'experiments are never deleted: a removed failure is a hidden failure');
END;

-- =============================================================================
-- Study results (Plan 1 §7.4)
-- =============================================================================
-- correction_method and n_tests_in_family are NOT NULL by design. The original
-- plan applied rigorous false-discovery control to seasonality and none at all
-- to participant selection; here a participant-level claim cannot physically be
-- stored without declaring how many participants were tested.

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

CREATE TRIGGER study_result_no_update BEFORE UPDATE ON study_result
BEGIN
    SELECT RAISE(ABORT, 'study results are write-once: recompute under a new experiment rather than editing a recorded finding');
END;

CREATE TRIGGER study_result_no_delete BEFORE DELETE ON study_result
BEGIN
    SELECT RAISE(ABORT, 'study results are never deleted');
END;

-- =============================================================================
-- Fee schedule (Plan 2 §4.1.1)
-- =============================================================================
-- Versioned, because rates move. Its predecessor treated STT, exchange charges
-- and GST as constants and got all three wrong: STT was charged sell-only when
-- equity delivery attracts it on both legs, the exchange rate was one number for
-- two exchanges, and GST was applied to brokerage alone rather than to
-- brokerage + SEBI + transaction. Together a 10 bps per-round-trip
-- under-charge, enough to flip the sign of its one surviving seasonality result.

CREATE TABLE fee_schedule (
    fee_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    component        TEXT NOT NULL CHECK (component IN
                        ('STT','TXN','SEBI','GST','STAMP','BROKERAGE')),
    segment          TEXT NOT NULL CHECK (segment IN ('EQ_DELIVERY','EQ_INTRADAY')),
    exchange         TEXT CHECK (exchange IN ('NSE','BSE') OR exchange IS NULL),
    side             TEXT NOT NULL CHECK (side IN ('BUY','SELL','BOTH')),
    rate             REAL NOT NULL,
    rate_basis       TEXT NOT NULL CHECK (rate_basis IN
                        ('PCT_TURNOVER','PER_CRORE','PCT_OF_BASE')),
    applies_to_base  TEXT,
    effective_from   TEXT NOT NULL,
    effective_to     TEXT,
    source_url       TEXT NOT NULL,
    source_note      TEXT NOT NULL,
    verified         INTEGER NOT NULL DEFAULT 0,
    verified_at      TEXT
);

CREATE INDEX idx_fee_lookup ON fee_schedule
    (component, segment, exchange, effective_from);

-- =============================================================================
-- Engine tables — created now, unpopulated in v1 (Plan 3 §1)
-- =============================================================================
-- Owner decision Q1: design the schemas so engines drop in later without a
-- migration that rewrites research history. A test asserts the signal ledger
-- stays empty while every engine is DISABLED.

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
    false_discovery_policy TEXT NOT NULL,
    enabled_status   TEXT NOT NULL DEFAULT 'DISABLED'
                        CHECK (enabled_status IN ('DISABLED','SHADOW','ENABLED')),
    version          TEXT NOT NULL
);

CREATE TABLE institutional_signal_ledger (
    signal_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    engine_id        TEXT NOT NULL REFERENCES engine_config (engine_id),
    as_of_date       TEXT NOT NULL,
    deal_id          INTEGER,
    security_id      INTEGER,
    participant_id   INTEGER,
    interpretation_mode TEXT NOT NULL,
    intended_horizon INTEGER,
    signal_type      TEXT NOT NULL,
    signal_status    TEXT NOT NULL CHECK (signal_status IN
                        ('APPROVED','REJECTED','BLOCKED','SKIPPED')),
    reason           TEXT NOT NULL,
    seasonality_cell_id INTEGER,
    engine_config_version TEXT NOT NULL,
    experiment_id    TEXT REFERENCES experiment_registry (experiment_id),
    input_hashes     TEXT NOT NULL,
    code_commit      TEXT NOT NULL,
    created_at       TEXT NOT NULL
);

-- A disabled engine emitting a signal means something is wired that should not
-- be. Fail at the database rather than discovering it in a result.
CREATE TRIGGER signal_requires_enabled_engine BEFORE INSERT ON institutional_signal_ledger
WHEN (SELECT enabled_status FROM engine_config WHERE engine_id = NEW.engine_id) = 'DISABLED'
BEGIN
    SELECT RAISE(ABORT, 'engine is DISABLED: no signals may be recorded for it');
END;

CREATE TRIGGER signal_no_update BEFORE UPDATE ON institutional_signal_ledger
BEGIN
    SELECT RAISE(ABORT, 'signals are write-once');
END;

CREATE TRIGGER signal_no_delete BEFORE DELETE ON institutional_signal_ledger
BEGIN
    SELECT RAISE(ABORT, 'signals are never deleted');
END;
