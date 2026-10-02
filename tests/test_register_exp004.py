"""The exp_004 registration, rehearsed (decision 0076).

The rehearsal on 2026-10-02 found the first version would hash 26 spec fields
and store 20: tail_rule, signal_definition, confounds, revised_policy,
interval_policy and trial_family had no registry column and were dropped
without a word. These pin the repair: every field stored, the hash recomputed
from the stored row before COMMIT, and a rehearsal that cannot write the real
registry.
"""

from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def reg(monkeypatch):
    spec = importlib.util.spec_from_file_location("register_exp004", ROOT / "scripts" / "register_exp004.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["register_exp004"] = mod
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod.families, "persisted_counter", lambda family, env=None: 0)
    # Unit tests must not depend on the real data files being present.
    monkeypatch.setattr(mod, "input_problems", lambda: [])
    return mod


@pytest.fixture
def gov(tmp_path):
    from src.common import migrate
    db = tmp_path / "governance_test.sqlite"
    migrate.migrate_sqlite(db)
    return db


def _spec(reg):
    return reg.build_spec((1500, 2200, 2000))


def test_every_spec_field_is_stored_and_the_stored_row_reproduces_the_hash(reg, gov):
    spec = _spec(reg)
    con = sqlite3.connect(gov)
    sh = reg.register(con, spec, 0.96, "abc123")
    cols = [r[1] for r in con.execute("PRAGMA table_info(experiment_registry)")]
    row = dict(zip(cols, con.execute("SELECT * FROM experiment_registry").fetchone(), strict=True))
    con.close()
    back = reg.stored_spec(row, list(spec))
    assert back == spec, {k for k in spec if back.get(k) != spec[k]}
    assert reg.spec_hash(back) == sh == row["spec_hash"]
    # The six that have no column are the ones that used to vanish.
    missing = {k for k in spec if k not in cols}
    assert {"tail_rule", "signal_definition", "revised_policy", "interval_policy"} <= missing


def test_a_row_that_does_not_reproduce_its_hash_is_rolled_back(reg, gov, monkeypatch):
    spec = _spec(reg)
    monkeypatch.setattr(reg, "stored_spec",
                        lambda row, keys: {k: row.get(k) for k in keys})   # the old behaviour
    con = sqlite3.connect(gov)
    with pytest.raises(RuntimeError, match="does not reproduce the hash"):
        reg.register(con, spec, 0.96, "abc123")
    assert con.execute("SELECT COUNT(*) FROM experiment_registry").fetchone()[0] == 0
    con.close()


def test_a_second_registration_is_refused(reg, gov):
    con = sqlite3.connect(gov)
    reg.register(con, _spec(reg), 0.96, "abc123")
    with pytest.raises(RuntimeError, match="already registered"):
        reg.register(con, _spec(reg), 0.96, "abc123")
    con.close()


def test_the_rehearsal_never_writes_the_real_registry(reg, gov, monkeypatch):
    before = gov.read_bytes()
    monkeypatch.setattr(reg, "governance_db", lambda env=None: gov)
    monkeypatch.setattr(reg, "sweep_coverage", lambda: (1500, 2200, 2000))
    monkeypatch.setattr(sys, "argv", ["register_exp004.py", "--rehearse"])
    assert reg.main() == 0
    assert gov.read_bytes() == before


def test_the_real_run_refuses_uncommitted_code(reg, gov, monkeypatch):
    monkeypatch.setattr(reg, "governance_db", lambda env=None: gov)
    monkeypatch.setattr(reg, "sweep_coverage", lambda: (1990, 2200, 2000))
    monkeypatch.setattr(reg, "code_is_committed", lambda: [" M src/research/holdings.py"])
    monkeypatch.setattr(sys, "argv", ["register_exp004.py"])
    assert reg.main() == 1
    con = sqlite3.connect(gov)
    assert con.execute("SELECT COUNT(*) FROM experiment_registry").fetchone()[0] == 0
    con.close()


def test_the_spec_says_what_the_code_does():
    """The universe no longer requires survival, the exit policy names the four
    cases, and kill 4 carries its number."""
    src = (ROOT / "scripts" / "register_exp004.py").read_text()
    assert "63 sessions after entry, (c)" not in src
    for case in ("HORIZON", "MOVED", "STOPPED", "CENSORED"):
        assert case in src, case
    assert "SHARE_CHANGE_FLAG" in src


def test_an_unreadable_input_refuses_the_registration(reg, gov, monkeypatch):
    monkeypatch.setattr(reg, "governance_db", lambda env=None: gov)
    monkeypatch.setattr(reg, "sweep_coverage", lambda: (1990, 2200, 2000))
    monkeypatch.setattr(reg, "code_is_committed", lambda: [])
    monkeypatch.setattr(reg, "input_problems", lambda: ["char_panel: IOException"])
    monkeypatch.setattr(sys, "argv", ["register_exp004.py"])
    assert reg.main() == 1
    con = sqlite3.connect(gov)
    assert con.execute("SELECT COUNT(*) FROM experiment_registry").fetchone()[0] == 0
    con.close()
