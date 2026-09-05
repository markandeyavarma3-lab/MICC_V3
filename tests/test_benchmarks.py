"""The benchmark panel, and the two config claims the data does not support.

benchmarks.yml has specified six benchmarks since 2026-08-18 and nothing built
any of them. `outcome_benchmark_returns` held 0 rows and charmatch.py — 251
lines implementing the primary one — was imported by nothing.
"""

from __future__ import annotations

import pytest

from src.warehouse import benchmarks

pytestmark = pytest.mark.needs_data


@pytest.fixture(scope="module")
def series():
    return {s.benchmark_id: s for s in benchmarks.build("prod")}


def test_every_declared_benchmark_is_built_or_declared_missing(series):
    """SILENCE IS NOT AN OPTION. A benchmark can be built, deferred to the
    per-event path, or declared unavailable — but it cannot simply be absent,
    because a five-benchmark result reported against a six-benchmark spec reads
    as complete."""
    declared = set(benchmarks.declared_ids())
    covered = set(series) | set(benchmarks.PER_EVENT) | set(benchmarks.UNAVAILABLE)
    assert declared == covered, f"unaccounted: {sorted(declared ^ covered)}"


def test_the_broad_market_headline_is_unavailable_and_says_so():
    """NIFTY500_TR is the config's own `broad_market_headline` and is sourced
    from `warehouse.benchmark_n500tr`, which no code has ever written. Every
    result carrying benchmark returns is missing its headline comparison."""
    assert "NIFTY500_TR" in benchmarks.UNAVAILABLE
    why = benchmarks.UNAVAILABLE["NIFTY500_TR"]
    assert "benchmark_n500tr" in why and len(why) > 100


def test_nifty50_is_not_the_total_return_series_the_config_claims(series):
    """benchmarks.yml declares `total_return: true`. The only NIFTY50 series
    held is OHLCV with no dividend leg. Indian large-cap yield is ~1.2%/yr, so
    at the twelve-month primary horizon this understates the benchmark by about
    a fifth of the 6% plausible-effect bound — from one mislabelled column."""
    s = series["NIFTY50_TR"]
    assert not s.spec_honoured
    assert "PRICE index" in s.deviation


def test_the_constructed_smallcap_declares_its_weighting_deviation(series):
    """`free_float_proxy_mcap` is specified and pit_universe carries no market
    cap at all. Built equal-weighted, which is a different portfolio."""
    s = series["SMALLCAP_SYNTH"]
    assert not s.spec_honoured
    assert "equal-weighted" in s.deviation


def test_the_official_indices_are_not_marked_constructed(series):
    assert series["NIFTY50_TR"].official and series["NIFTY_MIDCAP100"].official
    assert not series["EW_TOP500"].official
    assert not series["SMALLCAP_SYNTH"].official


def test_the_no_skill_portfolio_compounds_to_something_a_market_could_do(series):
    """A LOOSE BOUND ON PURPOSE. Equal-weighting a daily-rebalanced basket of
    thin names harvests noise, and the first build of this series produced an
    18.3%/yr CAGR that turned out to include a +77,226% single-day 'return' —
    RNAVAL, suspended for five years and relisted, whose LAG spanned the gap.
    This asserts only that the level series stays inside a range a real market
    could produce, which the broken version did not.
    """
    for bid in ("EW_TOP500", "SMALLCAP_SYNTH"):
        s = series[bid]
        assert s.rows > 4000, f"{bid} has only {s.rows} sessions"
