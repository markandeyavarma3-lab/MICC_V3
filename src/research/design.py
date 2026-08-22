"""design.py — what a study must establish before it is allowed to exist.

Three rules, each traceable to a specific way this project has already gone
wrong. None of them is a style preference.

RULE 1 — NOTHING ENTERS A DESIGN WITHOUT A COMPUTED MDE BESIDE IT.

The horizon grid came from a plan template. The power arithmetic came afterwards
and contradicted it: at 12 months MDE is 7.38% against a plausible bound of
0.50%, and the "+7.80% signal" sat directly on its own detection floor. The Room
2B grid was 54,000 cells against 77,471 events — 1.43 events per cell. Both
defects have the same shape: a design written from a template, then measured.

Reversing the order is the entire fix. If a horizon or slice cannot detect an
effect inside the plausible range, it does not go in — it is not "robustness",
it is a guaranteed UNDERPOWERED row that spends correction budget to say nothing.

RULE 2 — A MECHANISM, AND A SIDE-PREDICTION THAT COULD FAIL.

"Measure X and see" is not a hypothesis, it is a query. A mechanism generates
predictions BEYOND the headline effect, and those extra predictions are what
noise cannot fake. If institutions are informed, the effect should scale with
deal size relative to ADV. Noise does not produce a monotone dose-response.

One dose-response curve is worth more than three significant t-statistics,
because there is no way to arrive at it by looking harder.

RULE 3 — THE CONFOUND CHECKLIST IS RUN, NOT REMEMBERED.

The open-to-close microstructure confound ate 71% of the 1-day effect and was
caught because it occurred to me that afternoon. The quality of a result must not
depend on what the analyst happened to think of. configs/confounds.yml is the
standing list; a confound may be declared inapplicable in writing, but not
skipped in silence.
"""

from __future__ import annotations

import re

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Literal

import yaml

from src.common.paths import CONFIGS
from src.research.multiplicity import bar

StudyKind = Literal["event_study", "portfolio", "seasonality", "scan"]
Applicability = Literal["REQUIRED", "NOT_APPLICABLE"]


class DesignRejected(ValueError):
    """The design cannot proceed to registration.

    Raised before any data is touched. That timing is the point: a design defect
    caught here costs an afternoon, and the same defect caught after the fact
    costs the credibility of every number in the study.
    """


@lru_cache(maxsize=1)
def confound_spec() -> dict:
    return yaml.safe_load((CONFIGS / "confounds.yml").read_text())


@lru_cache(maxsize=1)
def research_spec() -> dict:
    return yaml.safe_load((CONFIGS / "research.yml").read_text())


#: Horizon labels whose natural unit is a month.
_MONTHLY = re.compile(r"^(\d+(?:\.\d+)?)\s*(?:m|mo|month|months)$", re.I)
#: Horizon labels expressed in trading sessions — the primary grid (decision 0004).
_SESSIONS = re.compile(r"^(\d+(?:\.\d+)?)\s*(?:s|sess|session|sessions)$", re.I)


def _is_monthly_horizon(label: str) -> bool:
    return bool(_MONTHLY.match(str(label).strip()))


def horizon_in_months(label: str) -> float | None:
    """The horizon expressed in months, or None if the label declares no unit.

    Sessions are converted with `power.sessions_per_month` from research.yml —
    a convention (21) rather than a measurement, which is why it lives in config
    where it can be challenged rather than in this function.

    A label this cannot parse ("ic_5s", "event") returns None, and the caller
    refuses it. Guessing a unit is how a 1-session MDE came to be judged against
    a per-month bound in the first place.
    """
    s = str(label).strip()
    if m := _MONTHLY.match(s):
        return float(m.group(1))
    if m := _SESSIONS.match(s):
        return float(m.group(1)) / float(research_spec()["power"]["sessions_per_month"])
    return None


def required_confounds(kind: StudyKind) -> tuple[str, ...]:
    return tuple(
        c["id"]
        for c in confound_spec()["confounds"]
        if kind in c["applies_to"] and c.get("blocking", False)
    )


@dataclass(frozen=True, slots=True)
class HorizonPower:
    """One horizon and what it can actually see. Both, or neither."""

    horizon: str
    n_periods: int
    mde: float
    #: None means "not yet computed", which is itself a rejection reason. A design
    #: does not get to omit the number by leaving it blank.
    plausible_bound: float | None = None

    @property
    def resolved_bound(self) -> float:
        """The plausible bound this horizon is actually judged against.

        HISTORY. Until 2026-08-18 this silently used
        `plausible_effect_bound_monthly` FOR EVERY HORIZON including
        single-session ones — a unit error that made short horizons look powered.
        The module then REFUSED any non-monthly horizon rather than guess, which
        was correct while decision 0018 was open but blocked all Track D
        registration, since every primary horizon is in sessions (0004).

        DECISION 0028, 2026-08-21: the owner chose the RATE VIEW. The bound
        accrues with time, so it scales:

            bound(h) = plausible_effect_bound_monthly * h_in_months

        An explicit `plausible_bound` always wins — a study may state its own,
        and must, for any label whose unit this cannot parse.
        """
        if self.plausible_bound is not None:
            return self.plausible_bound

        spec = research_spec()["power"]
        base = float(spec["plausible_effect_bound_monthly"])

        if not spec.get("plausible_bound_scales_with_horizon", False):
            # Pre-0028 behaviour, retained so flipping the config off restores it
            # exactly rather than approximately.
            if not _is_monthly_horizon(self.horizon):
                raise DesignRejected(
                    f"horizon {self.horizon!r} has no explicit plausible_bound and "
                    f"scaling is disabled, so only per-MONTH horizons can be judged."
                )
            return base

        months = horizon_in_months(self.horizon)
        if months is None:
            raise DesignRejected(
                f"horizon {self.horizon!r} declares no parseable unit, so its "
                f"plausible bound cannot be derived. Labels this understands are "
                f"'3m'/'6 months' and '10s'/'21 sessions'.\n"
                f"State plausible_bound explicitly for this horizon and record "
                f"why. Guessing a unit is how a 1-session MDE came to be judged "
                f"against a monthly bound (decision 0018)."
            )
        if months <= 0:
            raise DesignRejected(f"horizon {self.horizon!r} resolves to {months} months")
        return base * months

    @property
    def is_powered(self) -> bool:
        """Whether this horizon can see an effect inside the plausible range."""
        return self.mde <= self.resolved_bound


@dataclass(frozen=True, slots=True)
class SidePrediction:
    """A prediction the mechanism makes that the headline effect does not.

    `falsifies_if` is the load-bearing field. A "prediction" with no stated
    failure condition is a description, and it can be satisfied after the fact by
    whatever the data happens to show.
    """

    statement: str
    falsifies_if: str

    def __post_init__(self) -> None:
        if not self.statement.strip():
            raise DesignRejected("side-prediction has no statement")
        if not self.falsifies_if.strip():
            raise DesignRejected(
                f"side-prediction {self.statement[:50]!r} states no failure "
                f"condition. A prediction that cannot fail is a description."
            )


@dataclass(frozen=True, slots=True)
class ConfoundPlan:
    confound_id: str
    applicability: Applicability
    reason: str = ""

    def __post_init__(self) -> None:
        if self.applicability == "NOT_APPLICABLE" and not self.reason.strip():
            raise DesignRejected(
                f"confound {self.confound_id!r} is marked NOT_APPLICABLE with no "
                f"written reason. Skipping is allowed; skipping silently is not."
            )


@dataclass(frozen=True, slots=True)
class StudyDesign:
    """A design that has satisfied all three rules, or an exception.

    Validation runs in __post_init__, so an invalid design cannot be constructed
    and then quietly used. There is no `validate()` for a caller to forget.
    """

    study_id: str
    kind: StudyKind
    mechanism: str
    side_predictions: tuple[SidePrediction, ...]
    horizons: tuple[HorizonPower, ...]
    confounds: tuple[ConfoundPlan, ...]
    trials_before: int
    #: Fraction of the book the signal touches. Required for portfolio studies —
    #: this is the number whose absence let Finding 001 reach a verdict.
    expected_dilution: float | None = None
    expected_annual_benefit: float | None = None
    #: Track S only. Which trial family pays for this search
    #: (configs/trials.yml). Required for kind='scan': a scan that does not
    #: declare its family up front can be charged to whichever counter flatters
    #: it once the result is known, which is the exact abuse the family scheme
    #: exists to prevent.
    trial_family_id: str | None = None
    #: Observations behind each test statistic, minus one. Omitting it assumes a
    #: normal distribution, which understates the bar whenever the per-test
    #: sample is small — 22% for a calendar cell on 21 yearly observations.
    dof: int | None = None
    #: Track S only. Anchored expanding windows share ~95% of their training
    #: data, so a fold count is not an evidence count. Both are required.
    nominal_folds: int | None = None
    effective_folds: float | None = None
    notes: str = ""
    _bar: object = field(default=None, compare=False, repr=False)

    def __post_init__(self) -> None:
        self._check_mechanism()
        self._check_power()
        self._check_confounds()
        self._check_economics()
        self._check_scan()
        object.__setattr__(self, "_bar", self._compute_bar())

    def _compute_bar(self):
        """The bar this design must clear.

        TWO BUGS FIXED 2026-08-18, both making the bar too EASY.

        1. It called `bar(trials_before)` with no `dof`, so every design got the
           normal-distribution assumption. For a scan on 21 yearly observations
           that is a 22% understatement (4.68 against a true 5.73).
        2. It ignored `trial_family_id` entirely — validated that the family
           existed and then never used it. A scan declaring TRACK_S_CALENDAR,
           which carries 31,893,556 prior trials, would have been handed a bar
           computed from trials_before=171: |t| >= 3.67 instead of 11.76.

        The second is the worse one. The family scheme was built the same day to
        stop exactly this, and the design gate walked straight past it.
        """
        if self.trial_family_id:
            from src.research.families import charge

            return charge(self.trial_family_id, 0, dof=self.dof).bar
        return bar(self.trials_before, dof=self.dof)

    # --- rule 2 --------------------------------------------------------------

    def _check_mechanism(self) -> None:
        if len(self.mechanism.strip()) < 40:
            raise DesignRejected(
                f"{self.study_id}: mechanism is missing or too thin "
                f"({len(self.mechanism.strip())} chars). State WHY the effect "
                f"should exist, not what will be measured. 'Measure X and see' is "
                f"a query, not a hypothesis."
            )
        if not self.side_predictions:
            raise DesignRejected(
                f"{self.study_id}: no side-predictions. A mechanism that predicts "
                f"only the headline effect cannot be distinguished from a story "
                f"told about noise. State at least one thing that follows from the "
                f"mechanism and could fail independently — a dose-response in deal "
                f"size, an asymmetry between buys and sells, a regime dependence."
            )

    # --- rule 1 --------------------------------------------------------------

    def _check_power(self) -> None:
        if not self.horizons:
            raise DesignRejected(f"{self.study_id}: no horizons declared")

        blind = [h for h in self.horizons if not h.is_powered]
        if len(blind) == len(self.horizons):
            # Per-horizon bounds, not one number: since decision 0028 the bound
            # scales with horizon, so a single figure here would misreport what
            # each horizon was actually judged against.
            detail = ", ".join(
                f"{h.horizon} MDE={h.mde:.4f} vs bound {h.resolved_bound:.4f}" for h in blind
            )
            raise DesignRejected(
                f"{self.study_id}: EVERY horizon is underpowered against its "
                f"plausible bound. [{detail}]\n"
                f"This study cannot reach a conclusion at any horizon it declares. "
                f"Collapse to a finer cohort frequency, add characteristic "
                f"matching, or do not run it — but do not run it and report the "
                f"p-values."
            )

    # --- rule 3 --------------------------------------------------------------

    def _check_confounds(self) -> None:
        declared = {c.confound_id for c in self.confounds}
        required = set(required_confounds(self.kind))
        missing = required - declared
        if missing:
            raise DesignRejected(
                f"{self.study_id}: blocking confounds neither planned nor "
                f"declared inapplicable: {sorted(missing)}.\n"
                f"The open-to-close microstructure confound ate 71% of the 1-day "
                f"effect on 2026-08-16 and was caught only because someone thought "
                f"of it. See configs/confounds.yml."
            )
        unknown = declared - {c["id"] for c in confound_spec()["confounds"]}
        if unknown:
            raise DesignRejected(
                f"{self.study_id}: unknown confound ids {sorted(unknown)}"
            )

    # --- economic significance, computed before rather than after -------------

    def _check_economics(self) -> None:
        if self.kind != "portfolio":
            return
        if self.expected_dilution is None:
            raise DesignRejected(
                f"{self.study_id}: a portfolio study must state its expected "
                f"dilution BEFORE registration. Finding 001's was 1.2%, and that "
                f"single number explained the whole distance between an event t of "
                f"-3.93 and a portfolio t of -0.25. It was computed afterwards."
            )
        if not 0.0 < self.expected_dilution <= 1.0:
            raise DesignRejected(
                f"{self.study_id}: expected_dilution {self.expected_dilution} is "
                f"not a fraction in (0, 1]"
            )

    # --- Track S: family and folds must be declared, not chosen later --------

    def _check_scan(self) -> None:
        if self.kind != "scan":
            return
        from src.research.families import FamilyError, get

        if not self.trial_family_id:
            raise DesignRejected(
                f"{self.study_id}: a scan must declare its trial family BEFORE "
                f"searching. Without it the search can be charged to whichever "
                f"counter flatters the result afterwards — the exact abuse "
                f"configs/trials.yml exists to prevent."
            )
        try:
            get(self.trial_family_id)
        except FamilyError as exc:
            raise DesignRejected(f"{self.study_id}: {exc}") from exc

        if self.nominal_folds is None or self.nominal_folds < 2:
            raise DesignRejected(
                f"{self.study_id}: a scan must declare at least 2 folds. A "
                f"single fold is an in-sample fit, which is what the "
                f"predecessor's 31.9M-cell atlas was."
            )
        if self.effective_folds is None:
            raise DesignRejected(
                f"{self.study_id}: effective_folds not declared. Anchored "
                f"expanding windows share ~95% of their training data, so "
                f"{self.nominal_folds} folds are NOT {self.nominal_folds} "
                f"independent tests. Report both or the fold count misleads."
            )
        if self.effective_folds > self.nominal_folds:
            raise DesignRejected(
                f"{self.study_id}: effective_folds {self.effective_folds} exceeds "
                f"nominal {self.nominal_folds}, which is impossible."
            )

    # --- reporting -----------------------------------------------------------

    @property
    def required_t(self) -> float:
        """The bar this study must clear, given everything looked at before it."""
        return self._bar.required_t  # type: ignore[attr-defined]

    @property
    def powered_horizons(self) -> tuple[HorizonPower, ...]:
        return tuple(h for h in self.horizons if h.is_powered)

    @property
    def underpowered_horizons(self) -> tuple[HorizonPower, ...]:
        return tuple(h for h in self.horizons if not h.is_powered)

    def summary(self) -> str:
        lines = [
            f"study            : {self.study_id}  ({self.kind})",
            f"required |t|     : {self.required_t:.2f}  "
            f"({self.trials_before} prior trials)",
            f"horizons powered : {len(self.powered_horizons)}/{len(self.horizons)}",
        ]
        if self.underpowered_horizons:
            lines.append(
                "  UNDERPOWERED   : "
                + ", ".join(h.horizon for h in self.underpowered_horizons)
                + "  -> reported as silence, not as a negative"
            )
        lines.append(f"side-predictions : {len(self.side_predictions)}")
        na = [c.confound_id for c in self.confounds if c.applicability == "NOT_APPLICABLE"]
        lines.append(
            f"confounds        : {len(self.confounds)} declared"
            + (f", {len(na)} inapplicable ({', '.join(na)})" if na else "")
        )
        if self.expected_dilution is not None:
            lines.append(f"expected dilution: {self.expected_dilution:.2%} of the book")
        return "\n".join(lines)
