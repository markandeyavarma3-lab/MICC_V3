"""families.py — which search charges which counter, and what bar results face.

Implements configs/trials.yml. Read that file for the reasoning; this module is
the mechanism.

THE DEFECT THIS FIXES. `research.yml` declared the trial counter "applied to
EVERYTHING"; `scan.yml` was silent. Under a literal reading, running Track S once
would have pushed Track D's bar from |t| >= 3.71 to 7.28, retroactively failing
exp_001 and making every future deal study impossible. Two config files
contradicted each other and the contradiction would have surfaced only when
somebody ran a scan and watched the deal results evaporate.

THE FIX IS HIERARCHICAL, NOT SMALLER. Multiple-testing correction guards against
SELECTING the best of N comparable things, so the family is the set among which a
selection is actually made. A calendar cell and a bulk-deal event study are not
competing for one slot. But a claim that "the project found something" IS a
selection across everything, so that claim faces the project-level bar. Both are
computed and both are reported.

WHAT STOPS THIS BEING A LOOPHOLE. Not family size — declaration order. Families
are declared before the search and are immutable afterwards, and a result may
never be moved into a smaller family once seen. Choose the family late and every
result lands in a family of one, which is precisely the predecessor's failure:
it deflated challengers while exempting its own champion.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import yaml

from src.common.paths import CONFIGS
from src.research.multiplicity import Bar, bar


class FamilyError(RuntimeError):
    """An illegal use of the family scheme. Deliberately fatal."""


@lru_cache(maxsize=1)
def spec() -> dict:
    cfg = yaml.safe_load((CONFIGS / "trials.yml").read_text())
    ids = [f["id"] for f in cfg["families"]]
    if len(ids) != len(set(ids)):
        raise FamilyError(f"duplicate family ids in trials.yml: {ids}")
    return cfg


@lru_cache(maxsize=1)
def _by_id() -> dict[str, dict]:
    return {f["id"]: f for f in spec()["families"]}


def family_ids() -> tuple[str, ...]:
    return tuple(_by_id())


def get(family_id: str) -> dict:
    fam = _by_id().get(family_id)
    if fam is None:
        raise FamilyError(
            f"unknown family {family_id!r}. Known: {sorted(_by_id())}.\n"
            f"A new family requires a decision record first "
            f"(trials.yml rules.new_family_requires_decision_record)."
        )
    return fam


@dataclass(frozen=True, slots=True)
class Charge:
    """What a search costs, and to whom."""

    family_id: str
    trials_before: int
    trials_added: int
    trials_after: int
    dof: int | None
    bar: Bar

    def as_row(self) -> dict:
        return {
            "family_id": self.family_id,
            "trials_before": self.trials_before,
            "trials_added": self.trials_added,
            "trials_after": self.trials_after,
            "dof": self.dof,
            **{f"bar_{k}": v for k, v in self.bar.as_row().items()},
        }


def counter(family_id: str) -> int:
    """The family's standing trial count, including any prior external search.

    TRACK_S_CALENDAR carries 31,893,556 from the predecessor's completed scan.
    That space is not virgin, and a rebuild does not get to look at it as though
    for the first time.
    """
    fam = get(family_id)
    return int(fam.get("carried", 0)) + int(fam.get("prior_external_search", 0))


def charge(
    family_id: str,
    trials_added: int,
    dof: int | None = None,
) -> Charge:
    """Charge a search to its family and return the bar its results must clear.

    `trials_added` is the realised width of the search — never a hard-coded
    literal, always computed from the grid that actually ran.

    A family with `width_does_not_charge` (TRACK_S_PROCEDURE) ignores the width
    and uses its fixed family size. That exemption is what makes "scan wide to
    measure overfitting" legitimate: no selection among the scanned candidates is
    being reported, so the width is the instrument, not the hypothesis space. It
    holds only while the claim is about the procedure.
    """
    fam = get(family_id)
    if trials_added < 0:
        raise FamilyError(f"trials_added must be >= 0, got {trials_added}")

    before = counter(family_id)
    if fam.get("width_does_not_charge"):
        fixed = int(fam["fixed_family_size"])
        after = fixed
        added = 0
    else:
        added = trials_added
        after = before + added

    resolved_dof = dof if dof is not None else fam.get("typical_dof")
    return Charge(
        family_id=family_id,
        trials_before=before,
        trials_added=added,
        trials_after=after,
        dof=resolved_dof,
        bar=bar(max(1, after), dof=resolved_dof),
    )


def project_counter() -> int:
    """Total across every family — the count a project-level claim faces."""
    return sum(counter(fid) for fid in family_ids())


def project_bar(dof: int | None = None) -> Bar:
    """The bar for any claim of the form 'this project found X'.

    A within-family bar answers "is this the best of the deal studies". This
    answers "is this the best of everything we tried". Both are legitimate and
    they have different answers; publishing only the friendlier one is the abuse
    the predecessor committed.
    """
    return bar(max(1, project_counter()), dof=dof)


def report(family_id: str, trials_added: int, dof: int | None = None) -> str:
    """Both bars, side by side. trials.yml requires both be shown."""
    c = charge(family_id, trials_added, dof)
    p = project_bar(dof)
    return (
        f"family {c.family_id}: {c.trials_before:,} prior + {c.trials_added:,} "
        f"added = {c.trials_after:,}\n"
        f"  within-family bar  |t| >= {c.bar.required_t:.2f}\n"
        f"  project-level bar  |t| >= {p.required_t:.2f}  "
        f"({project_counter():,} trials across {len(family_ids())} families)\n"
        f"  A within-family result is not a project-level finding until it "
        f"clears the second."
    )


# --- persistence: the counters must actually accumulate ----------------------
#
# ADDED 2026-08-18, immediately after a check found that trials.yml declared the
# counters "monotonic, never reset" while NOTHING INCREMENTED THEM. charge() was
# a pure function and project_counter() summed static YAML, so a 31.9M-cell scan
# could have run without moving anything.
#
# That is exp_001's `trials_before` — computed, stored, printed once, never read
# — rebuilt one level up, inside the very file whose subject is that failure.


def _con(env: str | None = None):
    import sqlite3

    from src.common.migrate import migrate_sqlite
    from src.common.paths import governance_db

    db = governance_db(env)
    migrate_sqlite(db)
    con = sqlite3.connect(db)
    con.execute("PRAGMA foreign_keys = ON")
    return con


def persisted_counter(family_id: str, env: str | None = None) -> int:
    """The family's counter including everything actually charged to the ledger.

    The YAML `carried` value is the starting point; this is the live total.
    """
    get(family_id)  # validate
    con = _con(env)
    try:
        row = con.execute(
            "SELECT MAX(trials_after) FROM family_charge WHERE family_id = ?",
            (family_id,),
        ).fetchone()
    finally:
        con.close()
    return max(int(row[0] or 0), counter(family_id))


def commit_charge(
    family_id: str,
    trials_added: int,
    description: str,
    experiment_id: str | None = None,
    dof: int | None = None,
    env: str | None = None,
) -> Charge:
    """Charge a search AND write it to the append-only ledger.

    `trials_added` must be the realised width of the grid that ran, never a
    literal. Triggers refuse updates, deletes, and any total that would decrease.

    Families with `width_does_not_charge` (TRACK_S_PROCEDURE) still record the
    charge with trials_added = 0, because "we ran a 31.9M-cell scan and it cost
    this family nothing" is a claim that should be visible in the ledger rather
    than inferred from a config.
    """
    from datetime import UTC, datetime

    fam = get(family_id)
    if trials_added < 0:
        raise FamilyError(f"trials_added must be >= 0, got {trials_added}")
    if not description.strip():
        raise FamilyError("a charge must say what was searched")

    before = persisted_counter(family_id, env)
    if fam.get("width_does_not_charge"):
        added, after = 0, int(fam["fixed_family_size"])
    else:
        added, after = trials_added, before + trials_added

    resolved_dof = dof if dof is not None else fam.get("typical_dof")
    b = bar(max(1, after), dof=resolved_dof)

    con = _con(env)
    try:
        con.execute(
            "INSERT INTO family_charge (family_id, trials_added, trials_after, dof,"
            " required_t, experiment_id, description, recorded_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (family_id, added, max(after, before), resolved_dof, b.required_t,
             experiment_id, description, datetime.now(UTC).isoformat()),
        )
        con.commit()
    finally:
        con.close()

    return Charge(family_id, before, added, max(after, before), resolved_dof, b)


def persisted_project_counter(env: str | None = None) -> int:
    return sum(persisted_counter(f, env) for f in family_ids())
