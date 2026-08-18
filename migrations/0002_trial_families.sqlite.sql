-- 0002_trial_families — make the family counters actually accumulate.
--
-- WHY THIS MIGRATION EXISTS.
--
-- configs/trials.yml declares `counters_monotonic: true` and
-- `counters_never_reset: true`. On 2026-08-18, immediately after writing it, a
-- check found that NOTHING INCREMENTED THEM. `families.py` was a pure function,
-- `project_counter()` summed static YAML values, and a 31.9M-cell scan could
-- have run without moving any counter at all.
--
-- That is precisely the defect the whole scheme exists to cure — exp_001's
-- `trials_before` was computed, stored as 171, printed once, and never read by
-- anything. Rebuilt one level up, in the file whose subject is that failure.
--
-- A declaration with no storage behind it is a diary entry.

CREATE TABLE family_charge (
    charge_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    family_id        TEXT    NOT NULL,
    -- What was searched. Never a hard-coded literal: the realised width of the
    -- grid that actually ran.
    trials_added     INTEGER NOT NULL CHECK (trials_added >= 0),
    -- The running total AFTER this charge, stored rather than recomputed, so the
    -- history cannot be rewritten by editing a config.
    trials_after     INTEGER NOT NULL CHECK (trials_after >= 0),
    dof              INTEGER,
    required_t       REAL    NOT NULL CHECK (required_t > 0),
    -- Which registered study this search belongs to. NULL only for exploratory
    -- episodes, which are still charged.
    experiment_id    TEXT,
    description      TEXT    NOT NULL,
    code_commit_hash TEXT,
    recorded_at      TEXT    NOT NULL
);

CREATE INDEX idx_family_charge_family ON family_charge (family_id, charge_id);

-- Append-only. A counter that can be edited downward is not a counter.
CREATE TRIGGER family_charge_no_update
BEFORE UPDATE ON family_charge
BEGIN
    SELECT RAISE(ABORT, 'family_charge is append-only: trial counters are monotonic and never reset');
END;

CREATE TRIGGER family_charge_no_delete
BEFORE DELETE ON family_charge
BEGIN
    SELECT RAISE(ABORT, 'family_charge is append-only: a deleted charge is a search that stops being paid for');
END;

-- Monotonicity, enforced rather than promised: a new charge in a family may
-- never report a running total below the one before it.
CREATE TRIGGER family_charge_monotonic
BEFORE INSERT ON family_charge
WHEN NEW.trials_after < COALESCE(
        (SELECT MAX(trials_after) FROM family_charge WHERE family_id = NEW.family_id), 0)
BEGIN
    SELECT RAISE(ABORT, 'trials_after would decrease: family counters are monotonic');
END;
