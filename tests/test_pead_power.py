"""pead_power: dispersion only — the fifths are random, so no surprise meets a return."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.research import pead_power as P


def _quarters(n: int, start: str = "2019Q1") -> list[str]:
    return list(pd.period_range(start, periods=n, freq="Q").to_timestamp(how="end").strftime("%Y-%m-%d"))


@pytest.mark.unit
def test_a_quarter_is_rankable_only_with_a_year_ago_profit_and_four_earlier_seasonal_differences():
    r = pd.DataFrame({"symbol": "X", "qe": _quarters(12), "pat": range(12)})
    got = dict(zip(r["qe"], P.eligible(r), strict=True))
    assert not got["2020-12-31"] and got["2021-03-31"]          # 2021Q1 has 2020Q1..Q4 behind it
    gap = r[r["qe"] != "2020-06-30"]                            # a missing quarter breaks two differences
    assert not dict(zip(gap["qe"], P.eligible(gap), strict=True))["2021-03-31"]


@pytest.mark.unit
def test_the_power_number_cannot_see_the_surprise():
    rng = np.random.default_rng(1)
    days = pd.date_range("2020-01-01", periods=36 * 30, freq="D")
    df = pd.DataFrame({"tdate": days.strftime("%Y-%m-%d"), "ab_X": rng.normal(0, 0.05, len(days))})
    a = P.random_spread_mde(df, "ab_X", 1.0, draws=20)
    # A perfectly informative surprise column changes nothing: it is never read.
    b = P.random_spread_mde(df.assign(sue=df["ab_X"]), "ab_X", 1.0, draws=20)
    assert a == b and a["cohorts"] == 36 and 0 < a["mde"] < 0.05
