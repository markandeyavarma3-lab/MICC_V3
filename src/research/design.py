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

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Literal

import yaml

from src.common.paths import CONFIGS
from src.research.multiplicity import bar

StudyKind = Literal["event_study", "portfolio", "seasonality"]
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
    def is_powered(self) -> bool:
        bound = self.plausible_bound
        if bound is None:
            bound = research_spec()["power"]["plausible_effect_bound_monthly"]
        return self.mde <= bound


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
    notes: str = ""
    _bar: object = field(default=None, compare=False, repr=False)

    def __post_init__(self) -> None:
        self._check_mechanism()
        self._check_power()
        self._check_confounds()
        self._check_economics()
        object.__setattr__(self, "_bar", bar(self.trials_before))

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
            bound = research_spec()["power"]["plausible_effect_bound_monthly"]
            detail = ", ".join(f"{h.horizon} MDE={h.mde:.4f}" for h in blind)
            raise DesignRejected(
                f"{self.study_id}: EVERY horizon is underpowered against the "
                f"plausible bound of {bound:.4f}. [{detail}]\n"
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
