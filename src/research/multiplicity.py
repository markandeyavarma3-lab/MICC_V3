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
expected largest |t| is not 0 — it grows like sqrt(2 ln N). With N = 171 the best
of them is around 2.94 *by construction*, with no effect present anywhere.
Reporting "t = 2.9, p < 0.01" after 171 trials is reporting the null.

The estimator is Lopez de Prado's, used inside the Deflated Sharpe Ratio:

    E[max_N z] ~= (1 - g) * Z^-1(1 - 1/N) + g * Z^-1(1 - 1/(N*e))

with g the Euler-Mascheroni constant. It comes from the Gumbel limit of the
maximum of N iid normals and is materially more accurate than the sqrt(2 ln N)
asymptotic at the N we actually work at (tens to low thousands).

TWO ASSUMPTIONS, PULLING IN OPPOSITE DIRECTIONS. Measured 2026-08-18.

An earlier version of this docstring claimed that ignoring correlation between
trials is CONSERVATIVE — "the bar comes out too high rather than too low, which
is the right direction for the error to point". **That was only half true, and
the other half points the wrong way.**

  1. CORRELATION lowers the maximum. Correlated trials behave like fewer
     independent ones. Measured at df=20 over 3,146 cells: rho=0.0 gives
     E[max |t|] 4.595, rho=0.3 gives 4.125, rho=0.7 gives 3.071. Ignoring this
     is indeed conservative.

  2. DEGREES OF FREEDOM raise it, and this was missed entirely. Real statistics
     are t-distributed, not normal, and with few observations the t has far
     fatter tails. Over 3,146 draws: normal gives 3.746, t(20) gives 4.599 —
     23% higher. Ignoring this is ANTI-conservative and makes results too easy
     to pass.

On a realistic calendar grid the two partly cancel: the normal formula said
3.568, dof-adjustment says ~4.60, and the measured value on the true geometry was
4.151. **No formula gets a specific grid right.** Pass `dof` when the per-test
sample is small, and use `simulated_max_null_t` when the grid geometry matters —
which for any real scan, it does.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from scipy.stats import norm
from scipy.stats import t as t_dist

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


def expected_max_null_t(trials: int, dof: int | None = None) -> float:
    """Expected largest |t| from `trials` pure-noise trials.

    DEGREES OF FREEDOM MATTER, AND OMITTING THEM ROUNDS THE WRONG WAY.

    Added 2026-08-18 after measurement. The original version assumed every test
    statistic was standard normal. Real statistics are t-distributed, and with
    few observations the t has much fatter tails, so the maximum of many draws is
    LARGER than the normal formula says. Measured over 3,146 draws:

        distribution                E[max |stat|]
        normal N(0,1)                   3.746
        t, df=20   (21 observations)    4.599     <- +23%
        t, df=30                        4.280
        t, df=60                        3.999
        t, df=250                       3.798

    A calendar cell scored on 21 yearly observations is t(20), not normal. The
    un-adjusted bar therefore UNDERSTATES what noise produces, which is the
    dangerous direction: it makes results too easy to pass.

    Track D is unaffected in practice — 247 monthly cohorts give t(246), which is
    indistinguishable from normal. Track S is affected badly.

    Pass `dof` whenever the number of observations behind each statistic is
    small. `dof=None` retains the normal assumption and is correct only when the
    per-test sample is large.
    """
    if trials < 1:
        raise MultiplicityError(f"trials must be >= 1, got {trials}")
    if trials == 1:
        return 0.0
    if dof is not None and dof < 1:
        raise MultiplicityError(f"dof must be >= 1 when given, got {dof}")

    # SIDEDNESS, corrected 2026-08-18. The original used norm.ppf(1 - 1/n), which
    # is the expected maximum of N SIGNED normals. But `Bar.clears()` compares
    # abs(observed_t), so the bar is two-sided and the floor must be E[max |t|].
    # Measured: at N=171, max(z) is 2.693 but max|z| is 2.922. The module matched
    # the former while being applied to the latter, understating every bar it has
    # ever produced. A third error pointing the anti-conservative way.
    #
    # The |t| distribution has F(x) = 2*G(x) - 1, so its quantile is
    # G^-1((1+p)/2). Both branches now use that form.
    n = float(trials)
    ppf = norm.ppf if dof is None else (lambda p: t_dist.ppf(p, dof))

    def q(p: float) -> float:
        return float(ppf((1 + p) / 2))

    return (1 - EULER_GAMMA) * q(1 - 1 / n) + EULER_GAMMA * q(1 - 1 / (n * math.e))


def simulated_max_null_t(
    sampler,
    reps: int = 2000,
    seed: int = 0,
) -> tuple[float, float]:
    """E[max |t|] measured by simulating the ACTUAL grid, not assumed.

    THE ONLY TRUSTWORTHY OPTION FOR A CORRELATED SCAN. Measured on a realistic
    calendar grid (242 ordinals x 13 windows, 21 years of pure noise):

        module, normal assumption          3.568
        module, dof-adjusted               ~4.60
        EMPIRICAL on the real geometry     4.151

    Two effects run in opposite directions and neither is negligible:
    fat tails RAISE the maximum, correlation between overlapping cells LOWERS it.
    Isolated, at df=20 over 3,146 cells:

        cell correlation rho=0.0   E[max |t|] 4.595
        cell correlation rho=0.3              4.125
        cell correlation rho=0.7              3.071

    Because they partly cancel, no formula gets this right for a given grid. The
    honest procedure is to generate the grid under its own null and look.

    `sampler(rng)` must return the max |t| for one replication of the real grid
    geometry under the null. Returns (mean, sd).
    """
    import numpy as np

    rng = np.random.default_rng(seed)
    vals = np.array([float(sampler(rng)) for _ in range(reps)])
    return float(vals.mean()), float(vals.std())


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
    dof: int | None = None,
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
    classical = (
        float(norm.ppf(1 - adj / 2))
        if dof is None
        else float(t_dist.ppf(1 - adj / 2, dof))
    )
    noise = expected_max_null_t(max(1, round(n_eff)), dof=dof)
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
            f"{trials} prior trials{corr}"
            f"{'' if dof is None else f', dof={dof}'}. "
            f"Best-of-{max(1, round(n_eff))} pure noise "
            f"gives |t| ~= {noise:.2f}; Sidak alpha {adj:.2e} needs |t| >= "
            f"{classical:.2f}. Binding constraint: {which}. Required |t| >= "
            f"{required:.2f}. The {margin:.0%} margin is a judgement, not a "
            f"derivation."
        ),
    )
