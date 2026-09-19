"""The preliminary power module for exp_004: dispersion only, no signal read.

Decision 0035 lets a power computation use the full universe because
dispersion cannot distinguish a true effect from a false one — PROVIDED it
never conditions on the signal. The first test enforces that on the module's
own source; the rest pin the arithmetic on synthetic outcomes.
"""

from __future__ import annotations

import ast
import inspect

import numpy as np
import pandas as pd
import pytest

from src.research import holdings_power as hp

pytestmark = pytest.mark.unit

SIGNAL_COLUMNS = {"pct_shares", "num_shareholders", "num_shares", "category", "category_raw"}


def test_the_module_never_names_a_signal_column():
    """Parsed from source, not trusted from the docstring. A power module that
    reads the holding percentage is a study without a registration."""
    src = inspect.getsource(hp)
    tree = ast.parse(src)
    # The SQL is a string constant. Prose (the report says "no ... category
    # was read") legitimately names them; a SELECT must not.
    sql = [n.value for n in ast.walk(tree)
           if isinstance(n, ast.Constant) and isinstance(n.value, str) and "SELECT" in n.value]
    assert sql, "no SQL found — the guard would be vacuous"
    for col in SIGNAL_COLUMNS:
        assert not any(col in s for s in sql), f"{col} appears in SQL"
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | \
            {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert not (names & SIGNAL_COLUMNS)


def _panel(quarters=18, names=160, sd=0.10, seed=1, outliers=0):
    rng = np.random.default_rng(seed)
    rows = []
    for q in range(quarters):
        r = rng.normal(0, sd, names)
        if outliers:
            r[:outliers] = 5.0  # a handful of 500% quarters
        for i, x in enumerate(r):
            rows.append((f"2022-{(q % 4) * 3 + 3:02d}-{'30' if (q % 4) in (1, 2) else '31'}-{q // 4}", i, x))
    return pd.DataFrame(rows, columns=["quarter_end", "security_id", "rel"])


def test_the_mde_matches_the_analytic_formula_on_gaussian_outcomes():
    """Random deciles on N(0, sd): spread SD = sqrt(2) sd / sqrt(n/10) per
    quarter; SE of the mean over Q quarters divides by sqrt(Q)."""
    df = _panel(quarters=18, names=160, sd=0.10)
    r = hp.assess(df, draws=1500, seed=3)
    expected = hp.Z_SUM * np.sqrt(2) * 0.10 / np.sqrt(16) / np.sqrt(18)
    assert r.mde == pytest.approx(expected, rel=0.15)
    assert r.mde_analytic == pytest.approx(expected, rel=0.10)
    assert r.n_quarters == 18


def test_more_names_per_quarter_lowers_the_mde_and_more_quarters_lowers_it_too():
    base = hp.assess(_panel(quarters=18, names=160), draws=800).mde
    wide = hp.assess(_panel(quarters=18, names=640), draws=800).mde
    long = hp.assess(_panel(quarters=36, names=160), draws=800).mde
    assert wide < base * 0.65   # sqrt(4) = 2x fewer, with sampling noise
    assert long < base * 0.85   # sqrt(2) = 1.4x fewer


def test_a_handful_of_extreme_quarters_dominates_the_unclipped_mde_and_winsorising_shows_it():
    """The real data had a 1st percentile of -45% and a 99th of +74%; clipping
    there cut the MDE 2.5x. The module must report both, not pick one."""
    df = _panel(quarters=18, names=160, sd=0.10, outliers=1)  # 0.6% of names: inside the 99th
    r = hp.assess(df, draws=800)
    assert r.mde_winsor < r.mde * 0.6
    # The clip point sits BELOW the outliers — that is what removes them. A
    # first version asserted p99 > the outlier value, which is backwards.
    assert r.p99 < 5.0 and r.p99 > 0.2


def test_too_few_quarters_is_an_error_not_a_number():
    with pytest.raises(RuntimeError, match="quarter"):
        hp.assess(_panel(quarters=1, names=160), draws=50)


def test_a_quarter_with_too_few_names_is_excluded_not_averaged_in():
    df = _panel(quarters=18, names=160)
    thin = pd.DataFrame([("2030-03-31", i, 0.0) for i in range(5)], columns=df.columns)
    r = hp.assess(pd.concat([df, thin]), draws=100)
    assert r.n_quarters == 18 and "2030-03-31" not in r.quarters


def test_the_only_thing_borrowed_from_the_study_module_is_the_market_leg():
    """THE WAY AROUND THE GUARD ABOVE. That guard reads this module's own
    source, so it sees nothing that arrives by import. `from
    src.research.holdings import *` would satisfy it completely while pulling
    in `signals()` — the signal parser — and a later line calling it would
    read as ordinary. The market leg is shared on purpose, so this file and
    the study measure the same return; nothing else may be."""
    tree = ast.parse(inspect.getsource(hp))
    borrowed = {alias.name for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom) and node.module == "src.research.holdings"
                for alias in node.names}
    assert borrowed == {"market_tri_sql"}, f"borrowed from the study module: {sorted(borrowed)}"


def test_the_market_leg_is_the_total_return_index_not_a_price_index():
    """The first run subtracted a PRICE index, so it credited the strategy with
    the market's dividends — ~0.3% per quarter against a 1.5% bound. It also
    read a seed file that ends 2026-07-07, silently dropping every quarter that
    matured after it."""
    src = inspect.getsource(hp)
    assert "market_tri_sql()" in src
    assert "global_indices_daily" not in src, "the seed price leg is back"
