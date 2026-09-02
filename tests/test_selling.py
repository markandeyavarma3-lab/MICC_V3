"""The selling study, and the guards that stop it becoming a finding by accident.

0044 recorded a −23.80% twelve-month market-relative mean on sold names against
a null of −0.00%, and a hit rate of 24.0% against a null of 32.0%. That is
exploratory, it is not registered, and the single most likely way this project
embarrasses itself is by that number migrating into a report.
"""

from __future__ import annotations

import pytest

from src.research import measure, selling

pytestmark = pytest.mark.unit


def test_selling_uses_the_same_bound_as_every_other_study():
    """A study measured after three failures must not get an easier bar. The
    bound scales linearly with horizon at research.yml's rate (0028) and is a
    MAGNITUDE, so the negative expected sign changes nothing."""
    r = selling.Row("252s (12m)", 12.0, 3626, 232, 0.4007, 0.117047)
    assert r.bound == pytest.approx(measure.BOUND_PER_MONTH * 12.0)
    assert not r.powered, "11.70% MDE against a 6.00% bound is not powered"


def test_the_module_computes_no_effect_estimate():
    """0035: any estimate of an effect — mean, median, hit rate, t — must go
    through the ConfirmationGuard and charge a family. This module printed a
    cohort mean until 2026-09-02 and charged nothing; family_charge holds 0 rows.

    measure.py's docstring states the rule one file away. This is the test that
    would have caught the divergence.
    """
    import ast
    import inspect

    # AST, not text: the docstring legitimately NAMES the removed expression to
    # explain the correction. A grep would fail on the explanation of the fix,
    # which is how a test starts punishing documentation.
    tree = ast.parse(inspect.getsource(selling))
    calls = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        and n.func.attr in ("mean", "median")
    ]
    assert not calls, f"{len(calls)} effect estimate(s) outside the guard"
    assert not any(
        isinstance(n, ast.AnnAssign) and getattr(n.target, "id", "") == "mean_ab"
        for n in ast.walk(tree)
    ), "Row still carries a mean field"
    r = selling.Row("252s (12m)", 12.0, 100, 50, 0.4, 0.117)
    assert not r.powered
    assert not hasattr(r, "mean_ab"), (
        "0035 forbids an effect estimate outside the guard; this module carried "
        "one until 2026-09-02 and charged no family"
    )


def test_the_filters_match_the_buy_side_exactly():
    """The only legitimate difference between this and measure.grid is the side.
    A looser size floor or a missing participation ceiling here would make
    selling look powered for a reason that has nothing to do with selling."""
    sql = selling.EVENT_SQL
    assert "cl.side = 'SELL'" in sql
    assert "BETWEEN 0.005 AND 0.50" in sql, "size floor and participation ceiling"
    assert "gross_deal_value >= 1e7" in sql, "the Rs 1cr floor"
    assert "same_day_round_trip_flag" in sql
    assert "PROP_HFT" in sql
    assert "unresolved_symbol_flag" in sql and "uncovered_symbol_flag" in sql


def test_no_registered_study_result_exists_for_selling():
    """THE GUARD THAT MATTERS. 0044 is explicit that nothing measured there is a
    finding, and 0002 requires the spec frozen before results. If a selling
    study is ever registered this test should be updated deliberately, as part
    of that registration — not quietly deleted when it starts failing."""
    import sqlite3

    from src.common.paths import governance_db

    db = governance_db("prod")
    if not db.exists():
        pytest.skip("no governance store in this environment")
    con = sqlite3.connect(db)
    try:
        rows = con.execute(
            "SELECT COUNT(*) FROM experiment_registry"
            " WHERE lower(COALESCE(name, '')) LIKE '%sell%'"
        ).fetchone()[0]
    except sqlite3.OperationalError:
        pytest.skip("experiment_registry has no name column in this schema")
    finally:
        con.close()
    assert rows == 0, (
        "a selling experiment is registered; 0044's exploratory numbers must now "
        "be disclosed in that registration, and this test updated to say so"
    )
