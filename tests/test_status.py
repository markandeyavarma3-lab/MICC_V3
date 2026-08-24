"""The generated phase status, and the test that stops it going stale.

Phase 8's gate: "the generated status page is derived from repository and
database state, not written by hand, and reproduces the live figures. A
hand-written status drifts within a week."

It drifts faster than that. This project's report and README drifted on counts
four times in three days, and MICCV2's README drifted from its own crontab —
catalogued as audit defect #1 and then reproduced here.
"""

from __future__ import annotations

import pytest

from src.monitor import status

pytestmark = pytest.mark.data


def test_status_is_not_stale():
    """THE ENFORCEMENT. If the committed file disagrees with what the code
    derives, the suite fails and says so — a status nobody regenerates is worse
    than none, because it is read and believed."""
    assert status.STATUS_PATH.exists(), (
        "docs/STATUS.md is missing. Run: python -m src.monitor.status"
    )
    derived = status.render(status.evaluate())
    committed = status.STATUS_PATH.read_text()

    # The commit line changes on every commit and would make this fail
    # constantly for no information. Everything above it is the actual claim.
    strip = lambda s: s.split("Derived at commit")[0]  # noqa: E731
    assert strip(committed) == strip(derived), (
        "docs/STATUS.md is stale. Regenerate: python -m src.monitor.status"
    )


@pytest.mark.unit
def test_built_and_wired_are_different_grades():
    """The distinction this module exists for. Step 1.6 created fourteen tables
    and held zero rows; it must not be able to read as complete."""
    c = status.Ctx()
    built_only = status.Step("x", "p", "w", built=lambda _: True, wired=lambda _: False)
    assert built_only.level(c) == "BUILT"
    wired = status.Step("x", "p", "w", built=lambda _: True, wired=lambda _: True)
    assert wired.level(c) == "WIRED"


@pytest.mark.unit
def test_impossible_outranks_everything_and_carries_evidence():
    """2.4 and 2.5 are not pending work. Leaving them looking pending invites
    someone to re-attempt a route measured to return 503."""
    impossible = [s for s in status.steps() if s.impossible]
    assert {s.id for s in impossible} >= {"2.4", "2.5"}
    for s in impossible:
        assert "503" in s.impossible, f"{s.id} states no measured evidence"
        assert s.level(status.Ctx()) == "IMPOSSIBLE"


@pytest.mark.unit
def test_blocked_is_distinguished_from_unbuilt():
    """Risk 8's script exists and passes its own restore drill. Reporting it as
    unbuilt would misdescribe what is actually missing, which is a mounted
    destination."""
    s = next(x for x in status.steps() if x.id == "1.10")
    assert s.level(status.Ctx()) == "BLOCKED"
    assert s.blocked


@pytest.mark.unit
def test_every_step_can_be_graded_without_raising():
    """A status module that throws is a status nobody runs."""
    c = status.Ctx()
    for s in status.steps():
        assert s.level(c) in {
            "SPECIFIED", "BUILT", "WIRED", "VERIFIED", "IMPOSSIBLE", "BLOCKED"
        }


def test_the_three_steps_i_misreported_now_grade_honestly():
    """1.6, 1.9 and 2.1 were each reported complete while incomplete. Whatever
    their grade today, it must be DERIVED — so if the rows vanish, the grade
    drops on its own rather than waiting for someone to notice."""
    c = status.Ctx()
    by_id = {s.id: s for s in status.steps()}
    for sid in ("1.6", "1.9", "2.1"):
        s = by_id[sid]
        assert s.built is not None and s.wired is not None, (
            f"{sid} must check BOTH existence and consumption"
        )
        assert s.level(c) in {"WIRED", "VERIFIED"}, (
            f"{sid} grades {s.level(c)}; it holds rows and has consumers today"
        )
