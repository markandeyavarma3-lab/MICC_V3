"""Track S's result tables (Plan 3 step 6S.7): the headline is write-once
governance, and an exploration run can never pass as a registered one."""

from __future__ import annotations

import sqlite3

import duckdb
import numpy as np
import pytest

from src.scan import procedure

pytestmark = pytest.mark.unit


@pytest.fixture
def dbs(tmp_path, monkeypatch):
    import src.common.paths as paths
    monkeypatch.setattr(paths, "research_db", lambda env=None: tmp_path / "w.duckdb")
    monkeypatch.setattr(paths, "governance_db", lambda env=None: tmp_path / "g.sqlite")
    return tmp_path


def _res():
    r = procedure.ProcedureResult(10, 3, 2.5, 0.667, 0.03, 0.01, 0.02, 0.05, [0.01, -0.01, 0.03])
    r.null_hit_rates = np.array([0.33, 0.5, 0.67])
    return [r]


def test_an_explore_run_is_recorded_and_cannot_be_edited(dbs):
    rid = procedure.record(_res(), 0.4, {"first": "2005-01-03", "horizon": 21}, "EXPLORE", 25, "abc",
                           keys=["+a", "+a|-b"], fold_names=["s1", "s2", "s3"])
    g = sqlite3.connect(dbs / "g.sqlite")
    assert g.execute("SELECT run_id, regime, hit_rate FROM procedure_result").fetchone() == (rid, "EXPLORE", 0.667)
    with pytest.raises(sqlite3.IntegrityError):
        g.execute("UPDATE procedure_result SET hit_rate = 1.0")
    with pytest.raises(sqlite3.IntegrityError):
        g.execute("DELETE FROM procedure_result")
    w = duckdb.connect(str(dbs / "w.duckdb"))
    assert w.execute("SELECT COUNT(*), MAX(depth) FROM scan_cell").fetchone() == (2, 2)
    assert w.execute("SELECT COUNT(*) FROM scan_fold_result").fetchone()[0] == 3


def test_an_explore_run_cannot_claim_an_experiment_and_a_confirm_run_must(dbs):
    with pytest.raises(ValueError, match="names none"):
        procedure.record(_res(), 0.4, {"x": 1}, "EXPLORE", 25, "abc", experiment_id="exp_005")
    with pytest.raises(ValueError, match="names its registered"):
        procedure.record(_res(), 0.4, {"x": 1}, "CONFIRM", 25, "abc")
