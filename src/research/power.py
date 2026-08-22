"""power.py — statistical power, computed before the fit rather than after.

WHY THIS IS A MODULE AND NOT A PARAGRAPH. The plan promised "minimum detectable
effect is computed before any fit" and then never did it. When it was finally
computed on 2026-08-16 the headline finding changed: the 12-month bulk-buy result
of +7.80% sits on a detection floor of 7.38%. It was never marginal evidence — it
was undetectable, and reporting it as marginal was wrong.

Every registered experiment calls this to set its `pass_bar` and `kill_criteria`
from measured power. A pre-registration whose bars come from a guess is ceremony.

THE OVERLAP PROBLEM, which governs everything here. With 12- to 24-month horizons
and events clustered in time, observations overlap and correlate cross-sectionally.
Measured on the same data:

    naive t (treats 15,498 events as independent)     +11.61
    monthly-cohort t                                   +3.61
    moving-block bootstrap 95% CI             [-2.46%, +22.81%]

A naive standard error overstates significance by roughly 3x. So the estimator
here is the cohort mean, never the pooled event mean.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import erf, sqrt
from typing import Literal

import numpy as np
import pandas as pd

Verdict = Literal["PASS", "FAIL", "UNDERPOWERED"]

#: z(1 - 0.05/2) and z(0.80): the two-sided alpha=0.05, 80%-power constants.
_Z_ALPHA_TWO_SIDED_05 = 1.959963984540054
_Z_POWER_80 = 0.8416212335729143


def _z(p: float) -> float:
    """Inverse standard normal CDF by bisection on math.erf.

    Four numbers do not justify a scipy dependency in a module every study
    imports, and bisection converges far beyond the precision needed here.
    """
    lo, hi = -10.0, 10.0
    for _ in range(200):
        mid = (lo + hi) / 2
        if 0.5 * (1 + erf(mid / sqrt(2))) < p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


@dataclass(frozen=True, slots=True)
class PowerResult:
    """Everything needed to judge whether a study could have seen anything."""

    n_events: int
    n_periods: int
    cohort_sd: float
    cohort_mean: float
    mde: float
    plausible_bound: float
    verdict: Verdict
    reason: str

    def as_row(self) -> dict[str, object]:
        """Shaped for the columns `study_result` requires."""
        return {
            "n_events": self.n_events,
            "n_independent": self.n_periods,
            "cohort_sd": self.cohort_sd,
            "mean_return": self.cohort_mean,
            "mde": self.mde,
            "verdict": self.verdict,
            "reason": self.reason,
        }


def cohort_collapse(
    event_dates: pd.Series | np.ndarray,
    relative_returns: pd.Series | np.ndarray,
    freq: str = "M",
) -> pd.Series:
    """Collapse overlapping events into equal-weighted period cohorts.

    The primary estimator, not a robustness step. Pooling 15,498 overlapping
    12-month observations and dividing by sqrt(15,498) claims independence the
    data does not have.
    """
    df = pd.DataFrame(
        {
            "dt": pd.to_datetime(pd.Series(event_dates).values),
            "rel": np.asarray(relative_returns, dtype=float),
        }
    ).dropna(subset=["rel"])
    if df.empty:
        return pd.Series(dtype=float)
    return df.groupby(df["dt"].dt.to_period(freq))["rel"].mean().sort_index()


def cohort_sd(cohorts: pd.Series) -> float:
    """Dispersion of the cohort means — the quantity that sets the standard error."""
    if len(cohorts) < 2:
        return float("nan")
    return float(cohorts.std(ddof=1))


def mde(sd: float, n_periods: int, power: float = 0.80, alpha: float = 0.05) -> float:
    """Minimum detectable effect on the cohort mean, two-sided.

        MDE = (z_{1-a/2} + z_{power}) * sd / sqrt(n)

    The effect size the study *could* detect. Anything smaller is invisible to it
    whether or not it exists.
    """
    if not np.isfinite(sd) or n_periods < 2:
        return float("nan")
    za = _Z_ALPHA_TWO_SIDED_05 if abs(alpha - 0.05) < 1e-12 else _z(1 - alpha / 2)
    zb = _Z_POWER_80 if abs(power - 0.80) < 1e-12 else _z(power)
    return float((za + zb) * sd / np.sqrt(n_periods))


def verdict(
    observed: float,
    detectable: float,
    plausible_bound: float,
    p_value: float | None = None,
    alpha: float = 0.05,
) -> tuple[Verdict, str]:
    """PASS / FAIL / UNDERPOWERED.

    UNDERPOWERED OUTRANKS A SIGNIFICANT p-VALUE. If the smallest effect the study
    can see exceeds the largest effect anyone should believe, the result carries
    no information about the hypothesis — and a p that happens to clear 0.05 in
    that regime is a false discovery about to be reported as a finding.

    `plausible_bound` is the largest monthly abnormal return credible for the
    effect being tested. For institutional-follow strategies 0.5%/month (6%/yr)
    is already generous.
    """
    if not np.isfinite(detectable):
        return "UNDERPOWERED", "cohort dispersion could not be estimated"

    if detectable > plausible_bound:
        return (
            "UNDERPOWERED",
            f"MDE {detectable:.4f} exceeds the plausible bound {plausible_bound:.4f}: "
            "only implausibly large effects are visible here, so this is silence, "
            "not a negative result",
        )

    if p_value is not None and p_value < alpha and abs(observed) >= detectable:
        return (
            "PASS",
            f"p={p_value:.4f} < {alpha} and |effect| {abs(observed):.4f} >= MDE {detectable:.4f}",
        )

    if abs(observed) < detectable:
        return (
            "FAIL",
            f"|effect| {abs(observed):.4f} below MDE {detectable:.4f}: an effect this "
            "small is indistinguishable from zero here",
        )

    return "FAIL", f"effect {observed:.4f} did not clear the pre-registered bar"


def assess(
    event_dates: pd.Series | np.ndarray,
    relative_returns: pd.Series | np.ndarray,
    plausible_bound: float,
    power: float = 0.80,
    alpha: float = 0.05,
    freq: str = "M",
) -> PowerResult:
    """The whole assessment in one call — used at registration and at reporting."""
    rel = np.asarray(relative_returns, dtype=float)
    cohorts = cohort_collapse(event_dates, rel, freq=freq)
    sd = cohort_sd(cohorts)
    detectable = mde(sd, len(cohorts), power=power, alpha=alpha)
    mean = float(cohorts.mean()) if len(cohorts) else float("nan")
    v, reason = verdict(mean, detectable, plausible_bound, alpha=alpha)
    return PowerResult(
        n_events=int(np.isfinite(rel).sum()),
        n_periods=len(cohorts),
        cohort_sd=sd,
        cohort_mean=mean,
        mde=detectable,
        plausible_bound=plausible_bound,
        verdict=v,
        reason=reason,
    )


def block_bootstrap_ci(
    cohorts: pd.Series,
    block_length: int,
    draws: int = 10_000,
    seed: int = 0,
    ci: float = 0.95,
) -> tuple[float, float, float]:
    """Moving-block bootstrap CI on the cohort mean.

    Blocks must be at least the label horizon, or the resampling destroys the
    serial dependence it exists to preserve. Returns (low, high, P(mean > 0)).
    """
    v = np.asarray(cohorts.dropna(), dtype=float)
    if block_length < 1 or len(v) < block_length + 1:
        return float("nan"), float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    n_blocks = int(np.ceil(len(v) / block_length))
    starts = rng.integers(0, len(v) - block_length + 1, size=(draws, n_blocks))
    means = np.empty(draws)
    for i in range(draws):
        means[i] = np.concatenate([v[s : s + block_length] for s in starts[i]])[: len(v)].mean()
    tail = (1 - ci) / 2 * 100
    return (
        float(np.percentile(means, tail)),
        float(np.percentile(means, 100 - tail)),
        float((means > 0).mean()),
    )


# --- serial correlation: the correction that was actually missing -------------
#
# ADDED 2026-08-17, replacing a claim that was wrong.
#
# An earlier note in configs/split.yml asserted that "every MDE treats names as
# independent and is therefore optimistic". That was false: cohort_collapse above
# already defeats CROSS-SECTIONAL dependence by construction, because one month
# becomes one observation regardless of how many events fall inside it. Measured
# at the 10-session horizon on 16,445 real events, the difference is 8x:
#
#     naive on events (never done)   MDE 0.076%
#     monthly cohort (what we do)    MDE 0.621%
#
# What WAS missing is dependence BETWEEN months. Cohort means are autocorrelated —
# measured rho_1 of 0.086 to 0.133 across horizons — so 247 months are not 247
# independent observations. That is a real correction and a modest one: 6-27%.


def nw_lag(n: int) -> int:
    """Newey-West rule of thumb, 4*(n/100)^(2/9). K=5 at n=247."""
    return max(1, int(round(4 * (n / 100) ** (2 / 9))))


def serial_inflation(
    cohorts: pd.Series,
    max_lag: int | None = None,
    label_periods: int | None = None,
) -> tuple[float, int]:
    """Bartlett-kernel variance inflation for the mean of an autocorrelated series.

    Returns (inflation, lag_used). The inflation multiplies the variance of the
    sample mean, so n_eff = n / inflation.

        infl = 1 + 2 * sum_k (1 - k/(K+1)) * rho_k

    The Bartlett taper is what keeps the estimate positive-semidefinite; an
    untapered sum can and does go negative on real data, which would produce an
    n_eff above n and silently flatter the study.

    THE LAG MUST COVER THE LABEL OVERLAP. Defect found 2026-08-23.

    The rule of thumb depends only on the NUMBER of observations and knows
    nothing about how far each one's label reaches. That is fine for
    non-overlapping data and badly wrong for the overlapping windows this project
    is built on. Two measurements from that day:

        12-month label, 236 monthly cohorts (overlap 11/12):
            NW rule    K= 5   inflation 1.77   MDE 4.97%   -> "POWERED"
            K = 12            inflation 2.37   MDE 5.73%   -> POWERED, 5% margin
            K = 18            inflation 2.66   MDE 6.07%   -> 1.01x SHORT

        252-session label, 5,035 daily cohorts (overlap 251/252):
            NW rule    K= 9   inflation  2.06  MDE 3.62%   -> "POWERED"
            K = 252           inflation 10.02  MDE 7.97%   -> 1.3x SHORT

    In the second case the rule picked lag 9 against a true overlap of 252 and
    understated the variance inflation FIVEFOLD. Both produced a POWERED verdict
    that a correct lag removes. A verdict that depends on a parameter nobody
    chose deliberately is not a verdict.

    `label_periods` is the horizon expressed in COHORT PERIODS — 12 for a
    12-month label on monthly cohorts, 252 for a 252-session label on daily ones.
    When given, the lag is at least that. Pass it for any overlapping study;
    omitting it retains the old behaviour and is correct only when consecutive
    observations do not share a window.
    """
    v = np.asarray(cohorts.dropna(), dtype=float)
    n = len(v)
    if n < 3:
        return 1.0, 0
    if max_lag is not None:
        k_max = max_lag
    else:
        k_max = nw_lag(n)
        if label_periods is not None:
            # Never round DOWN to the rule of thumb: under-correcting is what
            # manufactures a false POWERED verdict.
            k_max = max(k_max, int(label_periods))
    k_max = min(k_max, n - 1)
    centred = v - v.mean()
    denom = float((centred**2).sum())
    if denom == 0.0:
        return 1.0, k_max
    total = 0.0
    for k in range(1, k_max + 1):
        rho_k = float((centred[:-k] * centred[k:]).sum() / denom)
        total += (1 - k / (k_max + 1)) * rho_k
    # Floored at 1.0: negative autocorrelation would imply the cohort mean is
    # MORE precise than iid. That may even be true, but claiming extra power from
    # a noisy lag estimate is exactly the wrong direction to round.
    return max(1.0, 1 + 2 * total), k_max


def effective_periods(
    cohorts: pd.Series,
    max_lag: int | None = None,
    label_periods: int | None = None,
) -> float:
    """Independent-equivalent number of periods after the serial correction."""
    infl, _ = serial_inflation(cohorts, max_lag, label_periods)
    return len(cohorts.dropna()) / infl


def mde_serial_corrected(
    cohorts: pd.Series,
    power: float = 0.80,
    alpha: float = 0.05,
    max_lag: int | None = None,
    label_periods: int | None = None,
) -> float:
    """MDE on the cohort mean, accounting for dependence between periods.

    This is the number a study should report. Measured 2026-08-17 on directional
    bulk buys, market-relative:

        horizon   rho_1   inflation   n_eff/247   observed    MDE
           1s     0.086     1.62        152.2     +0.691%    0.191%
           5s     0.133     1.29        192.1     -0.010%    0.423%
          10s     0.122     1.13        219.3     -0.603%    0.660%
          21s     0.111     1.16        212.2     -1.061%    0.968%

    Note the sign flip: a one-session pop that decays into a twenty-one-session
    loss. That is temporary price impact reversing, which is what a corpus that is
    54.8% same-day round-trip ought to produce.
    """
    clean = cohorts.dropna()
    if len(clean) < 3:
        return float("nan")
    n_eff = max(2.0, effective_periods(clean, max_lag, label_periods))
    return mde(cohort_sd(clean), int(round(n_eff)), power=power, alpha=alpha)
