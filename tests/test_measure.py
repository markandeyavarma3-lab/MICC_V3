"""The power grid decision 0034 rests on, pinned to committed code.

WHY THIS FILE MATTERS MORE THAN ITS SIZE SUGGESTS. PLAN_3 §6R records that
Finding 001 "is not reproducible ... the analysis code was never committed". On
2026-08-23 the twelve-month measurement that made 12 months the primary horizon
was run in throwaway shell heredocs and never committed either — the same defect,
inside the project whose subject is that defect. src/research/measure.py is the
correction and these tests are what stop it drifting back.
"""

from __future__ import annotations

import pytest

from src.common.paths import warehouse_dir
from src.research import measure

pytestmark = pytest.mark.data

needs_spine = pytest.mark.skipif(
    not any((warehouse_dir("prod") / "price_spine_adj").glob("**/*.parquet")),
    reason="adjusted spine not built",
)


@pytest.mark.unit
def test_the_bound_scales_with_horizon():
    """Decision 0028. A fixed bound is a unit error at every horizon but 21s."""
    rows = [measure.Row(h, s, m, 0, 0, 0.0, 1.0, 0.0) for h, s, m in measure.HORIZONS]
    assert [r.bound for r in rows] == [0.005, 0.015, 0.06]


@pytest.mark.unit
def test_the_grid_reads_the_adjusted_spine_not_the_raw_one():
    """universe.yml sets research_prices: adjusted. Raw and adjusted differ on
    17.1% of rows, and on raw prices a 1:2 split reads as -50%."""
    src = (measure.__file__ and open(measure.__file__).read()) or ""
    assert "price_spine_adj" in src
    assert '"price_spine"' not in src


@needs_spine
def test_the_twelve_month_figure_is_reproducible():
    """THE POINT OF THIS FILE. Decision 0034 and the report both quote 5.5572%.
    Until 2026-08-24 no committed code produced it."""
    row = next(r for r in measure.grid("prod") if r.sessions == 252)
    assert row.mde == pytest.approx(0.055572, abs=5e-6), (
        f"the 12-month MDE is {row.mde:.6%}; decision 0034 quotes 5.5572%. "
        f"If this changed legitimately, the decision record must change with it."
    )
    assert row.n_events == 17_988
    assert row.powered, "0034 rests on this horizon reaching its bound"


@needs_spine
def test_it_is_marginal_and_must_not_be_reported_otherwise():
    """A 7% margin. The report and 0034 both call it marginal; if the margin ever
    looks comfortable, something changed that needs explaining."""
    row = next(r for r in measure.grid("prod") if r.sessions == 252)
    margin = (row.bound - row.mde) / row.bound
    assert 0 < margin < 0.15, f"margin is {margin:.1%}, no longer marginal"


@needs_spine
def test_every_session_horizon_remains_short():
    """0034's other half: 12 months is the ONLY horizon within reach."""
    short = [r for r in measure.grid("prod") if r.sessions < 252]
    assert short and all(not r.powered for r in short)
