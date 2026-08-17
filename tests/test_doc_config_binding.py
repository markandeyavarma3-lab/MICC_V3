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
    assert 0 < k["fail_count_threshold"] <= k["total_studies"]
    assert k["verdict_path"].endswith(".md")
    assert k["checkpoint"] < k["deadline"], "the checkpoint must precede the deadline"


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
