"""The 110 F&O sessions of 2026 that only the salvaged bhavcopies hold (0097)."""

from __future__ import annotations

import pandas as pd
import pytest

from src.ingest import fno

pytestmark = pytest.mark.unit


def _src(tmp_path, *days):
    for d in days:
        (tmp_path / f"fo_{d}.zip").write_bytes(d.encode())
    return tmp_path


@pytest.fixture
def parsed(monkeypatch, tmp_path):
    """Each fake file's bytes are its date, so a test can make one lie about it."""
    monkeypatch.setattr(fno, "OUT_DIR", tmp_path / "out")
    monkeypatch.setattr(fno.fo, "parse_udiff_bytes", lambda b: b.decode())
    monkeypatch.setattr(fno.fo, "to_legacy_spine", lambda d: pd.DataFrame(
        {"date": [f"{d[:4]}-{d[4:6]}-{d[6:]}"], "x": [1]}))


def test_only_sessions_inside_the_hole_are_landed(parsed, tmp_path):
    src = _src(tmp_path, "20251231", "20260101", "20260616", "20260617")
    got = fno.land_salvaged(src=src)
    assert [str(r.session) for r in got] == ["2026-01-01", "2026-06-16"], "the spine already holds what surrounds it"
    assert (fno.OUT_DIR / "date=2026-01-01.parquet").exists()


def test_a_dry_run_writes_nothing(parsed, tmp_path):
    got = fno.land_salvaged(dry_run=True, src=_src(tmp_path, "20260105"))
    assert len(got) == 1 and not fno.OUT_DIR.exists()


def test_a_file_whose_own_date_disagrees_with_its_name_is_refused(parsed, tmp_path):
    (tmp_path / "fo_20260105.zip").write_bytes(b"20260106")
    with pytest.raises(fno.fo.FoParseError):
        fno.land_salvaged(src=tmp_path)


def test_landing_without_the_full_build_is_refused():
    """Sessions older than the spine's last date make append_sessions raise, so
    on their own they would stop the collector's F&O stage that night."""
    with pytest.raises(SystemExit):
        fno.main(["--salvaged"])
