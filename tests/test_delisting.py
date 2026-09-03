"""Step 6.4 — the events that stop trading, and the two ways they were dropped.

Plan 2 §3.4: "MICCV2's silent drop of these events was worth roughly the whole
measured effect." confounds.py reproduced that drop on 2026-09-03. These tests
pin the reconciliation, the census, and the finding — that the delisting
assumption is NOT load-bearing on this population, which is the opposite of what
the plan predicted and worth failing loudly if it ever changes.
"""

from __future__ import annotations

import pytest

from src.research import confounds, delisting

pytestmark = pytest.mark.needs_data


@pytest.fixture(scope="module")
def run():
    return delisting.run("prod")


def test_the_census_accounts_for_every_event(run):
    """THE RECONCILIATION THAT CAUGHT THE FIRST IMPLEMENTATION.

    The first version joined events to prices before computing LEAD, so the
    window partitioned over event rows and returned 984 of 1,255. Nothing about
    the output looked wrong — the census printed, the tiers had plausible
    numbers. Only the total gave it away. That is why this is a test and not a
    comment.
    """
    census, _ = run
    assert sum(census.values()) == 1255
    assert set(census) == {"HORIZON", "CENSORED", "STOPPED", "NO_BENCHMARK"}


def test_horizon_count_matches_the_population_confounds_measures_on(run):
    """The two modules must agree on which events have an outcome. confounds.py
    computes its mean over the non-null exits; delisting.py counts them as
    HORIZON. A divergence means one of them is filtering differently."""
    census, tiers = run
    by_name = {t.name: t for t in tiers}
    assert census["HORIZON"] == by_name["ALL"].n_base


def test_censored_events_are_excluded_not_priced(run):
    """76 companies are still trading; their 12-month horizon simply runs past
    the data cutoff. Pricing them at a recovery factor would invent a delisting
    for a live company, and the error is not in the conservative direction.

    A further 3 events have no market leg at all — `mkt` is undefined inside
    252 sessions of the cutoff — and are excluded as NO_BENCHMARK rather than
    dropped. Those three were found BY this test, not before it.
    """
    census, tiers = run
    by_name = {t.name: t for t in tiers}
    assert census["CENSORED"] > 0
    # Only STOPPED events are added on top of the base population.
    assert by_name["ALL"].n_priced == census["STOPPED"]
    assert (by_name["ALL"].n_base + census["STOPPED"]
            + census["CENSORED"] + census["NO_BENCHMARK"]) == 1255
    # AND THE MEAN IS TAKEN OVER EXACTLY THOSE ROWS. The first version of this
    # test asserted only the counts above, so deleting the CENSORED filter
    # entirely left it green while 76 live companies were priced at -100%.
    # Watched failing on 2026-09-03; n_rf is what closed it.
    for t in tiers:
        assert t.n_rf == t.n_base + t.n_priced, (
            f"{t.name}: {t.n_rf} rows in the recovery mean but only "
            f"{t.n_base} + {t.n_priced} have an outcome")


def test_pricing_delistings_strengthens_the_effect_it_does_not_weaken_it(run):
    """0051 framed 6.4 as a test the sell effect might FAIL: 'the test is
    whether it holds once dying names are priced honestly'. The arithmetic runs
    the other way. A sell followed by a delisting priced at 0.0 is a -100%
    return, so the silent drop was UNDERSTATING the effect all along.

    This test exists so that framing cannot be repeated by accident.
    """
    _, tiers = run
    all_t = {t.name: t for t in tiers}["ALL"]
    assert all_t.effects[0.0] < all_t.effect_base


def test_the_recovery_factor_is_not_load_bearing_on_this_population(run):
    """Plan 2 §3.4 calls this "the single most consequential assumption in the
    study" — on 6,574 of 30,771 full-universe events. On EXPLORE sells at twelve
    months it is 34 of 1,255, and the three factors span under one point. The
    plan's claim is right about the study and wrong about this population, and
    reporting it as load-bearing here would be borrowed alarm.
    """
    _, tiers = run
    all_t = {t.name: t for t in tiers}["ALL"]
    span = abs(all_t.effects[0.50] - all_t.effects[0.0])
    assert span < 0.02, f"recovery factor now moves the headline {span:.2%}"


def test_pricing_widens_the_liquidity_gradient(run):
    """0051's central finding is that the effect is STRONGEST in the names you
    cannot trade. Delisting concentrates in those same names, so honest pricing
    should widen the gradient rather than close it. If this ever fails, the
    untradability reading needs revisiting — which is the point of pinning it.
    """
    _, tiers = run
    t = {x.name: x for x in tiers}
    base_span = abs(t["off500"].effect_base - t["top100"].effect_base)
    priced_span = abs(t["off500"].effects[0.0] - t["top100"].effects[0.0])
    assert priced_span > base_span
    # and the ordering itself is unchanged: off500 worst, top100 mildest
    assert t["off500"].effects[0.0] < t["top500_ex100"].effects[0.0] < t["top100"].effects[0.0]


def test_confounds_no_longer_reports_a_count_from_a_different_population():
    """COUNT(*) counts NULLs and avg() does not. The baseline read
    "n=1,255, raw effect -30.30%" where the mean was over 1,145 rows."""
    r = {x.confound_id: x for x in confounds.run("prod")}["_baseline"]
    assert "n=1,145" in r.headline
    assert any("110" in d and "no 252-session exit" in d for d in r.detail)


def test_the_merged_case_is_declared_rather_than_silently_priced():
    """Plan 2 §3.4 wants four cases. security_master.delisting_reason is UNKNOWN
    on every row, so MERGED and SUSPENDED cannot be separated from DELISTED. A
    merger priced at 0.0 overstates the effect; the module must say so."""
    import inspect

    src = inspect.getsource(delisting)
    assert "MERGED" in src and "SUSPENDED" in src
    assert "delisting_reason" in src
