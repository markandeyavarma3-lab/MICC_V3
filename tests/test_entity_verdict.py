"""exp_002, the entity verdict study. Workstream 3 items 4-5.

The pass bar is the thing under test. A study whose code reads its own
registration loosely will report ALIVE on a failed bar, which is what the first
implementation here did.
"""

from __future__ import annotations

import pytest

from src.research import entity_verdict as E

pytestmark = pytest.mark.needs_data


@pytest.fixture(scope="module")
def v():
    return E.build()


def test_the_study_runs_against_the_registered_spec_hash():
    """The hash is pinned in the module. If the registration is edited, the two
    diverge and this fails — which is the point of freezing a spec."""
    import sqlite3

    from src.common.paths import governance_db

    con = sqlite3.connect(str(governance_db("prod")))
    try:
        row = con.execute(
            "SELECT spec_hash, test_count, status FROM experiment_registry "
            "WHERE experiment_id = ?", [E.EXPERIMENT_ID]).fetchone()
    finally:
        con.close()
    assert row, "exp_002 is not registered; the study must not run"
    assert row[0] == E.SPEC_HASH, "the registration changed after the study was written"
    assert row[1] == 24, "the declared family size moved"


def test_the_pass_bar_requires_the_passer_to_be_in_the_top_tier(v):
    """WATCHED FAILING 2026-09-11, and it mattered.

    The registration reads: "The TOP tier must (a) contain at least one entity
    passing BH-FDR 5% in-sample, AND (b) beat its benchmark net-of-costs."

    The first implementation tested `passed_fdr > 0 and top_beats > 0` — that
    ANY entity passed, not a TOP-tier one — and returned ALIVE. Both passers are
    in the BOTTOM tier on significantly negative formation excess, so the loose
    reading converted a failed bar into a finding.
    """
    in_top = [s for s in v.entities
              if s.tier == "TOP" and s.q_form is not None and s.q_form < E.FDR_ALPHA]
    assert v.alive == (bool(in_top) and v.tier_eval.get("TOP", -1) > 0), (
        "alive no longer equals the registered conjunction"
    )


def test_the_verdict_is_dead(v):
    """The recorded outcome. If this ever flips, something real changed and the
    memo needs rewriting rather than amending.

    RE-PINNED 2026-09-16. Under the substituted normal approximation this
    asserted passed_fdr == 2 and no TOP-tier passer: the bar failed on condition
    (a). Under the REGISTERED moving-block bootstrap (b2a6b77) four entities
    pass — all at the bootstrap floor p = 1/(B+1) on four or five deals — and
    one of them, SBI Life, is in TOP. Condition (a) is therefore MET, and the
    verdict now rests on condition (b): TOP is net-negative out-of-sample.
    Dead either way; the leg it died on is what changed.
    """
    assert not v.alive
    assert v.passed_fdr == 4
    in_top = sum(1 for s in v.entities
                 if s.tier == "TOP" and s.q_form is not None and s.q_form < E.FDR_ALPHA)
    assert in_top == 1, "condition (a) is met by exactly one TOP-tier passer"
    assert v.tier_eval["TOP"] < 0, "condition (b) fails: TOP loses net of costs OOS"


def test_the_formation_window_is_too_thin_to_tier_on(v):
    """The finding behind the finding. Half the tested entities have NO
    formation-period deal, so the registered walk-forward cannot be executed for
    them — the same shape as 0056: a study that cannot be run is a different
    verdict from one that ran and found nothing."""
    assert v.n_zero_formation >= 10
    thin = [s for s in v.entities if s.p_form is not None and s.n_form < 6]
    assert thin, "no thin-sample entities; the sparsity finding has changed"


def test_significance_on_a_handful_of_deals_is_reported_not_hidden(v):
    """Every FDR passer cleared 5% on four or five formation deals, and every one
    reports EXACTLY the bootstrap floor 1/(B+1). With that few values to
    resample the block bootstrap never produces a mean that crosses zero, so p
    saturates at its own resolution. Four identical floor p-values are not four
    discoveries; they are the bootstrap reporting it cannot describe a null.

    RE-PINNED 2026-09-16: the original asserted all passers were negative in
    formation, which was true of the two the substituted test produced. Under
    the registered bootstrap three of four are positive — and none of it
    predicts evaluation (rank IC -0.049).
    """
    passers = [s for s in v.entities
               if s.q_form is not None and s.q_form < E.FDR_ALPHA]
    assert len(passers) == 4
    assert max(s.n_form for s in passers) <= 5
    floor = 1 / (10_000 + 1)
    assert all(abs(s.p_form - floor) < 1e-6 for s in passers), (
        "a passer no longer sits at the bootstrap floor; the sample has grown"
    )
    assert abs(v.rank_ic) < 0.15, "formation ranking has started to predict evaluation"
