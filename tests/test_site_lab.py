"""The Research lab's data (src/site/lab.py, decision 0094).

The lab is the one place the site may show an after-event return, so these tests
hold its walls: EXPLORE stocks only, its own folder, never published."""

from __future__ import annotations

import inspect
import json
import re
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from src.research import resignations, split
from src.site import export as X
from src.site import lab

pytestmark = pytest.mark.unit
ROOT = Path(__file__).resolve().parents[1]


def _isin(stratum: str) -> str:
    return next(i for i in (f"INE{n:06d}A01010" for n in range(5000)) if split.assign("", i)[0] == stratum)


def _frame(isin: str) -> pd.DataFrame:
    return pd.DataFrame({"role": ["DEAL_BUY"], "tdate": ["2015-03-02"], "isin": [isin], "symbol": ["ACME"],
                         "ab_CHAR_MATCHED": [0.0123]})


def test_only_explore_events_reach_the_return_query():
    keep, drop1, drop2 = _isin("EXPLORE"), _isin("SELECT"), _isin("CONFIRM")
    evs = [resignations.Event("2015-03-02", i, "DEAL_BUY") for i in (keep, drop1, drop2)]
    assert [e.isin for e in lab.explore_only(evs)] == [keep]


@pytest.mark.parametrize("stratum", ["SELECT", "CONFIRM"])
def test_the_file_is_refused_whole_if_one_row_is_not_explore(tmp_path, stratum):
    df = lab.assemble({h: pd.concat([_frame(_isin("EXPLORE")), _frame(_isin(stratum))]) for h in lab.HORIZONS})
    with pytest.raises(lab.LabLeak):
        lab.write(df, tmp_path)
    assert not (tmp_path / "lab" / "events.json").exists()


def test_the_file_lives_in_lab_and_says_what_it_is(tmp_path):
    df = lab.assemble({h: _frame(_isin("EXPLORE")) for h in lab.HORIZONS})
    path = lab.write(df, tmp_path)
    assert path == tmp_path / "lab" / "events.json"
    doc = json.loads(path.read_text())
    assert doc["label"] == "Exploratory, not pre-registered" and doc["stratum"] == "EXPLORE"
    row = dict(zip(doc["cols"], doc["rows"][0], strict=True))
    assert row["a21"] == 1.23 and row["sym"] == "ACME" and "isin" not in row


def test_a_return_missing_at_one_horizon_stays_blank_never_zero(tmp_path):
    frames = {h: _frame(_isin("EXPLORE")) for h in lab.HORIZONS}
    frames[63] = frames[63].assign(ab_CHAR_MATCHED=[float("nan")])
    doc = json.loads(lab.write(lab.assemble(frames), tmp_path).read_text())
    row = dict(zip(doc["cols"], doc["rows"][0], strict=True))
    assert row["a63"] is None and row["a5"] == 1.23


def test_deal_events_take_eligible_buys_and_clean_sells_only():
    """eligible_for_research holds no sell at all: reading it alone dropped the
    whole DEAL_SELL type from the first build."""
    q = duckdb.connect()
    q.execute("""CREATE TABLE security_master AS SELECT * FROM (VALUES (1, 'INE1'), (2, NULL)) t(security_id, isin)""")
    q.execute(f"""CREATE TABLE institutional_deals_clean AS SELECT * FROM (VALUES
        (1, DATE '2015-03-02', 'BUY', true, NULL),
        (1, DATE '2015-03-03', 'SELL', false, '{lab.SELL_REASON}'),
        (1, DATE '2015-03-04', 'SELL', false, 'same-day round trip'),
        (1, DATE '2015-03-05', 'BUY', false, 'below the value floor'),
        (2, DATE '2015-03-06', 'SELL', false, '{lab.SELL_REASON}')
        ) t(security_id, trade_date, side, eligible_for_research, ineligibility_reason)""")
    got = sorted((e.date, e.role) for e in lab._deal_events(q))
    q.close()
    assert got == [("2015-03-02", "DEAL_BUY"), ("2015-03-03", "DEAL_SELL")]


def test_a_result_is_up_or_down_against_the_same_quarter_a_year_ago():
    res = pd.DataFrame({"symbol": ["A", "A", "A", "A", "B"],
                        "qe": ["2020-03-31", "2021-03-31", "2022-03-31", "2023-03-31", "2021-03-31"],
                        "pat": [10.0, 12.0, 9.0, 9.0, 5.0]})
    assert lab.result_direction(res).tolist() == [None, "RESULT_UP", "RESULT_DOWN", None, None]


def test_the_ordinary_exporter_cannot_write_the_lab():
    """The field-name ban in test_site_export only stays honest if export never
    pulls these rows in."""
    code = inspect.getsource(X)
    assert not re.search(r"""\b(src\.site\.lab|import lab)\b|["']lab["']""", code)


def test_the_publisher_refuses_while_the_lab_exists():
    """Decision 0094: the section must be removed before any publishing."""
    text = (ROOT / "scripts" / "site_publish.sh").read_text()
    refuse = text.index('dist/lab')
    assert refuse < text.index("git init"), "the check must come before anything is pushed"


def test_market_micro_describes_turnover_delivery_and_concentration(tmp_path):
    spine = tmp_path / "spine.parquet"
    delivery = tmp_path / "delivery.parquet"
    q = duckdb.connect()
    q.execute(f"""COPY (SELECT * FROM (VALUES
        ('A', '2026-01-02', 100.0, 10), ('B', '2026-01-02', 100.0, 30), ('C', '2026-01-02', 0.0, 50),
        ('A', '2026-02-02', 100.0, 10)) t(symbol, date, close, volume)) TO '{spine}' (FORMAT parquet)""")
    q.execute(f"""COPY (SELECT * FROM (VALUES
        ('2026-01-02', 'A', 'EQ', 10, 5), ('2026-01-02', 'B', 'EQ', 30, 3), ('2026-01-02', 'X', 'N1', 99, 99),
        ('2026-02-02', 'A', 'EQ', 10, 4)) t(date, symbol, series, traded_qty, deliverable_qty))
        TO '{delivery}' (FORMAT parquet)""")
    got = X.market_micro(q, str(spine), delivery)
    q.close()
    rows = [dict(zip(got["cols"], r, strict=True)) for r in got["rows"]]
    jan = rows[0]
    assert jan["m"] == "2026-01" and jan["stocks"] == 2           # a zero-price row is not a traded stock
    assert jan["turnover_cr"] == 0.0 and jan["top10_pct"] == 100.0
    assert jan["delivery_pct"] == 20.0                            # 8 of 40, the N1 bond line is out
    assert rows[1]["delivery_pct"] == 40.0
    assert not any(c.startswith("ret") or "return" in c for c in got["cols"])
