"""Governance write preconditions. Two silent failures, both measured 2026-09-12.

Neither needed a warehouse to find and neither needs one to test.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src.governance import ledger

MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"
GOV_0001 = MIGRATIONS / "0001_governance.sqlite.sql"
GOV_0003 = MIGRATIONS / "0003_registration_replace_is_not_an_amendment.sqlite.sql"


def _schema(con, with_0003=True):
    con.executescript(GOV_0001.read_text())
    if with_0003:
        con.executescript(GOV_0003.read_text())


def _cols(con):
    return [r[1] for r in con.execute("PRAGMA table_info(experiment_registry)")]


def _row(cols, **over):
    r = {c: ("REGISTERED" if c == "status" else "x") for c in cols}
    r.update({"experiment_id": "exp_002", "spec_hash": "FROZEN", "test_count": 24})
    r.update(over)
    return r


def _insert(con, row, cols, replace=True):
    verb = "INSERT OR REPLACE" if replace else "INSERT"
    con.execute(
        f"{verb} INTO experiment_registry ({','.join(cols)}) "
        f"VALUES ({','.join('?' * len(cols))})", [row[c] for c in cols])


class TestInsertOrReplaceBypassedTheFreeze:
    """THE HOLE. 0001 froze a registered spec with a BEFORE UPDATE trigger and a
    BEFORE DELETE trigger. SQLite's REPLACE is delete-then-insert: not an UPDATE,
    and it fires DELETE triggers only under recursive_triggers, which is off."""

    def test_the_original_schema_blocks_update_and_delete(self):
        con = sqlite3.connect(":memory:")
        _schema(con, with_0003=False)
        cols = _cols(con)
        _insert(con, _row(cols), cols)
        with pytest.raises(sqlite3.IntegrityError, match="frozen"):
            con.execute("UPDATE experiment_registry SET spec_hash='T'")
        with pytest.raises(sqlite3.IntegrityError, match="never deleted"):
            con.execute("DELETE FROM experiment_registry")

    def test_but_replace_walked_straight_through_both(self):
        """WATCHED FAILING. Without 0003 this rewrites a frozen registration."""
        con = sqlite3.connect(":memory:")
        _schema(con, with_0003=False)
        cols = _cols(con)
        _insert(con, _row(cols), cols)
        _insert(con, _row(cols, spec_hash="TAMPERED", test_count=999), cols)
        assert con.execute(
            "SELECT spec_hash, test_count FROM experiment_registry"
        ).fetchone() == ("TAMPERED", 999), "the bypass this migration exists to close"
        assert con.execute("PRAGMA recursive_triggers").fetchone()[0] == 0

    def test_migration_0003_closes_it(self):
        con = sqlite3.connect(":memory:")
        _schema(con)
        cols = _cols(con)
        _insert(con, _row(cols), cols)
        with pytest.raises(sqlite3.IntegrityError, match="not an amendment route"):
            _insert(con, _row(cols, spec_hash="TAMPERED", test_count=999), cols)
        assert con.execute(
            "SELECT spec_hash, test_count FROM experiment_registry"
        ).fetchone() == ("FROZEN", 24)

    def test_an_identical_re_registration_stays_idempotent(self):
        """Closing the hole must not break re-running a script that changes
        nothing — that is a legitimate and frequent operation."""
        con = sqlite3.connect(":memory:")
        _schema(con)
        cols = _cols(con)
        _insert(con, _row(cols), cols)
        _insert(con, _row(cols), cols)
        assert con.execute("SELECT COUNT(*) FROM experiment_registry").fetchone()[0] == 1

    def test_a_draft_may_still_be_amended(self):
        con = sqlite3.connect(":memory:")
        _schema(con)
        cols = _cols(con)
        _insert(con, _row(cols, status="DRAFT"), cols)
        _insert(con, _row(cols, status="DRAFT", spec_hash="REVISED"), cols)
        assert con.execute(
            "SELECT spec_hash FROM experiment_registry").fetchone()[0] == "REVISED"


class TestRequirePopulatedLedger:
    def test_a_missing_file_is_refused_and_not_created(self, tmp_path, monkeypatch):
        db = tmp_path / "governance_prod.sqlite"
        monkeypatch.setattr(ledger, "governance_db", lambda _e: db)
        with pytest.raises(ledger.LedgerRefused, match="does not exist"):
            ledger.require_populated_ledger()
        assert not db.exists(), "the guard must never create the ledger it checks"

    def test_a_schemaless_file_is_refused(self, tmp_path, monkeypatch):
        db = tmp_path / "g.sqlite"
        sqlite3.connect(str(db)).close()
        monkeypatch.setattr(ledger, "governance_db", lambda _e: db)
        with pytest.raises(ledger.LedgerRefused, match="no governance schema"):
            ledger.require_populated_ledger()

    def test_a_correctly_migrated_but_empty_ledger_is_refused(self, tmp_path, monkeypatch):
        """THE ACTUAL FAILURE: provenance migrates a fresh database on any
        machine lacking one, and the write then succeeds into nothing."""
        db = tmp_path / "g.sqlite"
        con = sqlite3.connect(str(db))
        _schema(con)
        con.commit()
        con.close()
        monkeypatch.setattr(ledger, "governance_db", lambda _e: db)
        with pytest.raises(ledger.LedgerRefused, match="empty ledger"):
            ledger.require_populated_ledger()

    def test_a_ledger_with_history_passes(self, tmp_path, monkeypatch):
        db = _populated(tmp_path)
        monkeypatch.setattr(ledger, "governance_db", lambda _e: db)
        assert ledger.require_populated_ledger() == db


def _populated(tmp_path: Path) -> Path:
    db = tmp_path / "g.sqlite"
    con = sqlite3.connect(str(db))
    _schema(con)
    con.execute(
        "INSERT INTO artefact (artefact_hash, artefact_type, logical_name, "
        "produced_by, code_commit, produced_at) VALUES "
        "('a'*64,'RESULT','prop_hft_classifier_coverage','t','c','2026-01-01')")
    con.execute("INSERT INTO merkle_log (as_of_date, merkle_root, artefact_count, "
                "computed_at) VALUES ('2026-01-01','r',1,'2026-01-01')")
    con.commit()
    con.close()
    return db


class TestRequireNotAlreadyRegistered:
    def test_an_unregistered_experiment_is_allowed(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ledger, "governance_db", lambda _e: _populated(tmp_path))
        assert ledger.require_not_already_registered("exp_999", "abc") is None

    def test_an_identical_re_registration_is_refused(self, tmp_path, monkeypatch):
        """Not an error in the data — a refusal to restate a frozen registration
        as a fresh one, which is what rewriting created_at would do."""
        db = _populated(tmp_path)
        con = sqlite3.connect(str(db))
        cols = _cols(con)
        _insert(con, _row(cols, created_at="2026-09-11"), cols)
        con.commit()
        con.close()
        monkeypatch.setattr(ledger, "governance_db", lambda _e: db)
        with pytest.raises(ledger.LedgerRefused, match="already registered"):
            ledger.require_not_already_registered("exp_002", "FROZEN")

    def test_a_different_spec_hash_is_refused_as_an_amendment(self, tmp_path, monkeypatch):
        db = _populated(tmp_path)
        con = sqlite3.connect(str(db))
        cols = _cols(con)
        _insert(con, _row(cols), cols)
        con.commit()
        con.close()
        monkeypatch.setattr(ledger, "governance_db", lambda _e: db)
        with pytest.raises(ledger.LedgerRefused, match="DIFFERENT spec_hash"):
            ledger.require_not_already_registered("exp_002", "OTHER")
