"""exp_003's power module computes dispersion and n, and nothing that could
become a finding by accident. Decision 0067."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


def test_the_module_computes_no_effect_estimate():
    """0035. Same AST check test_selling uses: the docstring may NAME the
    forbidden thing; the code may not call it."""
    from src.research import oi_power

    tree = ast.parse(inspect.getsource(oi_power))
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and n.func.attr in ("mean", "median", "quantile", "qcut", "sign")]
    assert not calls, f"{len(calls)} effect/direction call(s) outside the guard"
    assert not any(f in {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
                   for f in ("index_fut_net", "stock_fut_net")), (
        "the signal columns are never read by the power module"
    )


def test_total_is_excluded_and_the_four_categories_are_the_spec():
    from src.research import oi_power

    assert "TOTAL" not in oi_power.CATEGORIES
    assert set(oi_power.CATEGORIES) == {"FII", "DII", "Pro", "Client"}
    assert oi_power.PRIMARY == 21 and 21 in oi_power.HORIZONS


def test_two_arm_mde_is_twice_one_arm_and_the_bound_scales_with_horizon():
    from src.research import oi_power

    r = oi_power.Row("FII", 21, 3000, 150, 0.04, 1.2, 0.010, 0.020)
    assert r.mde_two_arm == pytest.approx(2 * r.mde_one_arm)
    assert r.bound == pytest.approx(oi_power.BOUND_PER_MONTH * 1.0)
    assert oi_power.Row("FII", 252, 1, 1, 0.0, 1.0, 0.0, 0.0).bound == pytest.approx(oi_power.BOUND_PER_MONTH * 12)
    assert not r.powered and "UNDERPOWERED" in r.verdict
    assert oi_power.Row("FII", 21, 3000, 150, 0.04, 1.2, 0.002, 0.004).powered


def test_it_refuses_to_run_unregistered(tmp_path, monkeypatch):
    from src.research import oi_power

    monkeypatch.setattr(oi_power, "governance_db", lambda e=None: tmp_path / "empty.sqlite")
    with pytest.raises(RuntimeError, match="not REGISTERED"):
        oi_power.registered_hash()


def test_the_registration_script_freezes_the_spec_and_never_rewrites():
    src = (Path(__file__).parents[1] / "scripts" / "register_exp003.py").read_text()
    # code strings only — the docstring legitimately names the forbidden form
    tree = ast.parse(src)
    docs = {id(n.value) for n in ast.walk(tree)
            if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)}
    code = "\n".join(n.value for n in ast.walk(tree)
                     if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs)
    assert "INSERT OR REPLACE" not in code, "a registered spec is not rewritten"
    assert "INSERT INTO experiment_registry" in code
    import sys
    sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
    import register_exp003 as r

    assert r.SPEC["test_count"] == 8 == len(r.CATEGORIES) * len(r.SIGNALS)
    assert r.FAMILY == "TRACK_O_POSITIONING" and r.SPEC["trial_family"] == r.FAMILY
    assert "NOT CASH FLOW" in r.SPEC["hypothesis"]
    assert "NIFTY 50 PRICE index" in r.SPEC["benchmark_policy"]
    for k in ("hypothesis", "pass_bar", "kill_criteria", "confounds", "holding_period"):
        assert r.SPEC[k]
    from src.research import families
    assert families.get(r.FAMILY)["carried"] == 0


def test_the_family_is_new_and_declared_with_its_record():
    from src.research import families

    fam = families.get("TRACK_O_POSITIONING")
    assert fam["decision_record"] == "0067"
    assert fam["id"] != "TRACK_D_DEALS"
