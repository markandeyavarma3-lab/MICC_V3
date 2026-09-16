-- 0003 — close the INSERT OR REPLACE hole in the frozen-specification guarantee.
--
-- MEASURED 2026-09-12. 0001 froze a registered specification with two triggers:
-- `experiment_spec_frozen` (BEFORE UPDATE) and `experiment_no_delete`
-- (BEFORE DELETE). Both work. Neither fires for `INSERT OR REPLACE`.
--
-- SQLite implements REPLACE as a delete followed by an insert, so it is not an
-- UPDATE and the update trigger never sees it; and REPLACE fires DELETE triggers
-- only when `PRAGMA recursive_triggers` is ON, which defaults to OFF and is not
-- set anywhere in this project. Verified against the real 0001 schema:
--
--     UPDATE  spec_hash -> 'TAMPERED'          BLOCKED
--     DELETE  the row                          BLOCKED
--     INSERT OR REPLACE, spec_hash 'TAMPERED',
--                        test_count 24 -> 999  ALLOWED   <-- both bypassed
--
-- scripts/register_exp002.py writes with `INSERT OR REPLACE`. Re-running it
-- therefore silently rewrote a frozen registration — spec_hash, test_count,
-- created_at and trials_before — with no error and exit 0. The whole epistemic
-- claim of this project is that the specification was fixed before any outcome
-- was computed, and that claim rested on a trigger that the project's own
-- registration script walked around.
--
-- This trigger closes it at the schema level rather than in the caller, because
-- the caller is not the only thing that can write to this table. An IDENTICAL
-- re-registration is still allowed: re-running a registration script that
-- changes nothing is idempotent and must stay that way.
CREATE TRIGGER experiment_replace_is_not_an_amendment
BEFORE INSERT ON experiment_registry
WHEN EXISTS (
    SELECT 1 FROM experiment_registry
     WHERE experiment_id = NEW.experiment_id
       AND status != 'DRAFT'
       AND (   spec_hash        != NEW.spec_hash
            OR hypothesis       != NEW.hypothesis
            OR pass_bar         != NEW.pass_bar
            OR kill_criteria    != NEW.kill_criteria
            OR test_count       != NEW.test_count
            OR holding_period   != NEW.holding_period
            OR cost_policy      != NEW.cost_policy
            OR benchmark_policy != NEW.benchmark_policy)
)
BEGIN
    SELECT RAISE(ABORT, 'the specification is frozen once REGISTERED: INSERT OR REPLACE is not an amendment route, register a new experiment instead');
END;
