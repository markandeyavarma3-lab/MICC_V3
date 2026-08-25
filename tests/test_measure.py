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
    # 5.2803% THROUGH THE PIPELINE, against 5.5572% via the old seed-parquet
    # bypass that decision 0034 was decided on. The difference is 283 events:
    # the mart excludes uncovered and unresolved symbols that reading the parquet
    # directly silently included. 0034 is NOT edited to match — it records what
    # was decided and on what basis — and the conclusion is unchanged, since both
    # figures sit under the 6.00% bound.
    assert row.mde == pytest.approx(0.052803, abs=5e-6), (
        f"the 12-month MDE is {row.mde:.6%}; the pipeline figure is 5.2803%. "
        f"If this changed legitimately, say so in a decision record."
    )
    assert row.n_events == 17_705
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


# --- the calendar and the mart, which the grid now depends on ----------------


@needs_spine
def test_the_calendar_is_observed_not_generated():
    """Plan 1.4: observed sessions, never generated. The proof it matters is that
    the data contains three SATURDAY sessions — 2020-11-14 Muhurat and two 2024
    special sessions — which any weekday-minus-holidays calendar would drop,
    silently changing what "10 trading sessions" means."""
    from src.common import calendar

    s = calendar.sessions("prod")
    assert len(s) == 5339, f"{len(s)} sessions; the Phase 1 gate expects 5,339"
    weekend = [d for d in s if d.weekday() >= 5]
    assert len(weekend) == 3, f"expected 3 weekend sessions, found {len(weekend)}"
    assert calendar.next_session(s[0], "prod") == s[1]
    assert calendar.next_session(s[-1], "prod") is None, (
        "past the end of the data there is no next session, and inventing one "
        "would fabricate an entry date"
    )


@needs_spine
def test_zero_silent_drops():
    """Phase 4's gate verbatim: every clean deal either resolves to a security or
    carries an explicit failure status. Every raw row must appear in the mart."""
    import duckdb

    from src.common.paths import research_db

    con = duckdb.connect(str(research_db("prod")))
    try:
        raw = con.execute("SELECT COUNT(*) FROM institutional_deals_raw").fetchone()[0]
        clean = con.execute("SELECT COUNT(*) FROM institutional_deals_clean").fetchone()[0]
        unexplained = con.execute(
            "SELECT COUNT(*) FROM institutional_deals_clean"
            " WHERE NOT eligible_for_research AND ineligibility_reason IS NULL"
        ).fetchone()[0]
    finally:
        con.close()
    assert clean == raw, f"{raw:,} raw rows produced {clean:,} clean rows"
    assert unexplained == 0, f"{unexplained:,} rows excluded with no stated reason"
