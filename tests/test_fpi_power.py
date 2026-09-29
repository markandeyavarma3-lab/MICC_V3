"""The FPI-flow power check: dispersion and n only, never the flows themselves.

Decision 0035 allows a power computation before registration only if it
cannot see an effect. This module may know WHICH days NSDL reported a flow;
it must never read HOW MUCH, nor compute a mean, tercile or sign.
"""

from __future__ import annotations

import ast
import inspect

import pytest

from src.research import fpi_power

pytestmark = pytest.mark.unit

FLOW_COLUMNS = ("net_cr", "gross_purchases_cr", "gross_sales_cr", "net_usd_mn")


def test_the_module_computes_no_effect_estimate():
    tree = ast.parse(inspect.getsource(fpi_power))
    calls = [n.func.attr for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and n.func.attr in ("mean", "median", "quantile", "qcut", "sign", "corr")]
    assert not calls, f"an effect estimate in a pre-registration module: {calls}"


def test_the_flow_amounts_are_never_read():
    """Only the reporting DATE may come from the flows table."""
    src = inspect.getsource(fpi_power)
    sql = [n.value for n in ast.walk(ast.parse(src))
           if isinstance(n, ast.Constant) and isinstance(n.value, str) and "SELECT" in n.value]
    sql += [fpi_power._sample_sql(21)]
    for col in FLOW_COLUMNS:
        assert not any(col in s for s in sql), f"{col} is read"


def test_entry_is_strictly_after_the_reporting_date():
    """A flow reported on D was not public before D (0079)."""
    assert "p.d > days.rd" in fpi_power._sample_sql(21)


def test_two_arm_is_twice_one_arm_and_the_bound_scales_with_horizon():
    r = fpi_power.Row(63, 1000, 300, 0.1, 1.0, 0.01, 0.02, "a", "b")
    assert r.bound == pytest.approx(fpi_power.BOUND_PER_MONTH * 3)
    assert r.verdict.startswith("UNDERPOWERED") == (r.mde_two_arm > r.bound)
