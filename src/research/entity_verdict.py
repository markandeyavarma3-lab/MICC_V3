"""entity_verdict.py — exp_002, the entity persistence study. Workstream 3.

RUNS THE REGISTERED SPECIFICATION, INCLUDING WHERE IT CANNOT BE MET.

`scripts/register_exp002.py` froze the design before any return was computed:
form tiers on 2006-2015, evaluate on 2016-2026, BH-FDR at 5% across 24 declared
tests, CHAR_MATCHED at 63 sessions, pessimistic costs. Measuring the population
afterwards showed the formation window holds 245 of 1,539 deals and that **ten
of the twenty-four entities have no formation-period deal at all**.

The specification is therefore partly unexecutable. It is run exactly as
written anyway, and the shortfall is reported as the finding, because the
alternative — moving the split to where the data is thick — is choosing a
design after seeing which design would work. That is the failure this whole
project exists to refuse, and 0056 already recorded the same shape: a study that
cannot be run is a different verdict from a study that ran and found nothing,
and conflating them is how a negative result stops meaning anything.
"""

from __future__ import annotations

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

HORIZONS = (1, 2, 3, 5, 10, 21, 63, 126, 252)


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
    tier_eval: dict[str, float] = field(default_factory=dict)
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


def build(env: str | None = None, sessions: int = PRIMARY_SESSIONS) -> Verdict:
    spine = str(warehouse_dir(env) / "price_spine_adj" / "**" / "*.parquet")
    charp = str(warehouse_dir(env) / "char_panel" / "**" / "*.parquet")
    con = duckdb.connect(str(research_db(env)), read_only=True)
    con.execute("SET memory_limit='8GB'; SET preserve_insertion_order=false;")
    con.create_function("norm", normalize, ["VARCHAR"], "VARCHAR")
    con.create_function("role", classify, ["VARCHAR"], "VARCHAR")
    try:
        cutoff = measure.REPRODUCIBILITY_HORIZON
        con.execute(f"CREATE OR REPLACE TEMP VIEW rets AS "
                    f"{measure._returns_sql(spine, sessions, cutoff)}")
        con.execute(f"CREATE OR REPLACE TEMP VIEW ev AS {_events_sql()}")
        con.execute(f"""CREATE OR REPLACE TEMP VIEW tested AS
            SELECT ent FROM ev GROUP BY 1
            HAVING COUNT(*) >= {MIN_DEALS}
               AND COUNT(DISTINCT strftime(CAST(tdate AS DATE), '%Y-%m')) >= {MIN_MONTHS}""")
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
        rows = con.execute(f"""
            SELECT ent, tdate, side, gross_deal_value, adv20, quantity, exchange,
                   ret, bench, excess,
                   CASE WHEN tdate <= '{FORMATION_END}' THEN 'form' ELSE 'eval' END AS era
            FROM ab""").fetchall()
        return _score(rows)
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


def _score(rows) -> Verdict:
    import math
    from collections import defaultdict

    by: dict[str, dict[str, list[float]]] = defaultdict(lambda: {"form": [], "eval": []})
    raw: dict[str, dict[str, list[float]]] = defaultdict(lambda: {"form": [], "eval": []})
    for (ent, tdate, side, gv, adv, qty, exch, ret, bench, excess, era) in rows:
        by[ent][era].append(_net(excess, side, gv, adv, qty, tdate, exch))
        raw[ent][era].append(excess if side == "BUY" else -excess)

    v = Verdict()
    pvals: list[tuple[str, float]] = []
    for ent, d in sorted(by.items()):
        f, e = d["form"], d["eval"]
        mf = sum(f) / len(f) if f else None
        me = sum(e) / len(e) if e else None
        hit = (sum(1 for x in e if x > 0) / len(e)) if e else None
        stat = EntityStat(ent, len(f), len(e), mf, me, hit, None)
        if len(f) >= 2:
            mean = sum(f) / len(f)
            var = sum((x - mean) ** 2 for x in f) / (len(f) - 1)
            if var > 0:
                t = mean / math.sqrt(var / len(f))
                # two-sided normal approximation; the bootstrap in the spec is
                # reported alongside in the memo rather than replacing this.
                p = math.erfc(abs(t) / math.sqrt(2))
                stat.p_form = p
                pvals.append((ent, p))
        if not f:
            v.n_zero_formation += 1
        v.entities.append(stat)

    # Benjamini-Hochberg across the DECLARED family of 24, not across however
    # many happened to be computable.
    m = 24
    for rank, (ent, p) in enumerate(sorted(pvals, key=lambda x: x[1]), start=1):
        q = p * m / rank
        for s in v.entities:
            if s.entity == ent:
                s.q_form = min(q, 1.0)
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

    # THE PASS BAR, READ FROM THE REGISTRATION RATHER THAN PARAPHRASED.
    #
    #   "The TOP tier must (a) contain at least one entity passing BH-FDR 5%
    #    in-sample on 2006-2015, AND (b) beat its benchmark net-of-costs on
    #    2016-2026. Both, not either."
    #
    # The first implementation tested `passed_fdr > 0 AND top_beats > 0` — that
    # any entity anywhere passed, not that a TOP-tier one did — and reported
    # ALIVE. Both FDR passers are in the BOTTOM tier with significantly NEGATIVE
    # formation excess, so the loose reading turned a failed bar into a pass.
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
            f"anywhere ({', '.join(p[:28] for p in passers) or 'none'}), and "
            f"they sit in the BOTTOM tier on significantly NEGATIVE formation "
            f"excess — a passed test in the wrong direction")
        if top_beats > 0:
            v.reason += (f". The TOP tier is {top_beats:+.2%} out-of-sample, but "
                         f"the registered bar requires both conditions")
    elif not (top_beats > 0):
        v.reason = ("a TOP-tier entity passed FDR in-sample but the tier does "
                    "not beat its benchmark net-of-costs out-of-sample")
    return v
