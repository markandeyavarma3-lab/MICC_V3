"""UDiFF F&O bhavcopy and participant-wise OI parsers, pinned to the map in
handover_delta4/06_FNO_MAP.md and to real bytes.

WHY THESE EXIST. Decision 0058 resumed collection of both feeds and forbade
parsing them in that workstream: the legacy fno_spine names none of the 34
UDiFF columns the same way, and an invented map would have been the parsing
0058 was told not to do. Decision 0062 lifts that boundary for CODE AND
FIXTURES only. Nothing here touches data/, db/, or a prod path; the tests
that prove that are the last two in the file.

The fixtures are a 20-row slice of the 2026-09-10 F&O bhavcopy (all four
instrument types, one zero-volume option) and the entire 975-byte
participant-OI file for the same session.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

FIXTURES = Path(__file__).parent / "fixtures"
UDIFF = (FIXTURES / "fo_udiff_head.csv").read_bytes()
POI = (FIXTURES / "participant_oi_head.csv").read_bytes()


@pytest.fixture(scope="module")
def mod():
    from src.ingest import fo_bhavcopy
    return fo_bhavcopy


# --- UDiFF -> legacy spine ---------------------------------------------------

def test_the_header_map_sources_every_legacy_column(mod):
    """Every one of FNO.columns must come from a named UDiFF column or a
    declared transform. An unsourced column would be filled with NULLs and
    look like data."""
    from src.warehouse.spine import FNO

    assert set(mod.LEGACY_FROM_UDIFF) == set(FNO.columns), (
        f"map covers {sorted(mod.LEGACY_FROM_UDIFF)}; spine needs {sorted(FNO.columns)}"
    )
    header = UDIFF.split(b"\n", 1)[0].decode().split(",")
    assert len(header) == 34
    for legacy, src in mod.LEGACY_FROM_UDIFF.items():
        assert src in header, f"{legacy} is sourced from {src!r}, which is not a UDiFF column"
    # everything not mapped is listed, not silently discarded
    mapped = set(mod.LEGACY_FROM_UDIFF.values()) | set(mod.UDIFF_GUARD_COLUMNS)
    assert set(header) - mapped == set(mod.SIDECAR_COLUMNS), (
        "a UDiFF column is neither mapped nor named in SIDECAR_COLUMNS"
    )


def test_parse_udiff_returns_every_column_and_row(mod):
    df = mod.parse_udiff_bytes(UDIFF)
    assert list(df.columns)[:8] == ["TradDt", "BizDt", "Sgmt", "Src", "FinInstrmTp",
                                    "FinInstrmId", "ISIN", "TckrSymb"]
    assert df.shape == (20, 34)


def test_option_and_futures_rows_both_survive(mod):
    leg = mod.to_legacy_spine(mod.parse_udiff_bytes(UDIFF))
    by = leg.groupby("instrument").size().to_dict()
    assert by == {"FUTSTK": 2, "FUTIDX": 3, "OPTSTK": 7, "OPTIDX": 8}
    assert "IDF" not in set(leg["instrument"]) and "STO" not in set(leg["instrument"]), (
        "raw UDiFF codes leaked through; the 2026-06-17..07-07 stretch already "
        "carries them and this parser must not add to it"
    )
    # the zero-volume option is a row, not a drop (the legacy spine keeps them)
    zero = leg[(leg.symbol == "RELIANCE") & (leg.strike == 1480.0) & (leg.option_typ == "PE")]
    assert len(zero) == 1 and int(zero.contracts.iloc[0]) == 0


def test_strike_and_expiry_types_follow_the_legacy_convention(mod):
    leg = mod.to_legacy_spine(mod.parse_udiff_bytes(UDIFF))
    fut = leg[leg.instrument.str.startswith("FUT")]
    opt = leg[leg.instrument.str.startswith("OPT")]
    # futures: strike 0.0 and option_typ 'XX', as on every legacy futures row —
    # NOT NULL, whatever spine.py's comment says
    assert (fut.strike == 0.0).all() and (fut.option_typ == "XX").all()
    assert set(opt.option_typ) == {"CE", "PE"}
    assert (opt.strike > 0).all()
    assert str(leg.strike.dtype) == "float64"
    assert leg.expiry.str.fullmatch(r"\d{4}-\d{2}-\d{2}").all()
    assert leg.date.str.fullmatch(r"\d{4}-\d{2}-\d{2}").all()
    assert leg.date.nunique() == 1 and leg.date.iloc[0] == "2026-09-10"


def test_units_are_converted_not_copied(mod):
    """TtlTrfVal is rupees; the spine holds lakh. TtlTradgVol is contracts.
    RELIANCE 26SEP fut: 18,697 contracts x lot 500 x ~1,278 = 11.94 bn = TtlTrfVal."""
    leg = mod.to_legacy_spine(mod.parse_udiff_bytes(UDIFF))
    r = leg[(leg.instrument == "FUTSTK") & (leg.symbol == "RELIANCE") & (leg.expiry == "2026-09-29")].iloc[0]
    assert int(r.contracts) == 18697
    assert r.val_inlakh == pytest.approx(11942096050.00 / 1e5)
    assert int(r.open_int) == 129406500 and int(r.chg_in_oi) == 635000
    assert r.settle_pr == pytest.approx(1272.50) and r.close == pytest.approx(1272.50)
    neg = leg[leg.chg_in_oi < 0]
    assert len(neg) >= 1, "negative OI change must survive as a signed int"


def test_legacy_column_set_and_dtypes_match_the_spine_spec(mod):
    from src.warehouse.spine import FNO

    leg = mod.to_legacy_spine(mod.parse_udiff_bytes(UDIFF))
    assert list(leg.columns) == list(FNO.columns), "column ORDER is the spine's"
    assert "_y" not in leg.columns, "_y is the partition column spine.build derives"
    ints = {"contracts", "open_int", "chg_in_oi"}
    for c in ints:
        assert str(leg[c].dtype).startswith("int"), f"{c} must be integer, got {leg[c].dtype}"
    for c in ("open", "high", "low", "close", "settle_pr", "val_inlakh", "strike"):
        assert str(leg[c].dtype) == "float64", c
    key = list(FNO.unique_key)
    assert not leg.duplicated(subset=key).any(), "the spine's unique key is violated"


def test_an_unknown_instrument_code_is_an_error_not_a_guess(mod):
    bad = UDIFF.replace(b",STF,", b",ZZZ,", 1)
    with pytest.raises(mod.FoParseError, match="ZZZ"):
        mod.to_legacy_spine(mod.parse_udiff_bytes(bad))


def test_two_sessions_in_one_file_is_an_error(mod):
    bad = UDIFF.replace(b"\n2026-09-10,2026-09-10,", b"\n2026-09-11,2026-09-11,", 1)
    with pytest.raises(mod.FoParseError, match="TradDt"):
        mod.to_legacy_spine(mod.parse_udiff_bytes(bad))


def test_zip_and_plain_csv_both_parse(mod):
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("BhavCopy_NSE_FO_0_0_0_20260910_F_0000.csv", UDIFF)
    a = mod.parse_udiff_bytes(buf.getvalue())
    b = mod.parse_udiff_bytes(UDIFF)
    assert a.equals(b)


# --- participant OI ----------------------------------------------------------

def test_participant_categories_are_exactly_the_five(mod):
    df = mod.parse_participant_oi_bytes(POI)
    assert set(df["category"]) == {"Client", "DII", "FII", "Pro", "TOTAL"}
    assert len(df) == 5, "one row per category, no title row, no blank row"


def test_total_row_is_kept_verbatim_and_is_the_source_sum_within_one(mod):
    """TOTAL is the source's OWN sum row. Kept, never re-derived, never
    dropped: dropping it silently doubles a naive GROUP BY (migration 0004).

    NEVER RE-DERIVED, because the source's row is not exactly the sum. On the
    real 2026-09-10 file NSE's TOTAL is +1 on Option Index Call Long
    (5,704,449 against parts summing to 5,704,448) and -1 on Total Long
    Contracts — NSE forces TOTAL long == TOTAL short per instrument and the
    parts do not quite. A parser that recomputed TOTAL would disagree with the
    published figure by one contract and nobody would know which was "right".
    Verbatim, with the discrepancy pinned, is the honest shape.
    """
    df = mod.parse_participant_oi_bytes(POI).set_index("category")
    parts = df.loc[["Client", "DII", "FII", "Pro"]]
    assert len(mod.PARTICIPANT_OI_SOURCE_BACKED) == 14
    for col in mod.PARTICIPANT_OI_SOURCE_BACKED:
        assert abs(df.loc["TOTAL", col] - parts[col].sum()) <= 1, col
    # the exact published figures, not a recomputation
    assert df.loc["TOTAL", "index_fut_long"] == 436548
    assert df.loc["TOTAL", "index_call_long"] == 5704449 == df.loc["TOTAL", "index_call_short"]
    assert parts["index_call_long"].sum() == 5704448
    assert df.loc["TOTAL", "Total Long Contracts"] == 24709619
    assert parts["Total Long Contracts"].sum() == 24709620


def test_participant_oi_maps_by_name_not_position(mod):
    """Source order is Call Long, Put Long, Call Short, Put Short; the table's
    is Call Long, Call Short, Put Long, Put Short. A positional map would
    silently swap put-long and call-short."""
    df = mod.parse_participant_oi_bytes(POI).set_index("category")
    assert df.loc["Client", "index_call_long"] == 3945571
    assert df.loc["Client", "index_put_long"] == 2355516
    assert df.loc["Client", "index_call_short"] == 3565411
    assert df.loc["Client", "index_put_short"] == 3170018
    assert df.loc["Client", "index_fut_net"] == 286829 - 55858
    assert df.loc["DII", "stock_fut_net"] == 354539 - 4636004


def test_participant_oi_session_date_comes_from_the_title_and_may_be_checked(mod):
    from datetime import date

    df = mod.parse_participant_oi_bytes(POI)
    assert set(df["session_date"]) == {date(2026, 9, 10)}
    assert mod.parse_participant_oi_bytes(POI, session_date=date(2026, 9, 10)) is not None
    with pytest.raises(mod.FoParseError, match="session"):
        mod.parse_participant_oi_bytes(POI, session_date=date(2026, 9, 11))


def test_participant_oi_table_shape_matches_the_migration(mod):
    import re

    ddl = (Path(__file__).parents[1] / "migrations" / "0004_participant_oi.duckdb.sql").read_text()
    cols = re.findall(r"^\s+(\w+)\s+(?:DATE|VARCHAR|DOUBLE)", ddl, re.M)
    table_cols = [c for c in cols if c not in ("source", "loaded_at")]
    rows = mod.to_participant_oi_rows(mod.parse_participant_oi_bytes(POI))
    assert list(rows.columns) == table_cols
    # and the four source columns that have no home are named, not lost
    assert set(mod.PARTICIPANT_OI_SIDECAR) == {
        "Option Stock Call Short", "Option Stock Put Short",
        "Total Long Contracts", "Total Short Contracts",
    }


# --- the boundary 0062 keeps -------------------------------------------------

def test_the_parser_never_touches_the_research_db_or_the_prod_warehouse(mod):
    """Collection-only lifts for code and fixtures. A parser that can open
    research_db or write under data/ is a land step wearing a parser's name."""
    import ast
    import inspect

    src = inspect.getsource(mod)
    tree = ast.parse(src)
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert "duckdb" not in names and "connect" not in attrs, "the parser opens DuckDB"
    assert "research_db" not in names | attrs
    assert "warehouse_dir" not in names | attrs
    assert "SEED_INCREMENTS" not in names | attrs
    assert "ARCHIVE" not in names | attrs
    for imported in (n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))):
        modname = getattr(imported, "module", None) or ""
        for alias in imported.names:
            assert "paths" not in (modname + alias.name), (
                f"the parser imports src.common.paths ({modname}.{alias.name})"
            )
    assert not any(isinstance(n, ast.Constant) and isinstance(n.value, str)
                   and ("data/prod" in n.value or "research_prod" in n.value)
                   for n in ast.walk(tree))


def test_write_legacy_refuses_data_and_db_paths(mod, tmp_path):
    leg = mod.to_legacy_spine(mod.parse_udiff_bytes(UDIFF))
    out = mod.write_legacy(leg, tmp_path / "fno_20260910.parquet")
    assert out.exists() and out.stat().st_size > 0
    repo = Path(__file__).parents[1]
    for forbidden in (repo / "data" / "x.parquet", repo / "db" / "x.parquet",
                      repo / "data" / "prod" / "warehouse" / "fno_spine" / "x.parquet"):
        with pytest.raises(mod.FoParseError, match="refus"):
            mod.write_legacy(leg, forbidden)
    assert not (repo / "data" / "x.parquet").exists()
