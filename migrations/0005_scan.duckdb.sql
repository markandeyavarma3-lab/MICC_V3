-- 0005_scan.duckdb.sql — Track S's grid and its fold-level results.
-- Plan 3 step 6S.7, Plan 4 §11.
--
-- WHAT LIVES HERE AND WHAT DOES NOT. The per-candidate block IC (sums and
-- counts per 21-session block) stays in the atlas shards on disk: ~2 KB a
-- candidate, and nothing queries it but the procedure test. These tables hold
-- what a reader asks for afterwards: which grid ran on what (scan_run, the
-- atlas manifest verbatim), what each candidate was (scan_cell), and the
-- train/test IC of the selected set in every fold (scan_fold_result).
-- The headline itself, the procedure result, is a governance record:
-- migrations/0004_procedure_result.sqlite.sql.

CREATE TABLE scan_run (
    run_id         TEXT PRIMARY KEY,          -- sha256 of the manifest, first 16
    manifest_json  TEXT NOT NULL,
    regime         TEXT NOT NULL CHECK (regime IN ('EXPLORE','CONFIRM')),
    created_at     TIMESTAMP NOT NULL
);

CREATE TABLE scan_cell (
    run_id         TEXT NOT NULL REFERENCES scan_run (run_id),
    cell_idx       BIGINT NOT NULL,           -- position in the canonical enumeration
    cell_key       TEXT NOT NULL,             -- e.g. +mom_63_skip0|-vol_21
    depth          INTEGER NOT NULL,
    PRIMARY KEY (run_id, cell_idx)
);

CREATE TABLE scan_fold_result (
    run_id         TEXT NOT NULL REFERENCES scan_run (run_id),
    design         TEXT NOT NULL,             -- sequential | cpcv
    top_n          INTEGER NOT NULL,
    fold_name      TEXT NOT NULL,
    train_ic       DOUBLE,                    -- mean |train IC| of the selected set
    test_ic        DOUBLE,                    -- mean test IC, read in the training sign
    PRIMARY KEY (run_id, design, top_n, fold_name)
);
