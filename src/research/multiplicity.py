"""multiplicity.py — turn the trial counter from bookkeeping into a bar.

WHY THIS EXISTS.

`trial_counter` has been maintained since the first commit. `trials_before` was
computed at exp_001's registration and stored as 171. It was then **printed, and
never used for anything.** Nothing in the codebase read it back. A counter that
does not change a number is not discipline; it is a diary.

This module is what makes it bite. Given the number of things looked at before a
result, it answers: **what would the best of that many pure-noise trials have
looked like?** Anything at or below that line is indistinguishable from having
looked a lot.

THE CORE ARITHMETIC. Draw N independent standard-normal test statistics. The
expected maximum is not 0 — it grows like sqrt(2 ln N). With N = 171 the best of
them is around 2.7 *by construction*, with no effect present anywhere. Reporting
"t = 2.7, p < 0.01" after 171 trials is reporting the null.

The estimator is Lopez de Prado's, used inside the Deflated Sharpe Ratio:

    E[max_N z] ~= (1 - g) * Z^-1(1 - 1/N) + g * Z^-1(1 - 1/(N*e))

with g the Euler-Mascheroni constant. It comes from the Gumbel limit of the
maximum of N iid normals and is materially more accurate than the sqrt(2 ln N)
asymptotic at the N we actually work at (tens to low thousands).

INDEPENDENCE IS THE ASSUMPTION, AND IT IS WRONG. Real trials are correlated —
adjacent horizons on the same event set are nearly the same test. Correlated
trials behave like fewer independent ones, so treating N as independent is
CONSERVATIVE: the bar comes out too high rather than too low. That is the right
direction for the error to point, and `effective_trials` is provided for when the
correlation can actually be estimated instead of assumed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from scipy.stats import norm

#: Euler-Mascheroni. Appears via the Gumbel limit, not by numerology.
EULER_GAMMA = 0.5772156649015329


class MultiplicityError(ValueError):
    """A bar was requested with inputs that cannot produce one."""


@dataclass(frozen=True, slots=True)
class Bar:
    """A significance bar that already accounts for how much was looked at."""

    trials: int
    expected_max_null_t: float
    required_t: float
    naive_alpha: float
    adjusted_alpha: float
    margin: float
    rationale: str

    def clears(self, observed_t: float) -> bool:
        """Two-sided. A negative effect of the predicted sign counts."""
        return abs(observed_t) >= self.required_t

    def as_row(self) -> dict:
        return {
            "trials": self.trials,
            "expected_max_null_t": round(self.expected_max_null_t, 4),
            "required_t": round(self.required_t, 4),
            "naive_alpha": self.naive_alpha,
            "adjusted_alpha": self.adjusted_alpha,
            "margin": self.margin,
            "rationale": self.rationale,
        }


def expected_max_null_t(trials: int) -> float:
    """Expected largest |t| from `trials` pure-noise trials.

    The number that makes multiplicity concrete. Under the null with no effect
    anywhere:

        trials      E[max t]
             1        0.00
            10        1.54
           100        2.51
           171        2.72      <- where this project stands today
         1,000        3.24
        31,900,000    5.55      <- the seasonality atlas
    """
    if trials < 1:
        raise MultiplicityError(f"trials must be >= 1, got {trials}")
    if trials == 1:
        return 0.0
    n = float(trials)
    return (1 - EULER_GAMMA) * norm.ppf(1 - 1 / n) + EULER_GAMMA * norm.ppf(
        1 - 1 / (n * math.e)
    )


def sidak_alpha(alpha: float, trials: int) -> float:
    """Family-wise alpha under independence: 1 - (1-a)^(1/N).

    Sidak rather than Bonferroni because it is exact under the independence both
    of them assume, rather than a bound on it. The difference is small at these N
    and there is no reason to take the looser one.
    """
    if not 0 < alpha < 1:
        raise MultiplicityError(f"alpha must be in (0,1), got {alpha}")
    if trials < 1:
        raise MultiplicityError(f"trials must be >= 1, got {trials}")
    return 1 - (1 - alpha) ** (1 / trials)


def effective_trials(trials: int, mean_correlation: float) -> float:
    """Independent-equivalent trial count when trials are correlated.

    Adjacent horizons on one event set are nearly the same test, so counting them
    as separate trials overstates the search. Uses the same design effect as the
    split's effective sample size, for the same reason and with the same caveat.

    Only use this with a MEASURED correlation. Assuming a high one to shrink the
    bar is exactly the move this module exists to prevent, so it is capped at the
    nominal count and floored at 1.
    """
    if trials < 1:
        raise MultiplicityError(f"trials must be >= 1, got {trials}")
    rho = min(max(float(mean_correlation), 0.0), 0.999)
    return max(1.0, trials / (1.0 + (trials - 1) * rho))


def bar(
    trials: int,
    alpha: float = 0.05,
    margin: float = 0.25,
    mean_correlation: float | None = None,
) -> Bar:
    """The t-statistic a result must clear, given how much was looked at.

    Two components, and the max of them is taken:

    1. The classical family-wise critical value at Sidak-adjusted alpha.
    2. `expected_max_null_t` scaled by `1 + margin` — because merely matching what
       noise produces is not evidence, it is a tie with the null.

    The default margin of 0.25 is a judgement, not a derivation, and is recorded
    as such in the returned rationale so it cannot later be mistaken for one.
    """
    if trials < 1:
        raise MultiplicityError(f"trials must be >= 1, got {trials}")
    if margin < 0:
        raise MultiplicityError(f"margin must be >= 0, got {margin}")

    n_eff = (
        float(trials)
        if mean_correlation is None
        else effective_trials(trials, mean_correlation)
    )
    adj = sidak_alpha(alpha, max(1, round(n_eff)))
    classical = float(norm.ppf(1 - adj / 2))  # two-sided
    noise = expected_max_null_t(max(1, round(n_eff)))
    required = max(classical, noise * (1 + margin))

    which = "family-wise critical value" if required == classical else "noise-max + margin"
    corr = (
        ""
        if mean_correlation is None
        else f", using measured rho={mean_correlation:.3f} -> n_eff={n_eff:.1f}"
    )
    return Bar(
        trials=trials,
        expected_max_null_t=noise,
        required_t=required,
        naive_alpha=alpha,
        adjusted_alpha=adj,
        margin=margin,
        rationale=(
            f"{trials} prior trials{corr}. Best-of-{max(1, round(n_eff))} pure noise "
            f"gives |t| ~= {noise:.2f}; Sidak alpha {adj:.2e} needs |t| >= "
            f"{classical:.2f}. Binding constraint: {which}. Required |t| >= "
            f"{required:.2f}. The {margin:.0%} margin is a judgement, not a "
            f"derivation."
        ),
    )
