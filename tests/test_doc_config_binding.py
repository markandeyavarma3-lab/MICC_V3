"""Documentation may not disagree with the configs. Drift breaks the build.

WHY THIS EXISTS.

MICCV2's README described a cron schedule that had drifted from the actual
crontab. That was catalogued as audit defect #1 — and then reproduced here within
a day: on 2026-08-17 the three plan documents were five commits and eighteen hours
behind the configs, describing horizons that had been dropped and a slice grid
that had been cut from 54,000 cells to six.

Documentation drift is not untidiness. A plan that describes a superseded design
is worse than no plan, because it is consulted and believed.

THE RULE. Configs are executable and are therefore the single source of truth.
Documents reference them. Where a document restates a number, that number is
bound here and a mismatch fails the suite.

WHAT THIS DELIBERATELY DOES NOT DO. It does not parse prose or attempt to verify
that documents are *complete*. It verifies that specific load-bearing values —
the ones where a stale figure would change what someone decides — appear in the
docs as the configs currently define them, and that superseded values do not.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from src.common.paths import CONFIGS, DOCS, ROOT

pytestmark = pytest.mark.unit

PLANS = DOCS / "plan"


def _cfg(name: str) -> dict:
    return yaml.safe_load((CONFIGS / name).read_text())


def _plan_text() -> str:
    return "\n".join(p.read_text() for p in sorted(PLANS.glob("PLAN_*.md")))


# --- the promised structure must exist ---------------------------------------


@pytest.mark.parametrize(
    "promised",
    [
        "docs/decisions",
        "docs/plan",
        "configs",
        "migrations",
        "src/common",
        "src/research",
    ],
)
def test_promised_directories_exist(promised):
    """Plan 1 §4.2 lists a repo layout. It was aspirational, not descriptive.

    `docs/decisions/` was promised on 2026-08-16 and did not exist until
    2026-08-17 — by which point sixteen decisions had been made and the only
    record of them was commit messages and chat prose.
    """
    assert (ROOT / promised).is_dir(), f"{promised} is promised in Plan 1 §4.2"


def test_every_decision_record_is_in_the_index():
    """An unindexed decision record is one nobody will find."""
    index = (DOCS / "decisions" / "README.md").read_text()
    records = sorted(p.name for p in (DOCS / "decisions").glob("[0-9][0-9][0-9][0-9]-*.md"))
    assert records, "no decision records found"
    missing = [r for r in records if r not in index]
    assert not missing, f"decision records absent from the index: {missing}"


def test_decision_records_state_what_would_reverse_them():
    """The field that stops a decision from calcifying.

    Six months on, nobody remembers whether a constraint was load-bearing or
    arbitrary, so everyone treats it as load-bearing. Naming the reversal
    condition up front means a decision can be revisited on evidence.
    """
    for rec in sorted((DOCS / "decisions").glob("[0-9][0-9][0-9][0-9]-*.md")):
        text = rec.read_text()
        assert "## What would reverse this" in text, f"{rec.name} has no reversal condition"
        assert "## Cost accepted" in text, f"{rec.name} lists no cost"
        assert re.search(r"^\*\*Decided by:\*\*\s*\S", text, re.M), (
            f"{rec.name} has no attribution — an owner's judgement call and a "
            f"default I picked while building are different things"
        )


# --- config internal consistency ---------------------------------------------


def test_split_ratios_agree_between_the_two_places_they_appear():
    cfg = _cfg("split.yml")
    for name, (lo, hi) in cfg["assignment"]["ranges"].items():
        implied = (hi - lo) / cfg["assignment"]["buckets"]
        assert cfg["strata"][name]["fraction"] == pytest.approx(implied)


def test_research_yml_points_at_the_split_spec_rather_than_restating_it():
    """One source of truth. research.yml must reference, never duplicate."""
    raw = (CONFIGS / "research.yml").read_text()
    cfg = _cfg("research.yml")
    assert cfg["split_spec"] == "configs/split.yml"
    assert (CONFIGS / "split.yml").exists()
    # If the ratios were copied here they would drift the moment split.yml moved.
    assert "EXPLORE:" not in raw, "research.yml is restating the split, not referencing it"


def test_kill_criterion_is_complete_enough_to_actually_fire():
    """A kill criterion missing a date cannot trigger, and so is decoration."""
    k = _cfg("research.yml")["project_kill_criterion"]
    assert k["deadline"] == "2027-02-28"
    assert k["checkpoint"] == "2026-11-30"
    assert k["verdict_path"].endswith(".md")
    assert k["checkpoint"] < k["deadline"], "the checkpoint must precede the deadline"
    # REVISED 2026-08-18. It read "3 of 4 studies", which cannot evaluate when the
    # critical path guarantees only ONE study (PLAN_3 §3.2). The threshold now
    # applies to studies ACTUALLY RUN.
    assert 0 < k["fail_fraction_threshold"] <= 1.0
    assert k["min_studies_before_fraction_applies"] >= 1
    assert k["primary_trigger"] == "checkpoint", (
        "the checkpoint must be the primary trigger: it is the only condition "
        "that fires on the critical path alone"
    )


def test_the_schedule_is_a_critical_path_not_a_bare_sequence():
    """The old schedule opened "No deadline was set (Q4)" — false since decision
    0010 — and totalled 22 weeks while omitting Phases 6S, 6R and 0.6. It left
    1.7 weeks of slack, so a 25% overrun missed by five weeks."""
    text = (PLANS / "PLAN_3_EXECUTION.md").read_text()
    sched = text.split("## 3. Schedule")[1].split("## 4.")[0]
    # The old line "No deadline was set (Q4)" is QUOTED in 3.1 as the thing being
    # corrected, so its mere presence is not the fault. What matters is that the
    # deadline is now stated as fact somewhere in the schedule.
    assert "2027-02-28" in sched, "the schedule does not state the deadline"
    assert re.search(r"has been false|no longer|superseded|corrected", sched, re.I), (
        "the schedule quotes its old no-deadline premise without retracting it"
    )
    assert re.search(r"critical path", sched, re.I), "no critical path defined"
    assert re.search(r"cut first", sched, re.I), (
        "no cut order — deciding what to drop under deadline pressure is how "
        "the wrong thing gets dropped"
    )
    assert "2026-11-23" in sched, "the critical path has no landing date"


# --- docs must not contradict the configs ------------------------------------


def test_plan_docs_do_not_advertise_dropped_horizons():
    """The 8/10/15/18/24-month horizons were dropped on 2026-08-16 (decision 0004).

    At 12 months MDE is already 7.38% against a plausible bound of 0.50%, so
    longer horizons are strictly more hopeless and each spends correction budget
    to guarantee an UNDERPOWERED row. A plan still listing them sends the reader
    to run tests that cannot conclude anything.

    A dropped horizon mentioned in passing is fine and often necessary — Plan 2
    §6.5 has to explain why purging a 24-month label exceeds a 20.6-month CPCV
    group. What is not fine is a LIST presented as the live grid. So this looks
    for enumerations, not for the numbers themselves.
    """
    cfg = _cfg("research.yml")
    live = set(cfg["horizons_months"])
    dropped = {8, 10, 15, 18, 24} - live

    # Three or more numbers separated by / or , and followed by "month(s)".
    enumeration = re.compile(
        r"((?:\*{0,2}\d{1,2}\*{0,2}\s*[/,]\s*){2,}\*{0,2}\d{1,2}\*{0,2})\s*months?\b", re.I
    )
    offenders = []
    for path in sorted(PLANS.glob("PLAN_*.md")):
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            for match in enumeration.finditer(line):
                listed = {int(n) for n in re.findall(r"\d{1,2}", match.group(1))}
                if listed & dropped:
                    offenders.append(f"{path.name}:{lineno}  {line.strip()[:90]}")

    assert not offenders, (
        "plan docs present a horizon list containing dropped values "
        f"{sorted(listed & dropped)}; the live grid is {cfg['horizons_sessions']} "
        f"sessions + {sorted(live)} months (docs/decisions/0004)\n  "
        + "\n  ".join(offenders)
    )


def test_plan_docs_do_not_still_describe_the_54000_cell_grid():
    """Room 2B was cut to six slices on 2026-08-16 (decision 0005).

    54,000 cells against 77,471 events is 1.43 events per cell. The grid was
    finer than the data.
    """
    text = _plan_text()
    assert not re.search(r"54,?000", text), (
        "plan docs still describe the crossed 54,000-cell Room 2B grid; it was "
        "replaced by six pre-declared slices (docs/decisions/0005)"
    )


def test_plan_docs_carry_the_current_plausible_effect_bound():
    """This number governs every UNDERPOWERED verdict in the project.

    It sat in a config for a day looking like a measurement before anyone asked
    where it came from (decision 0011). If the docs quote a different one, the
    reader will believe a different power analysis than the one that runs.
    """
    bound = _cfg("research.yml")["power"]["plausible_effect_bound_monthly"]
    assert bound == 0.005
    text = _plan_text()
    if re.search(r"plausible.{0,40}bound", text, re.I | re.S):
        assert re.search(r"0\.5\s*%|0\.005", text), (
            "plan docs mention a plausible bound but not the live value of 0.5%/month"
        )


def test_portfolio_gate_is_mandatory_in_config_and_described_in_the_plan():
    """The gate Finding 001 forced into existence (decision 0003).

    Without it exp_001 would have been recorded as a PASS and shipped as a
    finding: event effect −0.805% at t −3.93, portfolio effect −0.022%/yr at
    t −0.25.
    """
    assert _cfg("research.yml")["portfolio_gate"]["required_for_every_study"] is True
    assert re.search(r"portfolio.{0,10}gate", _plan_text(), re.I), (
        "the plan documents never mention the portfolio gate, which is mandatory "
        "for every study"
    )


def test_split_is_described_in_the_plan_at_all():
    """The partition changes what every study is allowed to do. Silence is drift."""
    assert re.search(r"\bCONFIRM\b|confirmation (set|stratum|data)", _plan_text()), (
        "plan documents do not describe the EXPLORE/SELECT/CONFIRM partition "
        "(configs/split.yml, docs/decisions/0008)"
    )


# --- the two-track configs must not drift apart (added 2026-08-18) -----------
#
# These exist because three gaps between Track D and Track S went unnoticed until
# a manual check: scan.yml referenced no split, no confound applied to a scan,
# and two config files disagreed about the trial counter in a way that would have
# destroyed Track D. Nothing bound them together, so nothing caught it.


class TestTwoTrackConsistency:
    def test_scan_references_the_split_and_family_specs(self):
        """scan.yml must POINT AT its partition, not restate or omit it."""
        cfg = _cfg("scan.yml")
        assert cfg["split_spec"] == "configs/split.yml#scan"
        assert cfg["trial_families"] == "configs/trials.yml"

    def test_the_scan_partition_exists_where_scan_yml_says_it_is(self):
        assert "scan" in _cfg("split.yml"), "scan.yml points at a section that is absent"

    def test_research_yml_no_longer_claims_a_single_global_counter(self):
        """The literal contradiction that would have killed Track D.

        research.yml said the counter applied to EVERYTHING; scan.yml was silent.
        """
        tc = _cfg("research.yml")["trial_counter"]
        assert tc["superseded_by"] == "configs/trials.yml"
        assert tc["family_for_this_track"] == "TRACK_D_DEALS"

    def test_every_family_referenced_anywhere_actually_exists(self):
        known = {f["id"] for f in _cfg("trials.yml")["families"]}
        scan = _cfg("split.yml")["scan"]
        for key in ("family_calendar", "family_signals", "family_procedure"):
            assert scan[key] in known, f"{key}={scan[key]} is not a declared family"
        assert _cfg("research.yml")["trial_counter"]["family_for_this_track"] in known

    def test_track_d_carried_count_agrees_between_the_two_files(self):
        """68 appears in research.yml and 171 in trials.yml; the difference is the
        ~100-cell exploratory episode plus logged rows. If they drift the bar is
        computed from one number and justified by another."""
        assert _cfg("research.yml")["trial_counter"]["carried_from_predecessor"] == 68
        d = next(f for f in _cfg("trials.yml")["families"] if f["id"] == "TRACK_D_DEALS")
        assert d["carried"] == 171

    def test_the_procedure_exemption_is_explicit_not_implied(self):
        """A family whose width does not charge is a large claim. It must say so
        in words, not be inferred from a missing field."""
        p = next(f for f in _cfg("trials.yml")["families"] if f["id"] == "TRACK_S_PROCEDURE")
        assert p["width_does_not_charge"] is True
        assert p["fixed_family_size"] > 0
        assert p["selection_happens_within"] is False

    def test_the_calendar_family_declares_the_predecessors_prior_search(self):
        c = next(f for f in _cfg("trials.yml")["families"] if f["id"] == "TRACK_S_CALENDAR")
        assert c["prior_external_search"] == 31_893_556

    def test_every_study_kind_has_at_least_one_blocking_confound(self):
        """A kind with no blocking confound is a kind outside the checklist —
        which is what `scan` was until 2026-08-18."""
        from src.research.design import required_confounds

        for kind in ("event_study", "portfolio", "seasonality", "scan"):
            assert required_confounds(kind), f"{kind} has no blocking confounds"

    def test_plan_4_describes_the_family_scheme(self):
        text = (PLANS / "PLAN_4_SCAN.md").read_text()
        assert "TRACK_S_" in text, "Plan 4 does not mention the trial families"
        assert re.search(r"time split|temporal", text, re.I), \
            "Plan 4 does not describe the Track S partition"


# --- the report may not misstate the system it describes ---------------------


def test_report_states_the_real_test_count():
    """Caught 2026-08-18: the report's conclusion claimed 146 tests when the
    suite had grown to 204.

    Every other number in the report is bound to a repository or a measurement.
    This one was bound to nothing, so it drifted the moment the suite grew — the
    same silent-drift failure the report itself catalogues as MICCV2's audit
    defect #1.

    Historical statements ("why they survived 146 tests") are correct as history
    and are deliberately not matched: this checks only the present-tense claim.
    """
    import os
    import subprocess
    import sys

    report = (DOCS / "report" / "PROJECT_REPORT.md").read_text()
    claim = re.search(r"discipline framework with ([\d,]+) tests", report)
    assert claim, "the report no longer states its test count in the expected form"
    stated = int(claim.group(1).replace(",", ""))

    # sys.executable, not "python": PATH here resolves to a DIFFERENT repo's venv.
    out = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "--collect-only", "-q"],
        cwd=ROOT, capture_output=True, text=True,
        env={**os.environ, "RESEARCH_ENV": "dev"},
    ).stdout
    # `--collect-only -q` prints "path/to/test_x.py: N" per file, not a total.
    per_file = re.findall(r"^\S+\.py: (\d+)$", out, re.M)
    assert per_file, f"could not parse collection output:\n{out[-400:]}"
    actual = sum(int(n) for n in per_file)

    assert stated == actual, (
        f"the report claims {stated} tests; the suite has {actual}. "
        f"A report that misstates the system it describes is the drift this "
        f"project exists to prevent."
    )


def test_every_plan_pdf_is_newer_than_its_source():
    """Caught 2026-08-18: three plan PDFs were a day stale and PLAN_4 had none.

    The report was rebuilt after every edit and the plans were not, so anyone
    handed a plan PDF got the superseded design — the exact failure this file
    exists to prevent, committed in the artefacts the plans are delivered as.

    Compounding it, `build_report.py` wrote to a hardcoded output directory, so
    rebuilding the plans dropped fresh PDFs into docs/report/ while the stale
    copies sat in docs/plan/pdf/. The build reported GREEN and the stale files
    were still what anyone would read.
    """
    stale = []
    for md in sorted(PLANS.glob("PLAN_*.md")):
        pdf = PLANS / "pdf" / f"{md.stem}.pdf"
        if not pdf.exists():
            stale.append(f"{md.stem}: PDF MISSING")
        elif pdf.stat().st_mtime < md.stat().st_mtime:
            stale.append(f"{md.stem}: PDF older than source")
    assert not stale, (
        "stale plan PDFs — rebuild with scripts/build_report.py --src <file>:\n  "
        + "\n  ".join(stale)
    )


def test_plan_3_covers_the_scan_track():
    """PLAN_3 is the EXECUTION plan. Until 2026-08-18 it had zero mentions of
    Track S, so the phase plan sequenced only half the project."""
    text = (PLANS / "PLAN_3_EXECUTION.md").read_text()
    assert "Phase 6S" in text, "PLAN_3 has no phase for the scan track"
    assert "TRACK_S" in text or "trial famil" in text.lower()


class TestExecutionPlanIsComplete:
    """Every commitment that creates work must appear in the execution plan.

    Found 2026-08-18: five did not. The worst was the portfolio gate — the
    Definition of Done asked only what happened after each event, which is the
    gate `exp_001` passed before failing on the book. A project whose definition
    of "finished" omits the portfolio gate can ship a correct event study as a
    tradable finding.
    """

    @staticmethod
    def _plan3() -> str:
        return (PLANS / "PLAN_3_EXECUTION.md").read_text()

    def test_definition_of_done_requires_the_portfolio_gate(self):
        dod = self._plan3().split("## 7. Definition of done")[1]
        assert re.search(r"constructed book|portfolio gate", dod, re.I), (
            "the Definition of Done does not require a portfolio test — this is "
            "the omission that would have let exp_001 ship as a PASS"
        )

    def test_definition_of_done_does_not_quote_the_dropped_horizon_count(self):
        """It said '9 horizons' long after decision 0004 cut the grid."""
        dod = self._plan3().split("## 7. Definition of done")[1]
        assert "9 horizons" not in dod

    def test_the_plan_says_when_the_project_stops(self):
        """Decision 0010 lived in research.yml and in no phase, so the execution
        plan had no way to end."""
        text = self._plan3()
        assert "2027-02-28" in text, "no deadline in the execution plan"
        assert "FINAL_VERDICT" in text, "no abandonment deliverable"
        assert "2026-11-30" in text, "no mid-point checkpoint"

    def test_blocking_owner_decisions_have_a_phase(self):
        """0018 blocks every session-horizon study and appeared nowhere."""
        assert "0018" in self._plan3()

    def test_exp001_rerun_has_a_phase(self):
        """Decision 0013 committed to it; no step existed."""
        text = self._plan3()
        assert "Phase 6R" in text
        assert "PRIOR_EXPOSURE" in text

    def test_the_serial_correction_is_required_somewhere(self):
        assert re.search(r"serial correction", self._plan3(), re.I)

    def test_every_phase_has_a_gate(self):
        """A phase without a gate is a phase that cannot fail."""
        text = self._plan3()
        # Capture the WHOLE heading: "Phase 6S dependencies…" and "Phase 9 —
        # Deferred" are not gated phases, and matching only the number made both
        # look like violations.
        phases = re.findall(r"^### (Phase [^\n]*)\n(.*?)(?=^### |\Z)",
                            text, re.M | re.S)
        assert phases, "no phases parsed"
        exempt = ("COMPLETE", "Deferred", "dependencies")
        ungated = [
            heading.split("—")[0].strip() for heading, body in phases
            if not any(e.lower() in heading.lower() for e in exempt)
            and not re.search(r"\*\*Gate", body)
        ]
        assert not ungated, f"phases with no gate: {ungated}"
