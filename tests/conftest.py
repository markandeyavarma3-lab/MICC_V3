"""Shared fixtures.

WHY THE ISOLATED LEDGER EXISTS. The persistence tests originally wrote to the
real dev governance database. Because `family_charge` is append-only and
monotonic BY DESIGN, that pollution could not be cleaned: after a few runs
TRACK_S_SIGNALS carried 5,151 trials that were pure test artefact, and the number
grew with every invocation.

A trial counter that accumulates test noise is not a trial counter. Any test
touching the ledger takes a throwaway database.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def isolated_ledger(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the governance DB at a throwaway file for the duration of one test."""
    from src.common import paths

    db = tmp_path / "governance_test.sqlite"
    monkeypatch.setattr(paths, "governance_db", lambda e=None: db)
    return db
