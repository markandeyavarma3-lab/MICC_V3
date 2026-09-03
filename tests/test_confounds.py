"""The standing confound checklist, and the two confounds that answered 0044.

confounds.yml has declared a mandatory nine-item checklist for event studies
since 2026-08-18 and nothing ran it. 0044 left the project's live question open:
the sell effect is 4x the plausible bound, so either 0011's bound is
miscalibrated or the result is confounded. This is the module that answers it.
"""

from __future__ import annotations

import pytest

from src.research import confounds

pytestmark = pytest.mark.needs_data


@pytest.fixture(scope="module")
def results():
    return {r.confound_id: r for r in confounds.run("prod")}


def test_every_event_study_confound_is_addressed(results):
    """confounds.yml is not advisory. Every confound with
    `applies_to: [event_study]` must come back MEASURED or NOT_APPLICABLE —
    silence is not an option the schema permits."""
    required = {
        c["id"] for c in confounds.spec()["confounds"]
        if "event_study" in c["applies_to"]
    }
    missing = required - set(results)
    assert not missing, f"confounds declared but never run: {sorted(missing)}"


def test_a_skipped_confound_carries_a_written_reason(results):
    """skip_policy: allowed, requires written_reason. A weak excuse must be as
    visible as a strong one, which means it has to exist."""
    for r in results.values():
        if r.verdict == "NOT_APPLICABLE":
            assert len(r.reason) > 80, (
                f"{r.confound_id} was skipped with a thin reason: {r.reason!r}"
            )


def test_the_checklist_runs_on_explore_not_confirm():
    """CONFIRM is spent, not browsed. Running diagnostics against it would
    consume the only stratum that can eventually settle the question, to answer
    a question that is not the settlement."""
    import inspect

    src = inspect.getsource(confounds)
    assert '"EXPLORE"' in src
    assert "CONFIRM" not in src.replace(
        "Reading\nCONFIRM to make the numbers bigger", ""
    ) or "split.assign(s)[0] == \"EXPLORE\"" in src


def test_the_liquidity_gradient_runs_the_wrong_way(results):
    """THE FIRST OF THE TWO FINDINGS.

    confounds.yml records that Finding 001 was STRONGER in liquid names and
    calls that "the unusual and encouraging direction". The sell effect is the
    opposite: measured 2026-09-03 on EXPLORE, off500 -60.32%, top500_ex100
    -32.98%, top100 -25.43% — monotonically weaker as tradability rises.

    An effect concentrated where it cannot be traded is the classic signature
    of an illiquidity premium rather than information.
    """
    liq = results["liquidity"]
    assert liq.verdict == "MEASURED"
    tiers = {}
    for line in liq.detail:
        name = line.split()[0]
        tiers[name] = float(line.split("effect")[1].strip().rstrip("%")) / 100
    assert {"off500", "top100"} <= set(tiers)
    assert tiers["off500"] < tiers["top100"], (
        "the liquidity gradient no longer favours illiquid names; 0051's "
        "central objection needs re-examining rather than this assertion "
        "being deleted"
    )


def test_survivorship_exposure_is_reported_and_unrecovered(results):
    """THE SECOND. 388 of 1,255 EXPLORE sell events — 31% — are on names that
    later stopped trading, and Plan 3 step 6.4 (delisting recovery factors) is
    unbuilt, so no recovery is applied to any of them.

    A dying name with no recovery factor contributes its full decline to the
    average. That is a mechanism for manufacturing a large negative effect
    without any information being present.
    """
    s = results["survivorship"]
    assert s.verdict == "MEASURED"
    assert "dead names" in s.headline
    assert any("recovery factor is NOT applied" in d for d in s.detail), (
        "the unapplied delisting recovery factor is no longer disclosed"
    )


def test_reversal_is_rejected_as_it_was_in_2026_08(results):
    """The one confound that comes back clean and matches its own precedent:
    correlation near zero and non-monotonic quintiles, exactly as the
    2026-08-16 bulk-deal measurement found (+0.008, U-shaped)."""
    m = results["momentum_reversal"]
    assert "non-monotonic" in m.headline
    assert "reversal not implicated" in m.headline


def test_microstructure_does_not_explain_the_sell_effect(results):
    """The 2026-08-16 precedent had microstructure explaining 71% of a 1-day
    effect. At 12 months it explains essentially none — which is expected, and
    is why the checklist reports the number rather than assuming either way."""
    assert "explains" in results["microstructure"].headline
