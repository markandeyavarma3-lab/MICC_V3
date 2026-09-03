"""costs.py — Phase 5. What friction takes, before any result claims to survive it.

WHY THIS EXISTS AND WHY IT IS REBUILT RATHER THAN PORTED.

MICCV2 treated the statutory layer as constant and got three components wrong
(`costs.yml` header, measured):

    STT  charged sell-only, when equity DELIVERY attracts it on BOTH legs
    TXN  one rate for two exchanges, and the wrong value
    GST  applied to brokerage alone, not brokerage + SEBI + transaction

Together **+10.04 bps per round trip** — enough to flip its one surviving
seasonality result from +3.70 bps to **-6.36 bps** per occurrence. A cost model
is not bookkeeping around a result; at this effect size it IS the result.

THE SCHEDULE IS VERSIONED, NOT CONSTANT. Rates moved repeatedly across the
2006-2026 sample, so every lookup is point-in-time: the rate in force on the
trade date, not today's. `unverified_periods` in the config names the windows
nobody has reconstructed, and `statutory_cost` returns them alongside the number
rather than burying them — a cost computed from an unverified row is a cost the
reader must be able to discount.

WHAT THIS MODULE DOES NOT DO. It computes no return, ranks nothing and reads no
event. It answers "what does this trade cost" and stops. Decision
[0035](../../docs/decisions/0035-power-may-use-the-full-universe-effects-may-not.md)
puts effect estimates behind the guard; a cost is not an effect, and keeping the
two in separate modules is what stops that line blurring.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import date

import yaml

from src.common.paths import CONFIGS, governance_db

COSTS_YML = CONFIGS / "costs.yml"


def spec() -> dict:
    return yaml.safe_load(COSTS_YML.read_text())


# --- the versioned statutory schedule -----------------------------------------


def load_fee_schedule(env: str | None = None) -> int:
    """Seed `fee_schedule` from costs.yml. Idempotent; returns rows written.

    The table is the queryable form of the config, not a second source of truth:
    it is emptied and rewritten, so the config cannot drift from what a study
    charged. Every row carries its `source_url` and `verified` flag because
    Plan 2 §4.1 requires a study to disclose when its window touches an
    unverified rate.
    """
    rows = spec()["statutory"]
    con = sqlite3.connect(governance_db(env))
    try:
        con.execute("DELETE FROM fee_schedule")
        for r in rows:
            base = r.get("applies_to_base")
            con.execute(
                "INSERT INTO fee_schedule (component, segment, exchange, side,"
                " rate, rate_basis, applies_to_base, effective_from, effective_to,"
                " source_url, source_note, verified, verified_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (r["component"], r["segment"], r.get("exchange"), r["side"],
                 float(r["rate"]), r["rate_basis"],
                 ",".join(base) if isinstance(base, list) else base,
                 r["effective_from"], r.get("effective_to"),
                 r["source_url"], r["source_note"],
                 1 if r.get("verified") else 0,
                 "2026-08-16" if r.get("verified") else None),
            )
        con.commit()
        return len(rows)
    finally:
        con.close()


def _in_force(rows: list[dict], on: date) -> list[dict]:
    """Rows effective on `on`. A rate with no `effective_to` is still current."""
    d = on.isoformat()
    return [
        r for r in rows
        if r["effective_from"] <= d
        and (r.get("effective_to") is None or d <= r["effective_to"])
    ]


@dataclass(frozen=True, slots=True)
class CostBreakdown:
    """Per-leg cost in rupees, itemised. The total is never the only number."""

    turnover: float
    components: dict[str, float]
    unverified: tuple[str, ...] = ()

    @property
    def total(self) -> float:
        return sum(self.components.values())

    @property
    def bps(self) -> float:
        return 10_000 * self.total / self.turnover if self.turnover else 0.0

    def render(self) -> str:
        parts = "  ".join(f"{k} {10_000*v/self.turnover:.2f}"
                          for k, v in sorted(self.components.items())
                          if self.turnover)
        flag = "  [UNVERIFIED RATES IN WINDOW]" if self.unverified else ""
        return f"{self.bps:.2f} bps  ({parts}){flag}"


def statutory_cost(turnover: float, on: date, side: str = "BUY",
                   exchange: str = "NSE", brokerage_rate: float | None = None,
                   segment: str = "EQ_DELIVERY") -> CostBreakdown:
    """One leg's statutory + brokerage cost, at the rates in force on `on`.

    THE THREE CORRECTIONS ARE STRUCTURAL, not commentary:

    - `side='BOTH'` rows charge on BUY and SELL. STT on equity delivery is a
      BOTH row, so it is charged on the buy leg too. The predecessor charged it
      sell-only.
    - `exchange` selects the TXN row. NSE and BSE differ (0.00307% vs 0.00375%)
      and the predecessor used one rate for both.
    - GST is `PCT_OF_BASE` over `applies_to_base = [BROKERAGE, SEBI, TXN]`, so
      it is computed AFTER those and from their sum. The predecessor applied it
      to brokerage alone.
    """
    cfg = spec()
    rate = (cfg["brokerage"]["headline_rate"] if brokerage_rate is None
            else brokerage_rate)
    rows = [r for r in _in_force(cfg["statutory"], on)
            if r["segment"] == segment
            and r["side"] in ("BOTH", side.upper())
            and (r.get("exchange") in (None, exchange))]

    comp: dict[str, float] = {"BROKERAGE": turnover * rate}
    # Pass 1: everything charged on turnover.
    for r in rows:
        if r["rate_basis"] == "PCT_TURNOVER":
            comp[r["component"]] = comp.get(r["component"], 0.0) + turnover * r["rate"]
        elif r["rate_basis"] == "PER_CRORE":
            comp[r["component"]] = comp.get(r["component"], 0.0) + (turnover / 1e7) * r["rate"]
    # Pass 2: percentages OF other components, which must exist first.
    for r in rows:
        if r["rate_basis"] != "PCT_OF_BASE":
            continue
        base_names = r.get("applies_to_base") or []
        if isinstance(base_names, str):
            base_names = [b.strip() for b in base_names.split(",")]
        base = sum(comp.get(b, 0.0) for b in base_names)
        comp[r["component"]] = comp.get(r["component"], 0.0) + base * r["rate"]

    unverified = tuple(
        u["note"] for u in cfg.get("unverified_periods", [])
    ) if any(not r.get("verified") for r in rows) or on.year < 2020 else ()
    return CostBreakdown(turnover, comp, unverified)


def round_trip_bps(turnover: float, on: date, exchange: str = "NSE",
                   brokerage_rate: float | None = None) -> float:
    """Buy + sell, in basis points of one leg's turnover. The comparable number."""
    buy = statutory_cost(turnover, on, "BUY", exchange, brokerage_rate)
    sell = statutory_cost(turnover, on, "SELL", exchange, brokerage_rate)
    return buy.bps + sell.bps


# --- spread -------------------------------------------------------------------


def corwin_schultz_spread(high: list[float], low: list[float]) -> float | None:
    """Corwin-Schultz (2012) high-low spread estimator, as a FRACTION of price.

    Two consecutive sessions' high-low ranges separate the true variance from
    the bid-ask bounce: a two-session range contains one day of extra variance
    but the same single bounce, so the difference identifies the spread.

    Returns None rather than a number when the input cannot support one — fewer
    than two sessions, or a zero range. `costs.yml` sets
    `exclude_zero_range_sessions: true` for a measured reason: H == L means the
    stock was circuit-locked, not that its spread was zero, and treating it as
    zero would make the most illiquid sessions look the cheapest.

    Negative estimates are set to zero per the authors' own recommendation
    (`negative_to_zero: true`), which is a known downward bias in thin names and
    is why `abdi_ranaldo` is kept as a declared cross-check.
    """
    import math

    if len(high) < 2 or len(low) < 2 or len(high) != len(low):
        return None
    est: list[float] = []
    for i in range(1, len(high)):
        h1, l1, h0, l0 = high[i], low[i], high[i - 1], low[i - 1]
        if min(h1, l1, h0, l0) <= 0 or h1 == l1 or h0 == l0:
            continue  # circuit-locked or unusable
        beta = math.log(h0 / l0) ** 2 + math.log(h1 / l1) ** 2
        hc, lc = max(h0, h1), min(l0, l1)
        gamma = math.log(hc / lc) ** 2
        k = 3 - 2 * math.sqrt(2)
        alpha = (math.sqrt(2 * beta) - math.sqrt(beta)) / k - math.sqrt(gamma / k)
        s = 2 * (math.exp(alpha) - 1) / (1 + math.exp(alpha))
        est.append(max(0.0, s) if spec()["spread"]["negative_to_zero"] else s)
    if not est:
        return None
    est.sort()
    trim = spec()["spread"]["winsorise_tails"]
    lo = int(len(est) * trim)
    hi = len(est) - lo
    kept = est[lo:hi] or est
    return sum(kept) / len(kept)


# --- impact -------------------------------------------------------------------


def sqrt_impact(quantity: float, adv: float, sigma_daily: float,
                y: float | None = None) -> float:
    """Square-root market impact as a fraction of price.

        impact = Y * sigma_daily * sqrt(Q / ADV)

    Y is configurable with declared alternates (0.5 / 0.8 / 1.0) because the
    literature does not agree on it, and a result that survives only at the
    friendliest Y is a result about Y. `cost_scenarios` runs all three.

    Returns 0.0 when ADV is unknown or zero: an unmeasurable impact must not
    silently become a free one, so callers get zero AND the event carries an
    explicit reason elsewhere — `institutional_deals_clean` already excludes
    rows with no ADV20 under 'below the ADV20 floor'.
    """
    import math

    if adv <= 0 or quantity <= 0 or sigma_daily <= 0:
        return 0.0
    yy = spec()["impact"]["y_constant"] if y is None else y
    return yy * sigma_daily * math.sqrt(quantity / adv)


# --- regime -------------------------------------------------------------------


def vix_regime_multiplier(vix: float, baseline: list[float]) -> float:
    """Widen costs under stress. 1.0 in calm, 1.5 in the top VIX decile.

    `sigma_daily` in `sqrt_impact` already carries part of the regime; this
    carries the rest — spreads widen with volatility beyond what the impact term
    captures. Interpolated between the two anchors rather than stepped, so an
    event just below the decile boundary is not priced as calm.
    """
    cfg = spec()["regime"]
    calm, stress = cfg["multiplier_calm"], cfg["multiplier_top_decile"]
    if not baseline or vix <= 0:
        return calm
    ordered = sorted(baseline)
    p90 = ordered[int(0.90 * (len(ordered) - 1))]
    p50 = ordered[len(ordered) // 2]
    if vix <= p50:
        return calm
    if vix >= p90:
        return stress
    return calm + (stress - calm) * (vix - p50) / (p90 - p50)


# --- the three reporting levels -----------------------------------------------


@dataclass(frozen=True, slots=True)
class Scenario:
    name: str
    round_trip_bps: float
    impact_bps: float
    spread_bps: float

    @property
    def total_bps(self) -> float:
        return self.round_trip_bps + self.impact_bps + self.spread_bps


@dataclass(frozen=True, slots=True)
class ScenarioSet:
    scenarios: tuple[Scenario, ...] = field(default_factory=tuple)

    def render(self) -> str:
        lines = [f"  {'level':<14}{'statutory':>11}{'impact':>10}{'spread':>9}{'TOTAL':>10}"]
        for s in self.scenarios:
            lines.append(f"  {s.name:<14}{s.round_trip_bps:>11.2f}{s.impact_bps:>10.2f}"
                         f"{s.spread_bps:>9.2f}{s.total_bps:>10.2f}")
        return "\n".join(lines)


def cost_scenarios(turnover: float, on: date, quantity: float, adv: float,
                   sigma_daily: float, spread: float | None = None,
                   exchange: str = "NSE") -> ScenarioSet:
    """Gross / base / pessimistic, per `costs.yml` reporting.levels.

    Plan 2 §4: every result at three levels, so the reader sees how much
    survives friction rather than one number chosen by whoever ran it. The
    levels differ in brokerage, impact Y and participation — all read from the
    config, none hardcoded here.
    """
    cfg = spec()
    levels = cfg["reporting"]["levels"]
    broker = cfg["brokerage"]
    out = []
    for name in ("gross", "base", "pessimistic"):
        lv = levels[name]
        rate = broker["floor_rate"] if lv["brokerage"] == "floor_rate" else broker["headline_rate"]
        rt = round_trip_bps(turnover, on, exchange, rate)
        imp = 10_000 * sqrt_impact(quantity, adv, sigma_daily, lv["y"])
        sp = 10_000 * (spread or 0.0)
        if lv["spread"] == "wider":
            sp *= 1.5
        elif lv["spread"] == "narrower":
            sp *= 0.5
        out.append(Scenario(name, rt, imp, sp))
    return ScenarioSet(tuple(out))


def main() -> int:
    n = load_fee_schedule()
    print(f"COST MODEL (Plan 2 §4)\n  fee_schedule seeded: {n} statutory rows\n")
    today = date.today()
    print("  round-trip statutory cost on Rs 1cr, headline brokerage:")
    for exch in ("NSE", "BSE"):
        print(f"    {exch}  {round_trip_bps(1e7, today, exch):.2f} bps")
    print(f"    NSE at the floor (zero brokerage)  {round_trip_bps(1e7, today, 'NSE', 0.0):.2f} bps")
    print("\n  one buy leg, itemised:")
    print("   ", statutory_cost(1e7, today, "BUY").render())
    print("\n  three reporting levels, Rs 1cr at 5% of ADV, sigma 2.5%, spread 30bps:")
    print(cost_scenarios(1e7, today, quantity=5_000, adv=100_000,
                         sigma_daily=0.025, spread=0.0030).render())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
