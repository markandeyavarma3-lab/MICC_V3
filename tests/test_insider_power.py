"""insider_power.py — making 0046's ad-hoc numbers reproducible, and the pledge answer.

0046 reported promoter buy/sell power figures from a shell heredoc that was
never committed — exactly the "analysis code never committed" defect PLAN_3
§6R records about exp_001. These tests pin the reproduction and the three
pledge populations the owner asked about.
"""

from __future__ import annotations

import pytest

from src.research import insider_power, measure

pytestmark = pytest.mark.needs_data


def test_no_effect_estimate_is_computed():
    """0035: dispersion may use the full universe, an effect may not. This
    module must never carry a mean/median field the way selling.py did until
    0048 removed one."""
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(insider_power))
    calls = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        and n.func.attr in ("mean", "median")
    ]
    assert not calls, f"{len(calls)} effect estimate(s) outside the guard"


def test_pledge_types_are_kept_as_three_separate_populations():
    """Pledge, Pledge Revoke and Pledge Invoke are different economic events —
    pooling them would average a financing choice, a release and a forced
    foreclosure into a number that means nothing."""
    labels = {p for p, _ in insider_power.POPULATIONS}
    assert {"pledge", "pledge revoke", "pledge invoke"} <= labels
    filters = {f for _, f in insider_power.POPULATIONS}
    assert len(filters) == len(insider_power.POPULATIONS), (
        "two populations share a filter and are being double-counted as distinct"
    )


def test_pledge_events_filter_on_value_not_quantity():
    """Measured on the seed: 128 of 14,148 Pledge rows have quantity > 0
    against 13,698 with value > 0. Filtering on quantity would nearly empty
    the table — the same defect 0046 found on ordinary Sell rows."""
    for _, txn_filter in insider_power.POPULATIONS:
        sql = insider_power._events_sql(txn_filter)
        assert "value > 0" in sql
        assert "quantity" not in sql.lower()


def test_only_promoters_and_promoter_group_are_counted():
    """0046 measured PROMOTER buys/sells specifically because promoters are the
    class with plausible informational access. Pooling in employees or
    directors answers a different, weaker question under the same label."""
    assert insider_power.PROMOTER_CATEGORIES == ("Promoters", "Promoter Group")
    for _, txn_filter in insider_power.POPULATIONS:
        sql = insider_power._events_sql(txn_filter)
        assert "'Promoters'" in sql and "'Promoter Group'" in sql
        assert "Employees" not in sql and "Director" not in sql


def test_the_grid_reproduces_0046_exactly():
    """The number this whole module exists to make reproducible. 0046: promoter
    buy 12m 1.51x short, promoter sell 12m 1.25x short — both from an ad-hoc run
    that was never committed as code."""
    rows = insider_power.grid("prod")
    buy = next(r for r in rows if r.population == "promoter buy" and r.horizon == "252s (12m)")
    sell = next(r for r in rows if r.population == "promoter sell" and r.horizon == "252s (12m)")
    assert buy.n_events == 24_835
    assert buy.mde == pytest.approx(0.090728, abs=1e-4)
    assert sell.n_events == 12_829
    assert sell.mde == pytest.approx(0.075268, abs=1e-4)


def test_pledge_invoke_does_not_open_a_new_path():
    """THE ANSWER TO THE QUESTION THIS MODULE WAS BUILT TO SETTLE. Pledge
    Invoke — a lender forcing the sale of a promoter's collateral — is
    economically the closest thing in this dataset to genuine distress. It is
    also the SMALLEST and NOISIEST population measured: n=958 against promoter
    sell's 12,829, cohort SD 49.70% against 22.64%. If pledges were going to
    rescue the project's power problem, this is where it would show up, and it
    does not — it is the worst-powered population in the whole grid.
    """
    rows = insider_power.grid("prod")
    invoke = next(r for r in rows if r.population == "pledge invoke" and r.horizon == "252s (12m)")
    sell = next(r for r in rows if r.population == "promoter sell" and r.horizon == "252s (12m)")
    assert invoke.n_events < sell.n_events
    assert invoke.mde / invoke.bound > sell.mde / sell.bound, (
        "pledge invoke closed the gap on promoter sell; the 'no rescue' finding "
        "needs re-examining, not silently dropping this assertion"
    )


def test_the_bound_is_the_same_as_every_other_study():
    """Pledge data must not get a friendlier bar than bulk buys, consensus or
    selling got. All scale linearly with horizon at research.yml's rate."""
    r = insider_power.Row("pledge", "252s (12m)", 12.0, 100, 50, 0.3, 0.15)
    assert r.bound == pytest.approx(measure.BOUND_PER_MONTH * 12.0)
    assert not r.powered
