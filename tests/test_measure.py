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
    Until 2026-08-24 no committed code produced it.

    THE FIGURE HAS SINCE MOVED, AND AGAINST THE PROJECT. Applying Plan 2 §4.4's
    participation ceiling on 2026-08-26 — an event needing more than 5 sessions
    at a 10%-of-ADV cap cannot be built — removed 14,747 of 20,489 eligible
    events. Twelve months went from 5.2803% (POWERED) to 13.3038% (2.22x short).

    Not because the surviving data is worse: the excluded deals have a median
    436.8% of ADV against 14.6% for those kept, at similar rupee value, so they
    were deals in THIN stocks. Losing 72% of events leaves 3.5x fewer per
    monthly cohort, and a cohort mean of k events is ~1/sqrt(k) noisy —
    19.2% x sqrt(3.5) = 35.8% against 37.1% observed. The power was borrowed
    from events nobody could trade.
    """
    row = next(r for r in measure.grid("prod") if r.sessions == 252)
    # 5.2803% THROUGH THE PIPELINE, against 5.5572% via the old seed-parquet
    # bypass that decision 0034 was decided on. The difference is 283 events:
    # the mart excludes uncovered and unresolved symbols that reading the parquet
    # directly silently included. 0034 is NOT edited to match — it records what
    # was decided and on what basis — and the conclusion is unchanged, since both
    # figures sit under the 6.00% bound.
    assert row.mde == pytest.approx(0.133038, abs=5e-6), (
        f"the 12-month MDE is {row.mde:.6%}; the post-ceiling figure is 13.3038%. "
        f"If this changed legitimately, say so in a decision record."
    )
    assert row.n_events == 4_750
    assert not row.powered, (
        "12 months is 2.22x short of its bound once untradeable events are "
        "excluded. If this ever passes again, the reason must be explained."
    )


@needs_spine
def test_no_horizon_is_currently_registrable():
    """The honest state after the participation ceiling. design.py refuses a
    study whose horizons are ALL blind, so no Track D study can be registered
    as currently specified — and that is the finding, not a bug."""
    rows = measure.grid("prod")
    assert rows and not any(r.powered for r in rows), (
        "a horizon now reaches its bound; 0034's supersession needs revisiting"
    )


@needs_spine
def test_the_ceiling_excludes_untradeable_events():
    """Plan 2 §4.4. An event needing more than max_sessions_to_build at the
    participation cap cannot be established, so it is not a tradable signal."""
    import duckdb

    from src.common.paths import research_db
    from src.mart.clean import participation_ceiling

    assert participation_ceiling() == pytest.approx(0.50), (
        "10% of ADV over 5 sessions; costs.yml drives this"
    )
    con = duckdb.connect(str(research_db("prod")))
    try:
        leaked = con.execute(
            "SELECT COUNT(*) FROM institutional_deals_clean"
            " WHERE eligible_for_research AND deal_value_to_adv20 > 0.50"
        ).fetchone()[0]
    finally:
        con.close()
    assert leaked == 0, f"{leaked:,} untradeable events are still marked eligible"


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
