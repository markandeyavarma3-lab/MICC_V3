"""seasonality_power.py — Engine 2 feasibility arithmetic. Track S.

PURE ARITHMETIC. This module imports no warehouse, opens no database and writes
no table. It exists because docs/reports/SEASONALITY_POWER.md makes numerical
claims, and a claim in a memo that is not reproducible from code is an
assertion. Every figure in that memo comes from a function here and is pinned by
tests/test_seasonality_power.py.

THE INPUTS ARE THE PROJECT'S OWN MEASUREMENTS, not fresh estimates:

  rho = 0.2350            cross-sectional correlation of raw returns, measured on
                          656 stocks x 2,870 sessions -- configs/scan.yml
                          `basis.measured_2026_08_18.rho_raw`
  IC sd = 0.1190          sd of the cross-sectional rank IC, same panel --
                          configs/scan.yml `cross_sectional.measured_ic_sd`
  annual sd = 25%/yr      BACKED OUT of the project's own quoted seasonality
                          MDEs rather than assumed: configs/scan.yml states "Two
                          observations detect an effect of 49.5%/yr. Twenty-one
                          detect 15.3%/yr", and both imply 25.0%/yr under
                          power.mde. See test_the_annual_sd_is_backed_out_of_the_
                          repos_own_quoted_mdes.
  21 years                price_spine_adj span, per docs/STATUS.md:44 ("adjusted
                          spine reaches 2026-09-10") and the 2005 start in
                          configs/split.yml `seasonality_split.time.explore`.

WHY POOLING ACROSS NAMES BUYS ALMOST NOTHING. With average pairwise correlation
rho, N names carry the information of N/(1+(N-1)rho) independent ones, which for
large N tends to 1/rho. At rho = 0.235 the entire 4,200-name universe is worth
4.25 independent names. configs/scan.yml measured exactly this ("rho +0.2350
n_eff 4.3 of 21,000"), and the same file records the correction that matters:
the market-relative rho of +0.0001 was an ARTIFACT of subtracting the
cross-sectional mean, which forces rho to -1/(N-1) whatever the input is. So
0.235 is the honest figure and there is no basis on which it becomes small.
"""

from __future__ import annotations

import math

from src.research.power import _Z_ALPHA_TWO_SIDED_05, _Z_POWER_80, _z

#: MICCV2's enumerated calendar-cell count, charged to Track S as prior search.
#: configs/trials.yml `TRACK_S_CALENDAR.prior_external_search`.
PRIOR_SCAN_CELLS = 31_893_556

#: The documented grid axes. docs/report/PROJECT_REPORT.md:386 and
#: configs/split.yml:193. These do NOT multiply to PRIOR_SCAN_CELLS; see
#: `cartesian_cells` and the memo's item 1.
WINDOW_LENGTHS = 13
START_POINTS = 242
COMPANIES = 4_200
INDICES = 202
ALIGNMENTS = 4
BASES = 2

RHO_CROSS_SECTIONAL = 0.2350
IC_SD = 0.1190
SD_ANNUAL_PCT = 25.0
YEARS_AVAILABLE = 21

#: Statutory round trip, configs/costs.yml baseline as used by costs.round_trip_bps.
ROUND_TRIP_BPS = 29.33


def cartesian_cells() -> int:
    """The FULL cartesian product over the documented axes.

    PRIOR_SCAN_CELLS is 28.8% of this. That shortfall is the point: V2's figure
    is an enumeration over entities with unequal history, not a product, so it
    cannot be reproduced by multiplying the documented axes together.
    """
    return WINDOW_LENGTHS * START_POINTS * (COMPANIES + INDICES) * ALIGNMENTS * BASES


def z_two_sided(alpha: float) -> float:
    """Two-sided critical z. Uses power.py's pinned constant at alpha = 0.05."""
    if abs(alpha - 0.05) < 1e-12:
        return _Z_ALPHA_TWO_SIDED_05
    return _z(1.0 - alpha / 2.0)


def bonferroni_alpha(m_tests: int, alpha: float = 0.05) -> float:
    return alpha / m_tests


def bh_alpha(m_tests: int, n_discoveries: int, alpha: float = 0.05) -> float:
    """The BH-FDR threshold at the `n_discoveries`-th rejection: alpha*R/m.

    BH is only less stringent than Bonferroni to the extent that discoveries
    actually exist. At R = 1 the two coincide, so assuming a large R is assuming
    the answer -- which is why the memo reports a range of R rather than one.
    """
    return alpha * n_discoveries / m_tests


def n_eff(n_names: int, rho: float = RHO_CROSS_SECTIONAL) -> float:
    """Independent-equivalent count of `n_names` names correlated at `rho`."""
    if n_names < 1:
        return float("nan")
    return n_names / (1.0 + (n_names - 1) * rho)


def sd_monthly_pct(sd_annual: float = SD_ANNUAL_PCT) -> float:
    return sd_annual / math.sqrt(12.0)


def mde_monthly_bps(
    m_tests: int,
    n_firings: int = 20,
    window_months: float = 1.0,
    n_names: int = 1,
    rho: float = RHO_CROSS_SECTIONAL,
    alpha: float = 0.05,
    power: float = 0.80,
    correction: str = "bonferroni",
    n_discoveries: int = 1,
) -> float:
    """Minimum detectable mean excess return, in bps PER MONTH.

    A calendar cell fires once a year, so `n_firings` is years of history and no
    amount of pooling across names increases it. `window_months` lengthens the
    held window: a drift effect grows linearly with the window while its sd grows
    as its square root, so quoting the MDE as a monthly RATE divides by
    `window_months` and multiplies the sd by its root -- a net sqrt(T) gain.
    """
    if correction == "bonferroni":
        a = bonferroni_alpha(m_tests, alpha)
    elif correction == "bh":
        a = bh_alpha(m_tests, n_discoveries, alpha)
    elif correction == "none":
        a = alpha
    else:
        raise ValueError(f"unknown correction {correction!r}")
    zb = _Z_POWER_80 if abs(power - 0.80) < 1e-12 else _z(power)
    sd = sd_monthly_pct() * math.sqrt(window_months) / math.sqrt(n_eff(n_names, rho))
    se = sd / math.sqrt(n_firings)
    return (z_two_sided(a) + zb) * se / window_months * 100.0


def years_required(
    effect_bps: float,
    m_tests: int,
    n_names: int = COMPANIES,
    window_months: float = 1.0,
    rho: float = RHO_CROSS_SECTIONAL,
    alpha: float = 0.05,
    power: float = 0.80,
) -> float:
    """Years of history needed to detect `effect_bps` per month at 80% power."""
    zb = _Z_POWER_80 if abs(power - 0.80) < 1e-12 else _z(power)
    sd = sd_monthly_pct() * math.sqrt(window_months) / math.sqrt(n_eff(n_names, rho))
    target = effect_bps / 100.0 * window_months
    return ((z_two_sided(bonferroni_alpha(m_tests, alpha)) + zb) * sd / target) ** 2


def ic_observations(
    n_firings: int = 20, sessions_per_firing: int = 21, rho_ic: float = 0.0
) -> float:
    """Independent-equivalent IC observations for a calendar cell.

    THE UNIT OF EVIDENCE QUESTION, WHICH IS THE WHOLE ARGUMENT. configs/scan.yml
    fixes the rank-IC unit as the DATE, and records why: "pooling stocks buys
    precision WITHIN a date, and buys no additional dates." The same logic
    applies one level up. A calendar claim is about the month, and the sessions
    inside one firing move together, so they buy precision WITHIN a firing and
    buy no additional firings. At rho_ic = 0 they count fully (420 for a monthly
    cell over 20 years); at rho_ic = 1 the firing is one observation (20).
    Neither extreme is credible, so the memo reports the curve.
    """
    per = sessions_per_firing / (1.0 + (sessions_per_firing - 1) * rho_ic)
    return n_firings * per


def mde_rank_ic(
    m_tests: int,
    n_firings: int = 20,
    sessions_per_firing: int = 21,
    rho_ic: float = 0.0,
    ic_sd: float = IC_SD,
    alpha: float = 0.05,
    power: float = 0.80,
) -> float:
    """Minimum detectable mean cross-sectional rank IC under Bonferroni."""
    zb = _Z_POWER_80 if abs(power - 0.80) < 1e-12 else _z(power)
    n = ic_observations(n_firings, sessions_per_firing, rho_ic)
    return (z_two_sided(bonferroni_alpha(m_tests, alpha)) + zb) * ic_sd / math.sqrt(n)


def cost_bps_per_month(window_months: float, round_trip_bps: float = ROUND_TRIP_BPS) -> float:
    """One round trip per firing, amortised over the held window."""
    return round_trip_bps / window_months
