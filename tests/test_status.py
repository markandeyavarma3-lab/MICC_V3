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

from src.common.paths import ROOT

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
    """BLOCKED must stay a real grade even when nothing currently holds it.

    1.10 held it for eight days from a hand-written string naming an obstacle
    that had already been removed, so it is no longer the example. The machinery
    is what is tested; the claim is what was wrong.
    """
    s = status.Step("X.0", "test", "a step waiting on the outside world",
                    built=lambda c: True, blocked="a measured external obstacle")
    assert s.level(status.Ctx()) == "BLOCKED", "blocked must outrank a passing built()"


@pytest.mark.unit
def test_risk_8_is_derived_from_the_destination_not_asserted(tmp_path, monkeypatch):
    """The defect: 1.10's status was a string, so it survived the thing it
    described being fixed. It now reads the folder backup.sh writes to."""
    s = next(x for x in status.steps() if x.id == "1.10")
    assert not s.blocked, "1.10 must not carry a hand-written status again"

    monkeypatch.setenv("BACKUP_DEST", str(tmp_path))  # exists, holds no backup
    assert s.level(status.Ctx()) == "BUILT", (
        "an empty destination must grade below WIRED — that was the real state "
        "for eight days while the page said BLOCKED for the wrong reason"
    )
    assert "NO BACKUP" in s.note_for(status.Ctx())


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


@pytest.mark.unit
def test_every_pipeline_stage_runs_in_the_daily_job():
    """A stage that only runs by hand is a stage whose failure is silent.

    0048: `src.ingest.land` was not in collect_daily.sh. It broke on 2026-09-01
    with an unhandled _csv.Error and nothing noticed for a day — the collectors
    reported success, health stayed green, the gate stayed 20/20, and no deal
    reached the mart after 08-28. An external audit found it.

    This asserts the whole chain is scheduled. A new module added to the flow
    must be added here too, which is the point: forgetting is the failure mode.
    """
    script = (ROOT / "scripts" / "collect_daily.sh").read_text()
    required = [
        "src.archive.stopgap",      # deals: raw bytes
        "src.archive.prices",       # prices: raw bytes
        "src.ingest.bhavcopy",      # prices -> parquet
        "src.archive.corporate_actions",
        "src.ingest.corp_actions",
        "src.archive.insider",
        "src.ingest.insider",
        "src.ingest.land",          # deals -> institutional_deals_raw
        "src.identity.master",      # -> security_master, deal_resolution
        "src.mart.clean",           # -> institutional_deals_clean
        "src.monitor.health",
    ]
    missing = [m for m in required if m not in script]
    assert not missing, (
        f"{len(missing)} pipeline stage(s) are not scheduled and would fail "
        f"silently: {missing}"
    )
    assert "spine" in script, "the spine rebuild is not scheduled"
    assert "backup.sh" in script, "the backup is not scheduled"


@pytest.mark.unit
def test_status_predicates_cannot_be_satisfied_by_their_own_descriptions():
    """0048's worst finding. Fourteen predicates read
    `"romano" in "".join(c.src_text.values())`, and src_text INCLUDES status.py
    — so a step's own description satisfied its own check.

    Ctx.mentions() now excludes this file, and every unbuilt-phase predicate was
    moved to Ctx.provides(), which imports the module and looks the symbol up.
    A word in a docstring cannot satisfy that.
    """
    src = (ROOT / "src" / "monitor" / "status.py").read_text()
    assert 'join(c.src_text.values())' not in src, (
        "a predicate is scanning all source text again, including this file"
    )
    body = src.split("def steps()")[1]
    assert "c.mentions(" not in body, (
        "a step predicate is back to matching text rather than importing a symbol"
    )


@pytest.mark.unit
def test_provides_reports_absent_symbols_as_absent():
    """The grader must be able to say no. Romano-Wolf is specified by Plan 3
    step 6.8 and multiplicity.py implements Sidak and a Gumbel-limit max-null-t
    — not Romano-Wolf under any name."""
    c = status.Ctx()
    assert c.provides("src.research.power", "serial_inflation")
    assert not c.provides("src.research.multiplicity", "romano_wolf")
    assert not c.provides("src.research.seasonality", "hansen_spa")
    assert not c.provides("src.does.not.exist", "anything")


@pytest.mark.unit
def test_the_daily_job_propagates_failure():
    """A scheduler that cannot tell failure from success is not monitoring.

    Until 2026-09-03 collect_daily.sh echoed every stage's exit code into a log
    nobody reads and returned 0 unconditionally. launchd and cron saw a clean
    run whether the pipeline worked or died — the same green-over-broken shape
    as the retired-endpoint envelope and the swallowed XBRL fetch. The signal
    existed and nothing carried it.
    """
    script = (ROOT / "scripts" / "collect_daily.sh").read_text()
    assert 'exit "$RC"' in script, "the daily job does not exit with a status"
    assert "note()" in script, "no per-stage status recorder"
    assert 'echo "$1=$2"' in script
    stages = script.count("\n  note ")
    assert stages >= 11, f"only {stages} stages report a status; expected >= 11"
    # the old pattern must not creep back
    assert 'echo "land=$?"' not in script, (
        "a stage is echoing its code instead of recording it through note()"
    )


@pytest.mark.unit
def test_the_insider_detail_fetch_reports_total_failure():
    """0048's lesson applied to the layer it missed.

    insider.py guards the INDEX against an empty envelope, then fetched each
    filing's XBRL detail under `except: continue` with no record. If the XBRL
    host moved, every fetch would fail, details_stored would read 0, and the
    entry would still be STORED with a healthy index count — green but empty,
    in the same file as the docstring warning about it.

    Verified by execution 2026-09-03: with the host broken, 264 filings indexed,
    0 stored, 264 failures, status FAILED.
    """
    import inspect

    from src.archive import insider

    src = inspect.getsource(insider.capture_window)
    assert "detail_failures" in src, "detail-fetch failures are not counted"
    assert "detail_failures and got == 0" in src, (
        "a run where every detail fetch failed is not marked FAILED"
    )
