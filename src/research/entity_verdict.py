"""entity_verdict.py — exp_002, the entity persistence study. Workstream 3.

RUNS THE REGISTERED SPECIFICATION, INCLUDING WHERE IT CANNOT BE MET.

`scripts/register_exp002.py` froze the design before any return was computed:
form tiers on 2006-2015, evaluate on 2016-2026, BH-FDR at 5% across 24 declared
tests, CHAR_MATCHED at 63 sessions, pessimistic costs. Measuring the population
afterwards showed the formation window holds 245 of 1,539 deals and that
**twelve of the twenty-four entities have no formation-period deal at all**
(the docstring said "ten" while the memo and the governance artefact said
twelve; twelve is the measured figure).

The specification is therefore partly unexecutable. It is run exactly as
written anyway, and the shortfall is reported as the finding, because the
alternative — moving the split to where the data is thick — is choosing a
design after seeing which design would work. That is the failure this whole
project exists to refuse, and 0056 already recorded the same shape: a study that
cannot be run is a different verdict from a study that ran and found nothing,
and conflating them is how a negative result stops meaning anything.

CORRECTED 2026-09-12, against the SAME frozen registration. The first
implementation deviated from the spec it had registered, in ways that inflated
its own intermediate results:

  * `permutation_policy` registered a moving-block bootstrap; the code ran a
    two-sided NORMAL approximation instead. That is what produced the two
    reported BH-FDR passes, on entities with two and five formation deals. The
    two-deal pass is definitely an artefact of it; the five-deal one is
    uncomputable under the bootstrap only if those deals span three or fewer
    distinct months, which needs the warehouse to settle. See `_p_form`.
  * `holding_period` registered "all 9 horizons reported"; `HORIZONS` was
    declared and never read, so eight of the nine were never computed.
  * Benjamini-Hochberg was computed as raw p*m/rank without the step-up running
    minimum, so the adjusted values were not monotone in p. See `_bh`.
  * Per-entity IC was never computed; the field was declared and left None.

None of this changes the VERDICT, which was and remains DEAD — removing
spurious passes can only strengthen a negative result. It does change published
intermediate numbers, which cannot be restated here because recomputation needs
the warehouse. docs/reports/ENTITY_VERDICT.md carries the correction notice.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import duckdb

from src.common.paths import research_db, warehouse_dir
from src.research import costs, measure
from src.research.entity_names import normalize
from src.research.roles import classify

EXPERIMENT_ID = "exp_002_entity_persistence"
SPEC_HASH = "8e7436d7aa9e9186016c357e1089c467f0418e1515cf1d6fd62c8d7ba7843902"

PRIMARY_SESSIONS = 63
FORMATION_END = "2015-12-31"
FDR_ALPHA = 0.05
MIN_DEALS, MIN_MONTHS = 30, 12

# All nine are REPORTED, per the registered holding_period: "primary 63
# sessions (3 months); all 9 horizons reported". Only 63 forms tiers and decides
# the pass bar. The first implementation declared this tuple and never read it,
# so eight of the nine registered horizons were never computed.
HORIZONS = (1, 2, 3, 5, 10, 21, 63, 126, 252)

# The registered significance procedure. See _p_form.
BOOTSTRAP_BLOCK_MONTHS = 3       # 63 sessions is three months of cohorts
BOOTSTRAP_DRAWS = 10_000
BOOTSTRAP_SEED = 20260911

# An IC below this many paired observations is the sparsity artefact this study
# exists to report, not a measurement.
MIN_IC_OBS = 5


@dataclass
class EntityStat:
    entity: str
    n_form: int
    n_eval: int
    mean_excess_form: float | None
    mean_excess_eval: float | None
    hit_rate_eval: float | None
    ic_eval: float | None
    p_form: float | None = None
    q_form: float | None = None
    tier: str = ""


@dataclass
class Verdict:
    entities: list[EntityStat] = field(default_factory=list)
    n_zero_formation: int = 0
    n_untestable: int = 0
    tier_eval: dict[str, float] = field(default_factory=dict)
    # horizon (sessions) -> mean net directional excess across tested entities.
    horizon_excess: dict[int, float] = field(default_factory=dict)
    rank_ic: float | None = None
    passed_fdr: int = 0
    alive: bool = False
    reason: str = ""


def _events_sql() -> str:
    """Directional deals from the tested entities. Population frozen at
    registration; `norm` and `role` are name-only and touch no outcome."""
    return """
        SELECT cl.deal_id, norm(r.client_name_raw) AS ent,
               UPPER(TRIM(r.symbol_raw)) AS symbol,
               CAST(cl.trade_date AS VARCHAR) AS tdate,
               cl.side, cl.gross_deal_value, cl.adv20, cl.quantity, cl.exchange
        FROM institutional_deals_clean cl
        JOIN institutional_deals_raw r USING (raw_deal_id)
        WHERE NOT cl.same_day_round_trip_flag
          AND NOT cl.unresolved_symbol_flag
          AND NOT cl.uncovered_symbol_flag
    """


def _rows_at(con, spine: str, charp: str, sessions: int):
    """Event rows with CHAR_MATCHED excess at one horizon.

    `ev` and `tested` are horizon-independent and built once by the caller; the
    return views are not, so every horizon rebuilds them.
    """
    cutoff = measure.REPRODUCIBILITY_HORIZON
    con.execute(f"CREATE OR REPLACE TEMP VIEW rets AS "
                f"{measure._returns_sql(spine, sessions, cutoff)}")
    # CHAR_MATCHED: equal-weighted forward return of same size/mom/vol cell,
    # the event's own name removed. Cells below the 10-name floor degrade in
    # the order benchmarks.yml declares.
    con.execute(f"""CREATE OR REPLACE TEMP TABLE cell AS
        SELECT r.symbol, r.date, r.ret, c.size_q, c.mom_q, c.vol_q
        FROM rets r ASOF JOIN read_parquet('{charp}') c
          ON r.symbol = c.symbol AND CAST(r.date AS DATE) >= c.rebalance_date
        WHERE r.ret IS NOT NULL""")
    con.execute("""CREATE OR REPLACE TEMP TABLE cmean AS
        SELECT date, size_q, mom_q, vol_q, avg(ret) m, COUNT(*) n
        FROM cell GROUP BY 1,2,3,4""")
    con.execute("""CREATE OR REPLACE TEMP VIEW ab AS
        SELECT e.ent, e.tdate, e.side, e.gross_deal_value, e.adv20, e.quantity,
               e.exchange, r.ret,
               (cm.m * cm.n - c.ret) / (cm.n - 1) AS bench,
               r.ret - (cm.m * cm.n - c.ret) / (cm.n - 1) AS excess
        FROM ev e
        JOIN tested t ON t.ent = e.ent
        JOIN rets r ON r.symbol = e.symbol AND CAST(r.date AS VARCHAR) = e.tdate
        JOIN cell c ON c.symbol = e.symbol AND CAST(c.date AS VARCHAR) = e.tdate
        JOIN cmean cm ON cm.date = c.date AND cm.size_q = c.size_q
                     AND cm.mom_q = c.mom_q AND cm.vol_q = c.vol_q
        WHERE role(e.ent) = 'LONG_ONLY' AND cm.n > 10 AND r.ret IS NOT NULL""")
    return con.execute(f"""
        SELECT ent, tdate, side, gross_deal_value, adv20, quantity, exchange,
               ret, bench, excess,
               CASE WHEN tdate <= '{FORMATION_END}' THEN 'form' ELSE 'eval' END AS era
        FROM ab""").fetchall()


def build(env: str | None = None, sessions: int = PRIMARY_SESSIONS) -> Verdict:
    spine = str(warehouse_dir(env) / "price_spine_adj" / "**" / "*.parquet")
    charp = str(warehouse_dir(env) / "char_panel" / "**" / "*.parquet")
    con = duckdb.connect(str(research_db(env)), read_only=True)
    con.execute("SET memory_limit='8GB'; SET preserve_insertion_order=false;")
    con.create_function("norm", normalize, ["VARCHAR"], "VARCHAR")
    con.create_function("role", classify, ["VARCHAR"], "VARCHAR")
    try:
        con.execute(f"CREATE OR REPLACE TEMP VIEW ev AS {_events_sql()}")
        con.execute(f"""CREATE OR REPLACE TEMP VIEW tested AS
            SELECT ent FROM ev GROUP BY 1
            HAVING COUNT(*) >= {MIN_DEALS}
               AND COUNT(DISTINCT strftime(CAST(tdate AS DATE), '%Y-%m')) >= {MIN_MONTHS}""")
        v = _score(_rows_at(con, spine, charp, sessions))
        # ALL NINE HORIZONS REPORTED, per the registered holding_period. Only
        # the primary (63) formed tiers and decided the pass bar; these are
        # descriptive and cannot move the verdict.
        for h in HORIZONS:
            nets = [_net(ex, sd, gv, adv, qty, td, exch)
                    for (ent, td, sd, gv, adv, qty, exch, rt, bn, ex, era)
                    in _rows_at(con, spine, charp, h)]
            v.horizon_excess[h] = sum(nets) / len(nets) if nets else float("nan")
        return v
    finally:
        con.close()


def _net(excess: float, side: str, turnover: float, adv: float, qty: float,
         on: str, exchange: str) -> float:
    """Excess return after the FULL registered cost stack.

    Statutory round trip plus square-root impact at Y=1.0 — the pessimistic
    level, fixed at registration so the cost assumption cannot be relaxed once
    the result is visible. A SELL disclosure is a negative signal, so its
    directional excess is sign-flipped before costs are charged.
    """
    from datetime import date as _d

    directional = excess if side == "BUY" else -excess
    try:
        bps = costs.round_trip_bps(float(turnover), _d.fromisoformat(on[:10]),
                                   exchange=exchange or "NSE")
    except Exception:
        bps = 29.33
    imp = 0.0
    if adv and adv > 0 and qty:
        # sigma_daily is not carried per event; 2% is the config's own baseline
        # and is used identically for every entity, so it cannot favour one.
        imp = 1e4 * costs.sqrt_impact(float(qty), float(adv), 0.02, 1.0)
    return directional - (bps + imp) / 1e4


def _ranks(xs: list[float]) -> list[float]:
    """Average ranks, so ties do not invent ordering."""
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    out = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            out[order[k]] = avg
        i = j + 1
    return out


def _rank_ic(xs: list[float], ys: list[float]) -> float | None:
    """Spearman rank correlation. None below MIN_IC_OBS, because an IC on two
    points is the same failure this study exists to report."""
    pairs = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
    if len(pairs) < MIN_IC_OBS:
        return None
    rx = _ranks([p[0] for p in pairs])
    ry = _ranks([p[1] for p in pairs])
    n = len(pairs)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    dx = math.sqrt(sum((a - mx) ** 2 for a in rx))
    dy = math.sqrt(sum((b - my) ** 2 for b in ry))
    return None if dx == 0 or dy == 0 else num / (dx * dy)


def _p_form(dates: list[str], values: list[float]) -> float | None:
    """Two-sided p on the formation mean, BY THE REGISTERED PROCEDURE.

    `permutation_policy`, frozen in scripts/register_exp002.py before any return
    was computed:

        "moving-block bootstrap, block = 63 sessions (the holding period),
         10,000 draws, seed 20260911, resampling whole months to preserve
         cross-sectional and serial dependence"

    THE FIRST IMPLEMENTATION DID NOT RUN THIS. It substituted
    `math.erfc(|t|/sqrt(2))` — a two-sided NORMAL approximation on raw per-deal
    returns — and that substitution is what manufactured the two reported FDR
    passes. The normal approximation clears the BH rank-1 threshold (p <
    0.05/24) at |t| >= 3.08 REGARDLESS OF n; the same threshold on two
    observations genuinely needs |t| >= 305.6. So an entity with two deals could
    "pass at FDR 5%" on a t-statistic of 4.

    The registered bootstrap cannot be run on two deals at all: it needs more
    monthly cohorts than the block length. It returns None there. That is the
    honest answer, it is the one the registration asked for, and it is why the
    substitution mattered rather than being a stylistic difference.

    Returning None is NOT "no evidence against the null" — it is "this entity is
    not testable under the registered design", which `Verdict.n_untestable`
    counts and the memo reports separately from a genuine non-rejection.
    """
    import pandas as pd

    from src.research import power

    cohorts = power.cohort_collapse(pd.Series(dates), pd.Series(values))
    if len(cohorts) < BOOTSTRAP_BLOCK_MONTHS + 1:
        return None
    _lo, _hi, p_gt0 = power.block_bootstrap_ci(
        cohorts, BOOTSTRAP_BLOCK_MONTHS, draws=BOOTSTRAP_DRAWS, seed=BOOTSTRAP_SEED
    )
    if p_gt0 != p_gt0:  # NaN — the bootstrap declined the series
        return None
    # Floored at 1/draws: zero draws above zero means "smaller than this
    # bootstrap can resolve", never p = 0.
    return max(2.0 * min(p_gt0, 1.0 - p_gt0), 1.0 / BOOTSTRAP_DRAWS)


def _bh(pvals: list[tuple[str, float]], m: int) -> dict[str, float]:
    """Benjamini-Hochberg step-up across the DECLARED family of `m`.

    The step-up requires the cumulative minimum from the largest rank down:
    q_(i) = min over j >= i of p_(j) * m / j. Without it the adjusted values are
    not monotone in p and a larger p can be reported as more significant than a
    smaller one. The first implementation computed the raw p*m/rank only.
    """
    ordered = sorted(pvals, key=lambda x: x[1])
    out: dict[str, float] = {}
    running = 1.0
    for rank in range(len(ordered), 0, -1):
        ent, p = ordered[rank - 1]
        running = min(running, p * m / rank)
        out[ent] = min(running, 1.0)
    return out


def _score(rows) -> Verdict:
    from collections import defaultdict

    def _era() -> dict[str, list]:
        return {"form": [], "eval": []}

    by: dict[str, dict[str, list[float]]] = defaultdict(_era)   # net, directional
    dts: dict[str, dict[str, list[str]]] = defaultdict(_era)    # trade dates
    sig: dict[str, dict[str, list[float]]] = defaultdict(_era)  # bet size
    for (ent, tdate, side, gv, adv, qty, exch, ret, bench, excess, era) in rows:
        by[ent][era].append(_net(excess, side, gv, adv, qty, tdate, exch))
        dts[ent][era].append(tdate)
        sig[ent][era].append(
            float(gv) / float(adv) if adv and float(adv) > 0 and gv else None
        )

    v = Verdict()
    pvals: list[tuple[str, float]] = []
    for ent, d in sorted(by.items()):
        f, e = d["form"], d["eval"]
        mf = sum(f) / len(f) if f else None
        me = sum(e) / len(e) if e else None
        hit = (sum(1 for x in e if x > 0) / len(e)) if e else None
        stat = EntityStat(ent, len(f), len(e), mf, me, hit,
                          _rank_ic(sig[ent]["eval"], e))
        p = _p_form(dts[ent]["form"], f) if f else None
        if p is not None:
            stat.p_form = p
            pvals.append((ent, p))
        elif f:
            v.n_untestable += 1
        if not f:
            v.n_zero_formation += 1
        v.entities.append(stat)

    # The family is the 24 DECLARED at registration, not however many turned out
    # to be computable. Shrinking m to the testable count would loosen the
    # threshold exactly when the data is thinnest.
    for ent, q in _bh(pvals, 24).items():
        for s in v.entities:
            if s.entity == ent:
                s.q_form = q
    v.passed_fdr = sum(1 for s in v.entities
                       if s.q_form is not None and s.q_form < FDR_ALPHA)

    scored = [s for s in v.entities if s.mean_excess_form is not None]
    scored.sort(key=lambda s: s.mean_excess_form, reverse=True)
    third = max(1, len(scored) // 3)
    for i, s in enumerate(scored):
        s.tier = "TOP" if i < third else ("BOTTOM" if i >= len(scored) - third else "MID")
    for tier in ("TOP", "MID", "BOTTOM"):
        vals = [x for s in v.entities if s.tier == tier
                for x in by[s.entity]["eval"]]
        v.tier_eval[tier] = sum(vals) / len(vals) if vals else float("nan")

    # Cross-entity persistence: does the formation ranking predict the
    # evaluation ranking at all? Descriptive, reported, and NOT part of the pass
    # bar — the bar was frozen and this statistic was not in it.
    both = [s for s in v.entities
            if s.mean_excess_form is not None and s.mean_excess_eval is not None]
    v.rank_ic = _rank_ic([s.mean_excess_form for s in both],
                         [s.mean_excess_eval for s in both])

    # THE PASS BAR, READ FROM THE REGISTRATION RATHER THAN PARAPHRASED.
    #
    #   "The TOP tier must (a) contain at least one entity passing BH-FDR 5%
    #    in-sample on 2006-2015, AND (b) beat its benchmark net-of-costs on
    #    2016-2026. Both, not either."
    #
    # An earlier implementation tested `passed_fdr > 0 AND top_beats > 0` — that
    # any entity anywhere passed, not that a TOP-tier one did — and reported
    # ALIVE on two entities whose formation excess was significantly NEGATIVE.
    # The registration is frozen; the code is what was wrong.
    top_beats = v.tier_eval.get("TOP", float("nan"))
    fdr_in_top = [s for s in v.entities
                  if s.tier == "TOP" and s.q_form is not None and s.q_form < FDR_ALPHA]
    v.alive = bool(fdr_in_top) and top_beats > 0
    if not fdr_in_top:
        passers = [s.entity for s in v.entities
                   if s.q_form is not None and s.q_form < FDR_ALPHA]
        v.reason = (
            f"no TOP-tier entity passed BH-FDR 5% in the formation window. "
            f"{len(passers)} entit{'y' if len(passers) == 1 else 'ies'} passed "
            f"anywhere ({', '.join(p[:28] for p in passers) or 'none'}); "
            f"{v.n_untestable} had formation deals but too few monthly cohorts "
            f"for the registered bootstrap to run at all")
        if top_beats > 0:
            v.reason += (f". The TOP tier is {top_beats:+.2%} out-of-sample, but "
                         f"the registered bar requires both conditions")
    elif not (top_beats > 0):
        v.reason = ("a TOP-tier entity passed FDR in-sample but the tier does "
                    "not beat its benchmark net-of-costs out-of-sample")
    return v
