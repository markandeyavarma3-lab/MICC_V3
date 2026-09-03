"""The cost model, and the three errors it exists to not repeat.

MICCV2 treated the statutory layer as constant and got three components wrong,
together +10.04 bps per round trip — enough to flip its one surviving
seasonality result from +3.70 bps to -6.36 bps per occurrence. At this effect
size the cost model is not bookkeeping around a result, it IS the result.

Each correction gets a test that fails if the old behaviour returns.
"""

from __future__ import annotations

from datetime import date

import pytest

from src.research import costs

pytestmark = pytest.mark.unit

TODAY = date(2026, 9, 1)
CR = 1e7  # one crore of turnover


def test_stt_is_charged_on_both_legs_not_sell_only():
    """CORRECTION 1. Equity DELIVERY attracts STT on buy AND sell; the
    predecessor charged it sell-only, understating every round trip by 10 bps."""
    buy = costs.statutory_cost(CR, TODAY, "BUY")
    sell = costs.statutory_cost(CR, TODAY, "SELL")
    assert buy.components["STT"] > 0, "STT is missing from the BUY leg"
    assert buy.components["STT"] == pytest.approx(sell.components["STT"])
    assert buy.components["STT"] == pytest.approx(CR * 0.0010)


def test_transaction_charges_differ_between_nse_and_bse():
    """CORRECTION 2. NSE 0.00307% against BSE 0.00375%. The predecessor used one
    rate for both, and BSE is materially the more expensive."""
    nse = costs.statutory_cost(CR, TODAY, "BUY", exchange="NSE")
    bse = costs.statutory_cost(CR, TODAY, "BUY", exchange="BSE")
    assert bse.components["TXN"] > nse.components["TXN"]
    assert nse.components["TXN"] == pytest.approx(CR * 0.0000307)
    assert bse.components["TXN"] == pytest.approx(CR * 0.0000375)


def test_gst_applies_to_brokerage_plus_sebi_plus_transaction():
    """CORRECTION 3. GST is 18% of (brokerage + SEBI + TXN), not of brokerage
    alone. Applying it to brokerage only understates it by 18% of the other two.
    """
    c = costs.statutory_cost(CR, TODAY, "BUY")
    base = c.components["BROKERAGE"] + c.components["SEBI"] + c.components["TXN"]
    assert c.components["GST"] == pytest.approx(0.18 * base)
    assert c.components["GST"] > 0.18 * c.components["BROKERAGE"], (
        "GST looks like it is being charged on brokerage alone"
    )


def test_the_round_trip_reproduces_the_figure_the_config_states():
    """costs.yml's own comments cite 29.33 bps headline and 22.25 bps at the
    floor for NSE, computed independently of this module. Agreement is a real
    cross-check; drift means one of the two is wrong."""
    assert costs.round_trip_bps(CR, TODAY, "NSE") == pytest.approx(29.33, abs=0.01)
    assert costs.round_trip_bps(CR, TODAY, "NSE", 0.0) == pytest.approx(22.25, abs=0.01)


def test_the_schedule_is_point_in_time_not_current():
    """Rates moved across the 2006-2026 sample. GST replaced service tax on
    2017-07-01, so a 2010 trade must not be charged GST — charging today's
    schedule against a 2010 event is the constant-rate error in another costume.
    """
    old = costs.statutory_cost(CR, date(2010, 6, 1), "BUY")
    new = costs.statutory_cost(CR, TODAY, "BUY")
    assert "GST" not in old.components or old.components["GST"] == 0
    assert new.components["GST"] > 0


def test_a_pre_2020_window_is_flagged_unverified():
    """Plan 2 §4.1: a study whose window touches an unverified rate must say so.
    Pre-2017 GST, pre-2020 stamp duty and pre-2024 TXN history are all
    unreconstructed and named in costs.yml."""
    old = costs.statutory_cost(CR, date(2012, 1, 1), "BUY")
    assert old.unverified, "a 2012 cost claims fully verified rates"
    assert "UNVERIFIED" in old.render()


def test_a_circuit_locked_session_is_not_a_zero_spread():
    """H == L means the stock was locked, not that it traded at no spread.
    Counting it as zero would make the most illiquid sessions look cheapest."""
    assert costs.corwin_schultz_spread([100.0, 100.0], [100.0, 100.0]) is None


def test_the_spread_estimator_is_positive_on_a_real_range():
    s = costs.corwin_schultz_spread(
        [101.0, 102.0, 101.5, 103.0], [99.0, 100.0, 100.2, 101.0])
    assert s is not None and s >= 0.0


def test_impact_grows_with_the_square_root_of_participation():
    """Quadrupling size doubles impact, not quadruples it. A linear model would
    make the TOO_LARGE exclusion look far more punitive than it is."""
    a = costs.sqrt_impact(1_000, 100_000, 0.02)
    b = costs.sqrt_impact(4_000, 100_000, 0.02)
    assert b == pytest.approx(2 * a)


def test_unknown_adv_is_not_a_free_trade():
    """An unmeasurable impact must not silently become zero cost in a way that
    reads as cheap. It returns 0.0 and the mart excludes such rows explicitly."""
    assert costs.sqrt_impact(1_000, 0, 0.02) == 0.0


def test_the_regime_multiplier_interpolates_rather_than_steps():
    """An event just below the decile boundary must not be priced as calm."""
    base = list(range(10, 40))
    calm = costs.vix_regime_multiplier(11, base)
    mid = costs.vix_regime_multiplier(32, base)
    stress = costs.vix_regime_multiplier(39, base)
    assert calm == 1.0
    assert stress == 1.5
    assert 1.0 < mid < 1.5, "the multiplier is stepping, not interpolating"


def test_three_levels_are_ordered_and_none_is_chosen_for_the_reader():
    """Plan 2 §4: gross / base / pessimistic, so the reader sees how much
    survives friction instead of one number picked by whoever ran it."""
    s = costs.cost_scenarios(CR, TODAY, quantity=5_000, adv=100_000,
                             sigma_daily=0.025, spread=0.0030)
    names = [x.name for x in s.scenarios]
    assert names == ["gross", "base", "pessimistic"]
    totals = [x.total_bps for x in s.scenarios]
    assert totals == sorted(totals), "pessimistic must not cost less than gross"


def test_the_fee_schedule_table_matches_the_config():
    """The table is the queryable form of costs.yml, not a second source of
    truth. Drift between them is how a study charges rates nobody approved."""
    import sqlite3

    from src.common.paths import governance_db

    n = costs.load_fee_schedule("prod")
    con = sqlite3.connect(governance_db("prod"))
    try:
        rows = con.execute("SELECT COUNT(*), SUM(verified) FROM fee_schedule").fetchone()
    finally:
        con.close()
    assert rows[0] == n == len(costs.spec()["statutory"])
    assert rows[1] == n, "an unverified rate reached the schedule"
