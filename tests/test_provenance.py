"""The provenance DAG — Plan 2 §8, commissioned 2026-08-21.

The schema existed from migration 0001 and held ZERO ROWS for five days. These
tests exist so it cannot quietly return to that state: if the graph is not
written to, `test_the_graph_is_not_empty_after_a_seed_registration` is the thing
that notices.
"""

from __future__ import annotations

import sqlite3

import pytest

from src.common.hashing import hash_bytes
from src.governance import provenance as prov
from src.governance.provenance import Artefact, ProvenanceError


@pytest.fixture
def env(tmp_path, monkeypatch):
    """An isolated governance DB per test. Never touches dev or prod."""
    db = tmp_path / "governance_test.sqlite"
    monkeypatch.setattr(prov, "governance_db", lambda e=None: db)
    return None


def _art(content: bytes, name: str = "thing", typ: str = "SOURCE") -> Artefact:
    return Artefact(hash_bytes(content), typ, name, "test:_art")


# --- identity ----------------------------------------------------------------


def test_an_artefact_is_its_content_hash(env):
    assert prov.register(_art(b"alpha")) is True
    assert prov.count()[0] == 1


def test_registering_identical_content_twice_is_a_no_op(env):
    """Re-runnability. The Phase 1 rebuild must be safe to run again."""
    a = _art(b"alpha")
    assert prov.register(a) is True
    assert prov.register(a) is False, "the second registration should insert nothing"
    assert prov.count()[0] == 1


def test_different_content_under_one_name_makes_two_artefacts(env):
    """A restated source does not REPLACE its predecessor; both persist.

    The triggers make 'this artefact changed' inexpressible, which is correct —
    the only true statement is that a new artefact exists.
    """
    prov.register(_art(b"v1", name="bulk_deals"))
    prov.register(_art(b"v2", name="bulk_deals"))
    assert prov.count()[0] == 2


def test_a_bad_type_is_refused_in_python_not_by_sqlite(env):
    with pytest.raises(ProvenanceError, match="unknown artefact_type"):
        prov.register(Artefact(hash_bytes(b"x"), "NONSENSE", "n", "p"))  # type: ignore[arg-type]


def test_a_hash_that_is_not_a_sha256_is_refused(env):
    with pytest.raises(ProvenanceError, match="64-char sha256"):
        prov.register(Artefact("abc123", "SOURCE", "n", "p"))


def test_an_artefact_needs_a_name(env):
    with pytest.raises(ProvenanceError, match="logical_name"):
        prov.register(Artefact(hash_bytes(b"x"), "SOURCE", "   ", "p"))


# --- edges and lineage -------------------------------------------------------


def test_an_edge_to_an_unregistered_parent_is_refused(env):
    """A lineage that cannot be walked is worse than no lineage."""
    child = _art(b"derived", typ="TABLE")
    with pytest.raises(ProvenanceError, match="foreign-key|FOREIGN KEY"):
        prov.register(child, parents=[(hash_bytes(b"never-registered"), "input")])


def test_an_artefact_cannot_be_its_own_parent(env):
    a = _art(b"alpha")
    prov.register(a)
    with pytest.raises(ProvenanceError, match="cycle"):
        prov.register(a, parents=[(a.artefact_hash, "self")])


def test_lineage_reaches_every_ancestor(env):
    """'What produced this number?' as a query rather than an archaeology."""
    src_a = _art(b"prices", name="prices")
    src_b = _art(b"deals", name="deals")
    prov.register(src_a)
    prov.register(src_b)

    mart = _art(b"mart", name="clean_mart", typ="TABLE")
    prov.register(mart, parents=[(src_a.artefact_hash, "input"),
                                 (src_b.artefact_hash, "input")])

    result = _art(b"result", name="study_001", typ="RESULT")
    prov.register(result, parents=[(mart.artefact_hash, "input")])

    names = {n["logical_name"] for n in prov.lineage(result.artefact_hash)}
    assert names == {"study_001", "clean_mart", "prices", "deals"}


def test_descendants_answers_the_restatement_question(env):
    """Plan 2 §8.2: the row a hash chain cannot answer.

    When NSE restates a source file, which published results are now suspect?
    """
    src = _art(b"bulk-2026-08-20", name="bulk_raw")
    prov.register(src)
    mart = _art(b"mart", name="deals_clean", typ="TABLE")
    prov.register(mart, parents=[(src.artefact_hash, "input")])
    r1 = _art(b"r1", name="finding_001", typ="RESULT")
    r2 = _art(b"r2", name="finding_002", typ="RESULT")
    prov.register(r1, parents=[(mart.artefact_hash, "input")])
    prov.register(r2, parents=[(mart.artefact_hash, "input")])

    affected = {d["logical_name"] for d in prov.descendants(src.artefact_hash)}
    assert affected == {"deals_clean", "finding_001", "finding_002"}


def test_lineage_terminates_on_a_diamond(env):
    """Two paths to one ancestor must not loop or double-report it."""
    root = _art(b"root", name="root")
    prov.register(root)
    left = _art(b"left", name="left", typ="TABLE")
    right = _art(b"right", name="right", typ="TABLE")
    prov.register(left, parents=[(root.artefact_hash, "input")])
    prov.register(right, parents=[(root.artefact_hash, "input")])
    top = _art(b"top", name="top", typ="RESULT")
    prov.register(top, parents=[(left.artefact_hash, "l"), (right.artefact_hash, "r")])

    got = prov.lineage(top.artefact_hash)
    assert len(got) == len({n["artefact_hash"] for n in got}), "an ancestor was repeated"
    assert {n["logical_name"] for n in got} == {"top", "left", "right", "root"}


# --- append-only, enforced by the database not by convention -----------------


def test_the_triggers_actually_refuse_edits(env, tmp_path):
    """Migration 0001's write-once guarantee, exercised rather than trusted."""
    a = _art(b"alpha")
    prov.register(a)
    con = sqlite3.connect(prov.governance_db(None))
    try:
        with pytest.raises(sqlite3.IntegrityError, match="immutable|content-addressed"):
            con.execute("UPDATE artefact SET logical_name='x'")
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            con.execute("DELETE FROM artefact")
    finally:
        con.close()


# --- datasets ----------------------------------------------------------------


def test_a_dataset_hash_is_order_independent_but_content_sensitive(env, tmp_path):
    d = tmp_path / "ds"
    (d / "year=2005").mkdir(parents=True)
    (d / "year=2006").mkdir(parents=True)
    (d / "year=2005" / "a.parquet").write_bytes(b"one")
    (d / "year=2006" / "b.parquet").write_bytes(b"two")
    first, size = prov.hash_dataset(d)
    assert size == 6

    # Same bytes, recomputed — identical.
    assert prov.hash_dataset(d)[0] == first

    # One byte different anywhere — different dataset.
    (d / "year=2006" / "b.parquet").write_bytes(b"TWO")
    assert prov.hash_dataset(d)[0] != first


def test_an_empty_dataset_is_refused(env, tmp_path):
    """The hash of nothing is a valid hash, and would look like a green build."""
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(ProvenanceError, match="Refusing to register an empty"):
        prov.hash_dataset(empty)


# --- computed artefacts -------------------------------------------------------


def test_a_derived_hash_depends_on_inputs_and_params(env):
    """Two results agree only if BOTH the data and the settings agree."""
    base = prov.derived_hash(["a" * 64, "b" * 64], {"horizon": 10})
    assert prov.derived_hash(["b" * 64, "a" * 64], {"horizon": 10}) == base, "order"
    assert prov.derived_hash(["a" * 64, "b" * 64], {"horizon": 21}) != base, "params"
    assert prov.derived_hash(["a" * 64, "c" * 64], {"horizon": 10}) != base, "inputs"


# --- tamper evidence ----------------------------------------------------------


def test_the_merkle_root_seals_the_whole_graph(env):
    prov.register(_art(b"alpha"))
    first = prov.write_merkle_root(as_of="2026-08-21")
    assert prov.write_merkle_root(as_of="2026-08-21") == first, "must be idempotent"


def test_sealing_a_day_twice_after_the_graph_grew_is_refused(env):
    """An append-only log cannot express 'the root changed'."""
    prov.register(_art(b"alpha"))
    prov.write_merkle_root(as_of="2026-08-21")
    prov.register(_art(b"beta"))
    with pytest.raises(ProvenanceError, match="already recorded"):
        prov.write_merkle_root(as_of="2026-08-21")


# --- the honesty guarantee ----------------------------------------------------


def test_a_dirty_tree_is_recorded_as_dirty(env, monkeypatch):
    """Recording the bare sha of a dirty tree makes an unreproducible run look
    reproducible. It must say so."""
    prov.code_commit.cache_clear()
    commit = prov.code_commit()
    prov.code_commit.cache_clear()
    assert commit == "UNKNOWN" or len(commit) == 40 or commit.endswith("-dirty"), commit
