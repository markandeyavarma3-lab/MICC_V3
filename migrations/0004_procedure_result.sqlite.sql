-- 0004_procedure_result.sqlite.sql — the procedure test's headline, write-once.
-- Plan 3 step 6S.7, Plan 4 §4.
--
-- A governance record for the same reason study_result is one: a recorded
-- result is never edited, it is superseded by a new run. `regime` keeps the
-- free EXPLORE runs (2005-2015, split.yml scan.temporal) apart from the one
-- registered CONFIRM run, and only a CONFIRM row may carry an experiment_id.

CREATE TABLE procedure_result (
    result_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id           TEXT NOT NULL,
    regime           TEXT NOT NULL CHECK (regime IN ('EXPLORE','CONFIRM')),
    experiment_id    TEXT,
    top_n            INTEGER NOT NULL,
    folds            INTEGER NOT NULL,
    effective_folds  REAL NOT NULL,
    hit_rate         REAL NOT NULL,
    null_mean        REAL,
    p_vs_null        REAL,
    mean_train_ic    REAL,
    mean_test_ic     REAL,
    degradation      REAL,
    rank_decay       REAL,
    pbo              REAL,
    candidates       INTEGER NOT NULL,
    code_commit      TEXT NOT NULL,
    created_at       TEXT NOT NULL,
    CHECK (regime = 'CONFIRM' OR experiment_id IS NULL)
);

CREATE TRIGGER procedure_result_no_update BEFORE UPDATE ON procedure_result
BEGIN
    SELECT RAISE(ABORT, 'procedure results are write-once: run again under a new run_id rather than editing a recorded result');
END;

CREATE TRIGGER procedure_result_no_delete BEFORE DELETE ON procedure_result
BEGIN
    SELECT RAISE(ABORT, 'procedure results are write-once: a recorded result is superseded, never deleted');
END;
