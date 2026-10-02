"""The Track S panel against the real warehouse. The unit tests build a
synthetic Panel and never touch the loader; on 2026-10-02 the loader's first
real run failed twice (an ambiguous `date` column, rebalance dates read as
text) and the synthetic tests stayed green. These run the loader itself."""

from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from src.common.paths import warehouse_dir

needs_spine = pytest.mark.skipif(
    not any((warehouse_dir("prod") / "price_spine_adj").glob("**/*.parquet")),
    reason="adjusted spine not built",
)


@pytest.fixture(scope="module")
def p():
    from src.scan import panel
    return panel.load("prod", start=date(2015, 6, 1), end=date(2015, 12, 31))


@needs_spine
def test_the_real_panel_loads_inside_the_requested_window(p):
    assert p.dates[0] >= date(2015, 6, 1) and p.dates[-1] <= date(2015, 12, 31)
    assert len(p.ids) == len(set(p.ids.tolist()))
    assert p.close.shape == (len(p.dates), len(p.ids))


@needs_spine
def test_the_point_in_time_universe_is_about_five_hundred_names(p):
    per_day = p.universe.sum(axis=1)
    assert per_day.min() >= 400 and per_day.max() <= 500


@needs_spine
def test_deals_load_and_are_never_negative(p):
    assert (p.deal_buy >= 0).all() and (p.deal_sell >= 0).all()
    assert p.deal_buy.sum() > 0 and p.deal_sell.sum() > 0
    assert not np.isnan(p.close[p.universe]).all()
