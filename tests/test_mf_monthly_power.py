"""The monthly mutual-fund power preview: dispersion only, never the holding."""

from __future__ import annotations

import inspect
import re

import numpy as np
import pandas as pd
import pytest

from src.research import mf_monthly_power as M


@pytest.mark.unit
def test_the_module_never_reads_a_holding_column():
    """Decision 0035: power may see which stock-months exist, never how much was
    held. The SQL selects isin and as_of from the portfolios and nothing else."""
    src = inspect.getsource(M)
    code = src.split('"""', 2)[2]                      # past the module docstring
    for col in ("qty", "value_cr", "pct", "shares"):
        assert not re.search(rf"\b{col}\b", code), f"the preview names the holding column {col!r}"


@pytest.mark.unit
def test_the_mde_is_the_null_se_times_the_z_sum_and_the_overlap_is_charged():
    rng = np.random.default_rng(3)
    rows = [(f"2020-{m:02d}-28", i, rng.normal(0, 0.1)) for m in range(1, 13) for i in range(300)]
    df = pd.DataFrame(rows, columns=["month", "security_id", "rel"])
    r21, r63 = M.assess(df, 21, draws=300), M.assess(df, 63, draws=300)
    assert r21.mde == pytest.approx(M.Z_SUM * r21.null_se)
    assert r21.overlap_inflation == 1.0 and r63.overlap_inflation == 3.0
    assert r63.ratio_overlap == pytest.approx(r63.mde * np.sqrt(3) / r63.bound)
    # analytic: sqrt(2) * 0.1 / sqrt(30) / sqrt(12) per random-decile spread
    assert r21.null_se == pytest.approx(np.sqrt(2) * 0.1 / np.sqrt(30) / np.sqrt(12), rel=0.15)


@pytest.mark.unit
def test_a_thin_month_is_left_out_and_too_few_months_is_an_error():
    df = pd.DataFrame([("2020-01-31", i, 0.0) for i in range(50)], columns=["month", "security_id", "rel"])
    with pytest.raises(RuntimeError):
        M.assess(df, 21, draws=10)
