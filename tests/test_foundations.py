"""Phase 1 foundations: paths, hashing, migrations, and the write-once guarantees.

Each test here corresponds to a defect found in the predecessor system during the
2026-08-16 audit. The comment on each says which one, so a future reader can tell
whether a test is protecting something real or is ceremony.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
from pathlib import Path

import pytest

from src.common import hashing, migrate
from src.common.paths import ROOT, EnvironmentNotSet, env, relative_to_root

MIGRATIONS = ROOT / "migrations"


# --- environment: audit defect #2 (verify_v3 defaulted to dev and failed there) --


def test_unset_environment_raises_rather_than_defaulting(monkeypatch):
    monkeypatch.delenv("RESEARCH_ENV", raising=False)
    with pytest.raises(EnvironmentNotSet, match="not set"):
        env()


def test_invalid_environment_raises(monkeypatch):
    monkeypatch.setenv("RESEARCH_ENV", "staging")
    with pytest.raises(EnvironmentNotSet, match="not one of"):
        env()


@pytest.mark.parametrize("value", ["dev", "prod"])
def test_valid_environments_accepted(monkeypatch, value):
    monkeypatch.setenv("RESEARCH_ENV", value)
    assert env() == value


# --- paths: audit defect #8 (166 views hard-coded /Users/satya_03/...) ----------


def test_relative_to_root_rejects_paths_outside_the_repo():
    with pytest.raises(ValueError, match="outside the repo root"):
        relative_to_root("/etc/passwd")


def test_relative_to_root_returns_posix_relative():
    assert relative_to_root(ROOT / "data" / "x.parquet") == "data/x.parquet"


# --- hashing / provenance ------------------------------------------------------


def test_param_hash_is_order_independent():
    assert hashing.hash_params({"a": 1, "b": 2}) == hashing.hash_params({"b": 2, "a": 1})


def test_input_hash_is_order_independent():
    assert hashing.hash_inputs(["aa", "bb"]) == hashing.hash_inputs(["bb", "aa"])


def test_merkle_root_is_stable_and_order_independent():
    a = hashing.merkle_root(["a", "b", "c"])
    assert a == hashing.merkle_root(["c", "a", "b"])
    assert a != hashing.merkle_root(["a", "b", "d"])


def test_merkle_root_of_nothing_is_the_empty_digest():
    assert hashing.merkle_root([]) == hashing.EMPTY_SHA256


def test_spec_hash_demands_a_pass_bar_and_a_kill_criterion():
    """An experiment without both is not pre-registered — it is a plan to look."""
    with pytest.raises(ValueError, match="pass_bar|kill_criteria|missing"):
        hashing.spec_hash({"hypothesis": "institutions are informed"})


def test_spec_hash_changes_when_the_bar_moves():
    base = {
        "hypothesis": "h",
        "universe_definition": "u",
        "holding_period": "12m",
        "entry_policy": "next_open",
        "exit_policy": "horizon",
        "cost_policy": "v1",
        "benchmark_policy": "char_matched",
        "pass_bar": "t>3",
        "kill_criteria": "t<2",
    }
    moved = base | {"pass_bar": "t>2"}
    assert hashing.spec_hash(base) != hashing.spec_hash(moved)


# --- migrations: audit defect (dev store had 1 table, prod 15) ------------------


def test_migration_filenames_are_contiguous_from_one():
    migs = migrate.discover("sqlite", MIGRATIONS)
    assert [m.version for m in migs] == list(range(1, len(migs) + 1))


def test_migrations_apply_and_are_idempotent(tmp_path):
    db = tmp_path / "governance.sqlite"
    first = migrate.migrate_sqlite(db, MIGRATIONS)
    assert first, "expected at least one migration to apply"
    assert migrate.migrate_sqlite(db, MIGRATIONS) == []


def test_editing_an_applied_migration_is_refused(tmp_path):
    """Immutability of applied migrations — how the predecessor's stores diverged."""
    dir_ = tmp_path / "migrations"
    dir_.mkdir()
    f = dir_ / "0001_x.sqlite.sql"
    f.write_text("CREATE TABLE a (x INTEGER);")
    db = tmp_path / "g.sqlite"
    migrate.migrate_sqlite(db, dir_)

    f.write_text("CREATE TABLE a (x INTEGER, y INTEGER);")
    with pytest.raises(migrate.MigrationError, match="changed after it was applied"):
        migrate.migrate_sqlite(db, dir_)


# --- write-once guarantees -----------------------------------------------------


@pytest.fixture
def gov(tmp_path):
    db = tmp_path / "governance.sqlite"
    migrate.migrate_sqlite(db, MIGRATIONS)
    con = sqlite3.connect(db)
    con.execute("PRAGMA foreign_keys = ON")
    yield con
    con.close()


def _insert_artefact(con, h="a" * 64):
    con.execute(
        "INSERT INTO artefact (artefact_hash, artefact_type, logical_name, "
        "produced_by, code_commit, produced_at) VALUES (?,'TABLE','t','m:f','c','2026-08-16')",
        (h,),
    )
    con.commit()
    return h


def test_artefacts_cannot_be_updated_or_deleted(gov):
    h = _insert_artefact(gov)
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        gov.execute("UPDATE artefact SET logical_name='x' WHERE artefact_hash=?", (h,))
    gov.rollback()
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        gov.execute("DELETE FROM artefact WHERE artefact_hash=?", (h,))


def test_trial_counter_cannot_go_backwards(gov):
    """MICCV2 deflated challengers but exempted its incumbent. The counter is
    only honest if it cannot be trimmed."""
    gov.execute(
        "INSERT INTO trial_counter (source, description, recorded_at) "
        "VALUES ('test','t','2026-08-16')"
    )
    gov.commit()
    with pytest.raises(sqlite3.IntegrityError, match="only increases"):
        gov.execute("DELETE FROM trial_counter")


def _register(con, eid="exp_001", status="REGISTERED", spec="s" * 64):
    con.execute(
        """INSERT INTO experiment_registry (
            experiment_id, hypothesis, prior_belief, created_at, created_by,
            data_version, universe_definition, holding_period, entry_policy,
            exit_policy, cost_policy, benchmark_policy, training_period,
            validation_period, final_test_period, search_space_definition,
            test_count, multiple_testing_policy, permutation_policy,
            pass_bar, kill_criteria, spec_hash, trials_before,
            configuration_json, code_commit_hash, status)
        VALUES (?, 'h','p','2026-08-16','owner','v1','u','12m','next_open',
                'horizon','v1','char_matched','2005-2018','2018-2022','2022-2026',
                'ss', 4, 'romano_wolf', 'perm_1000', 't>3','t<2', ?, 68, '{}','c', ?)""",
        (eid, spec, status),
    )
    con.commit()


def test_a_registered_experiment_specification_is_frozen(gov):
    _register(gov)
    with pytest.raises(sqlite3.IntegrityError, match="frozen once REGISTERED"):
        gov.execute("UPDATE experiment_registry SET pass_bar='t>1' WHERE experiment_id='exp_001'")
    gov.rollback()
    # Status may still advance — that is the whole point of a lifecycle.
    gov.execute("UPDATE experiment_registry SET status='RUNNING' WHERE experiment_id='exp_001'")
    gov.commit()


def test_a_draft_experiment_may_still_be_edited(gov):
    _register(gov, eid="exp_draft", status="DRAFT", spec="d" * 64)
    gov.execute("UPDATE experiment_registry SET pass_bar='t>4' WHERE experiment_id='exp_draft'")
    gov.commit()


def test_experiments_are_never_deleted(gov):
    _register(gov)
    with pytest.raises(sqlite3.IntegrityError, match="never deleted"):
        gov.execute("DELETE FROM experiment_registry")


def test_test_count_must_be_positive(gov):
    """A study that declares zero tests has not declared its family size."""
    with pytest.raises(sqlite3.IntegrityError):
        gov.execute(
            """INSERT INTO experiment_registry (
                experiment_id, hypothesis, prior_belief, created_at, created_by,
                data_version, universe_definition, holding_period, entry_policy,
                exit_policy, cost_policy, benchmark_policy, training_period,
                validation_period, final_test_period, search_space_definition,
                test_count, multiple_testing_policy, permutation_policy,
                pass_bar, kill_criteria, spec_hash, trials_before,
                configuration_json, code_commit_hash, status)
            VALUES ('bad','h','p','2026-08-16','o','v1','u','12m','n','h','v1','c',
                    'a','b','c','ss', 0, 'bh','p','t>3','t<2','z','68','{}','c','DRAFT')"""
        )


def test_study_result_demands_a_correction_method(gov):
    """The original plan's blind spot, closed in the schema: a participant-level
    claim cannot be stored without declaring how many participants were tested."""
    _register(gov)
    with pytest.raises(sqlite3.IntegrityError):
        gov.execute(
            "INSERT INTO study_result (experiment_id, stratum, stratum_type, "
            "n_events, n_independent, n_tests_in_family, verdict, input_hashes, "
            "code_commit, computed_at) "
            "VALUES ('exp_001','ALL','all',100,50,4,'PASS','h','c','2026-08-16')"
        )


def test_study_results_are_write_once(gov):
    _register(gov)
    gov.execute(
        "INSERT INTO study_result (experiment_id, stratum, stratum_type, n_events, "
        "n_independent, correction_method, n_tests_in_family, verdict, input_hashes, "
        "code_commit, computed_at) "
        "VALUES ('exp_001','ALL','all',100,50,'romano_wolf',4,'FAIL','h','c','2026-08-16')"
    )
    gov.commit()
    with pytest.raises(sqlite3.IntegrityError, match="write-once"):
        gov.execute("UPDATE study_result SET verdict='PASS'")


# --- engines stay off in v1 (owner decision Q1 / Plan 3 §1.2) -------------------


def test_a_disabled_engine_cannot_emit_a_signal(gov):
    gov.execute(
        """INSERT INTO engine_config (engine_id, engine_name, purpose, data_inputs,
            participant_level, allowed_sides, interpretation_mode, holding_periods,
            entry_policy, exit_policy, liquidity_policy, risk_policy,
            benchmark_policy, minimum_history_policy, false_discovery_policy, version)
           VALUES ('consensus','Consensus','p','d','exact','BUY','INDIVIDUAL','12m',
                   'n','h','l','r','b','m','romano_wolf','0.1.0')"""
    )
    gov.commit()
    assert gov.execute(
        "SELECT enabled_status FROM engine_config WHERE engine_id='consensus'"
    ).fetchone()[0] == "DISABLED"

    with pytest.raises(sqlite3.IntegrityError, match="DISABLED"):
        gov.execute(
            "INSERT INTO institutional_signal_ledger (engine_id, as_of_date, "
            "interpretation_mode, signal_type, signal_status, reason, "
            "engine_config_version, input_hashes, code_commit, created_at) "
            "VALUES ('consensus','2026-08-16','INDIVIDUAL','BUY','APPROVED','r',"
            "'0.1.0','h','c','2026-08-16')"
        )


# --- repo hygiene: audit defect #9 (db/app_state.sqlite was tracked) -----------


def test_no_database_or_data_file_is_tracked_by_git():
    """Greps git rather than trusting .gitignore, which does not untrack."""
    out = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    bad = [
        f
        for f in out
        if f.startswith(("data/", "db/"))
        or f.endswith((".duckdb", ".sqlite", ".parquet"))
    ]
    assert not bad, f"data/database files tracked in git: {bad}"


def test_no_source_file_contains_a_hard_coded_home_path():
    """Audit defect #8: absolute paths inside stored SQL broke on every move."""
    offenders = []
    for py in (ROOT / "src").rglob("*.py"):
        text = py.read_text()
        if "/Users/" in text and "paths.py" not in py.name:
            offenders.append(str(py.relative_to(ROOT)))
    assert not offenders, f"hard-coded home paths in: {offenders}"


def test_no_order_placement_code_exists_anywhere():
    """Standing rule. Not in tests, not commented out, not in a dormant adapter."""
    forbidden = ("place_order", "modify_order", "cancel_order", "kite.orders")
    offenders = []
    for py in list((ROOT / "src").rglob("*.py")) + list((ROOT / "tests").rglob("*.py")):
        if py.name == Path(__file__).name:
            continue
        text = py.read_text()
        for token in forbidden:
            if token in text:
                offenders.append(f"{py.relative_to(ROOT)}: {token}")
    assert not offenders, f"order-placement code present: {offenders}"
