"""Point-in-time industries from the fund portfolios (src/warehouse/sector_history.py)."""

from __future__ import annotations

from datetime import date

import pytest

from src.warehouse import sector_history as H


@pytest.mark.unit
def test_a_label_is_known_from_the_tenth_of_the_next_month():
    assert H.known_from(date(2026, 9, 30)) == date(2026, 10, 10)
    assert H.known_from(date(2025, 12, 31)) == date(2026, 1, 10)


@pytest.mark.unit
def test_the_month_label_is_the_majority_across_schemes_ignoring_spelling():
    rows = [("INE1", date(2026, 8, 31), "Banks"), ("INE1", date(2026, 8, 31), "banks "),
            ("INE1", date(2026, 8, 31), "BANKS"), ("INE1", date(2026, 8, 31), "Finance")]
    got = H.monthly_labels(rows)[("INE1", date(2026, 8, 31))]
    assert got == ("Banks", "HIGH")                   # 3 of 4 agree; the commonest exact spelling
    lone = H.monthly_labels([("INE2", date(2026, 8, 31), "Power")])
    assert lone[("INE2", date(2026, 8, 31))][1] == "MEDIUM"   # unanimous but one row


@pytest.mark.unit
def test_months_merge_and_a_change_closes_the_interval_the_day_before_it_is_known():
    lab = {("INE1", date(2026, 6, 30)): ("Software", "HIGH"), ("INE1", date(2026, 7, 31)): ("Software", "LOW"),
           ("INE1", date(2026, 9, 30)): ("IT - Software", "HIGH")}
    got = H.intervals(lab)
    assert got == [("INE1", "Software", date(2026, 7, 10), date(2026, 10, 9), "LOW"),
                   ("INE1", "IT - Software", date(2026, 10, 10), None, "HIGH")]


@pytest.mark.unit
def test_one_company_with_two_isins_gets_one_set_of_intervals():
    # HDFC Bank changed ISIN in 2019; keyed by security, its months are one series.
    lab = H.monthly_labels([(7, date(2019, 8, 31), "Banks"), (7, date(2019, 9, 30), "BANKS"),
                            (7, date(2019, 10, 31), "Banks")])
    got = H.intervals(lab)
    assert len(got) == 1 and got[0][3] is None


@pytest.mark.unit
def test_the_industry_ladder_leads_with_sector_and_keeps_char_matched_unchanged():
    from src.research import charmatch as C
    assert [lv for lv, _ in C.IND_LEVELS] == ["SECTOR_SIZE3", "SECTOR", "SIZE_MOM_VOL", "SIZE_MOM", "SIZE"]
    default = C.ladder(10)
    assert "SECTOR" not in default.joins and "SECTOR" not in default.match_level
    ind = C.ladder(10, rungs=C.IND_LEVELS)
    assert ind.match_level.index("SECTOR_SIZE3") < ind.match_level.index("'SIZE_MOM_VOL'")


@pytest.mark.unit
def test_an_event_without_a_sector_falls_through_to_the_characteristic_cells():
    import duckdb

    from src.research import charmatch as C
    con = duckdb.connect()
    con.execute("CREATE TABLE cells (symbol VARCHAR, d DATE, ret DOUBLE, size_q INT, mom_q INT, vol_q INT,"
                " sector VARCHAR, size_t INT)")
    rows = [(f"S{i}", "2024-01-31", 0.01 * i, 1, 1, 1, "Banks" if i < 12 else None, 1) for i in range(24)]
    con.executemany("INSERT INTO cells VALUES (?,?,?,?,?,?,?,?)", rows)
    for lv, keys in C.IND_LEVELS:
        con.execute(f"CREATE TABLE cm_{lv} AS {C.cell_means_sql(lv, keys)}")
    con.execute("CREATE TABLE ec AS SELECT * FROM cells WHERE symbol IN ('S0', 'S20')")
    lad = C.ladder(10, own="ec", rungs=C.IND_LEVELS)
    got = dict(con.execute(f"SELECT ec.symbol, {lad.match_level} FROM ec {lad.joins}").fetchall())
    assert got == {"S0": "SECTOR_SIZE3", "S20": "SIZE_MOM_VOL"}
