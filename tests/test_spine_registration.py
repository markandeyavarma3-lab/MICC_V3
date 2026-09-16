"""The spine registers itself on the path the collector actually calls.

THE DEFECT THIS PINS (decision 0064). `collect_daily.sh` rebuilds the price
spines nightly with `spine.build(PRICE)` and `spine.build_adjusted()`. Until
2026-09-16 only `spine.build_all()` — the by-hand Phase 1 rebuild — registered
the result in the provenance DAG. On 2026-09-15, the first night the spine
grew after `charmatch` joined the script, `charmatch.build_panel` pointed a
parent edge at the new spine checksum, nobody had registered it, and
`artefact_edge`'s foreign key refused: `charpanel=1` with a full traceback,
while the panel itself had been written. Two nights running.

These tests use a throwaway ledger and a three-row synthetic spine. They do
not read prod, do not rebuild anything, and do not need the seed.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from src.governance import provenance as prov
from src.warehouse import spine

pytestmark = pytest.mark.unit


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    db = tmp_path / "governance_test.sqlite"
    monkeypatch.setattr(prov, "governance_db", lambda e=None: db)
    return db


@pytest.fixture
def tiny_spine(tmp_path) -> tuple[Path, duckdb.DuckDBPyConnection]:
    """A partitioned parquet dataset in the price spine's exact column shape."""
    out = tmp_path / "price_spine"
    con = duckdb.connect()
    con.execute("""
        CREATE TABLE t AS SELECT * FROM (VALUES
            ('AAA', '2026-09-15', 10.0, 11.0, 9.0, 10.5, 100.0, 2026),
            ('AAA', '2026-09-16', 10.5, 12.0, 10.0, 11.5, 120.0, 2026),
            ('BBB', '2026-09-16', 50.0, 51.0, 49.0, 50.0, 10.0, 2026)
        ) v(symbol, date, open, high, low, close, volume, _y)
    """)
    con.execute(f"COPY t TO '{out}' (FORMAT PARQUET, PARTITION_BY (_y), OVERWRITE_OR_IGNORE 1)")
    return out, con


def _parent(tmp_path, ledger, name: str) -> Path:
    """A registered source directory the spine can edge to."""
    d = tmp_path / name
    d.mkdir()
    (d / "part.parquet").write_bytes(b"PAR1" + name.encode() + b"PAR1")
    digest, size = prov.hash_dataset(d, pattern="**/*")
    prov.register(prov.Artefact(digest, "SOURCE", f"seed:{name}", "test", byte_size=size))
    return d


def test_register_spine_writes_the_checksum_a_child_can_parent_to(ledger, tiny_spine, tmp_path, monkeypatch):
    out, con = tiny_spine
    src = _parent(tmp_path, ledger, "v1_export")
    monkeypatch.setattr(spine, "_parent_dirs", lambda spec: (src,))

    r = spine.BuildResult(spine.PRICE.name, 3, 3, 0, 0, out)
    digest = spine.register_spine(spine.PRICE, r, con=con)

    assert r.artefact_hash == digest
    assert digest == prov.data_checksum(con, f"{out}/**/*.parquet", (*spine.PRICE.columns, "_y")), (
        "the registered hash must be the DATA checksum charmatch computes, not a file hash"
    )
    import sqlite3
    g = sqlite3.connect(ledger)
    row = g.execute("SELECT logical_name, row_count FROM artefact WHERE artefact_hash=?", (digest,)).fetchone()
    assert row == ("warehouse:price_spine", 3)
    edges = g.execute("SELECT parent_hash FROM artefact_edge WHERE child_hash=?", (digest,)).fetchall()
    assert len(edges) == 1, "one edge, to the one source it read"

    # THE POINT: charmatch's registration, verbatim in shape, now succeeds.
    ok = prov.register(
        prov.Artefact("c" * 64, "FEATURE", "warehouse:char_panel", "test"),
        parents=[(digest, "input")],
    )
    assert ok is True


def test_an_unregistered_parent_fails_loudly_not_silently(ledger, tiny_spine, tmp_path, monkeypatch):
    """The FK is the guarantee. A spine that quietly dropped an unknown parent
    would be the same unparented lineage one level up."""
    out, con = tiny_spine
    d = tmp_path / "never_registered"
    d.mkdir()
    (d / "x.parquet").write_bytes(b"PAR1xxPAR1")
    monkeypatch.setattr(spine, "_parent_dirs", lambda spec: (d,))
    r = spine.BuildResult(spine.PRICE.name, 3, 3, 0, 0, out)
    with pytest.raises(prov.ProvenanceError, match="FOREIGN KEY"):
        spine.register_spine(spine.PRICE, r, con=con)


def test_registration_is_idempotent_on_unchanged_data(ledger, tiny_spine, tmp_path, monkeypatch):
    """A nightly rebuild of unchanged data must not grow the graph — and must
    still leave a registered checksum for charmatch to find."""
    out, con = tiny_spine
    src = _parent(tmp_path, ledger, "v1_export")
    monkeypatch.setattr(spine, "_parent_dirs", lambda spec: (src,))
    r = spine.BuildResult(spine.PRICE.name, 3, 3, 0, 0, out)
    a = spine.register_spine(spine.PRICE, r, con=con)
    b = spine.register_spine(spine.PRICE, r, con=con)
    assert a == b
    import sqlite3
    n = sqlite3.connect(ledger).execute("SELECT COUNT(*) FROM artefact WHERE logical_name='warehouse:price_spine'").fetchone()[0]
    assert n == 1


def test_build_and_build_adjusted_register_by_default():
    """Pinned on the source: the two entry points collect_daily.sh calls both
    register, and only an explicit register=False opts out."""
    import inspect

    for fn in (spine.build, spine.build_adjusted):
        sig = inspect.signature(fn)
        assert sig.parameters["register"].default is True, fn.__name__
        src = inspect.getsource(fn)
        assert "register_spine(" in src, f"{fn.__name__} does not register what it built"


def test_collect_daily_calls_the_registering_entry_points():
    """The script is the path that matters. If it ever calls _build_impl or a
    new unregistered helper, charpanel goes unparented again."""
    sh = (Path(__file__).parents[1] / "scripts" / "collect_daily.sh").read_text()
    assert "spine.build(spine.PRICE" in sh
    assert "spine.build_adjusted(" in sh
    assert "_build_impl" not in sh and "register=False" not in sh


def test_build_all_no_longer_duplicates_registration():
    """One registration path. build_all used to carry its own copy of the
    register block; a second copy is how the two drifted in the first place."""
    import inspect

    src = inspect.getsource(spine.build_all)
    assert "prov.register(" not in src
    assert "register_spine" in inspect.getsource(spine.build)
