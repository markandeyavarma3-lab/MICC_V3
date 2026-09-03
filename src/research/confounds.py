"""confounds.py — the standing checklist, run on EXPLORE, charged to a family.

WHY THIS FILE EXISTS AND WHY IT IS LATE. `configs/confounds.yml` has declared a
mandatory nine-item checklist for event studies since 2026-08-18. Nothing ran
it. Every power verdict this project has produced (0038, 0043, 0044, 0046, 0050)
measured DISPERSION only, which decision 0035 permits on the full universe
precisely because dispersion cannot distinguish a true effect from a false one.

The moment a confound is measured, that changes. A confound answer IS an effect
estimate — "how much of the effect survives vol-matching" is a statement about
the effect — and 0035 is explicit that every one of them charges its family.
So this is the first module in the project that legitimately spends trials, and
`family_charge` stops being empty because the work finally warranted it, not
because the plumbing was tidied.

EXPLORE ONLY, AND THAT IS NOT A COMPROMISE. `split.yml` gives EXPLORE 30% of
names for exactly this: looking freely, without spending CONFIRM. Running the
checklist here costs one family charge and no confirmatory power. Reading
CONFIRM to make the numbers bigger would spend the only stratum that can
eventually settle the question, to answer a diagnostic. The n is smaller and
the honesty is the point.

WHAT A CONFOUND RESULT IS NOT. None of these verdicts says the sell effect is
real. 0044 established the effect is 4x the plausible bound and 0050 that no
population is powered; the checklist answers a different question — whether the
apparent effect has an ordinary explanation. A confound that fails to explain it
does not promote it to a finding. Only a registered study can do that.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import duckdb
import yaml

from src.common.paths import CONFIGS, SEED, research_db, warehouse_dir
from src.research import measure, split

CONFOUNDS_YML = CONFIGS / "confounds.yml"
PIT_UNIVERSE = SEED / "pit_universe.parquet"

#: The population under test. Sells, same filters every other study used.
SELL_EVENTS = """
    SELECT CAST(cl.trade_date AS VARCHAR) AS tdate, UPPER(TRIM(r.symbol_raw)) AS symbol
    FROM institutional_deals_clean cl
    JOIN institutional_deals_raw r USING (raw_deal_id)
    WHERE cl.side = 'SELL'
      AND NOT cl.same_day_round_trip_flag
      AND cl.deal_value_to_adv20 BETWEEN 0.005 AND 0.50
      AND cl.gross_deal_value >= 1e7
      AND NOT cl.unresolved_symbol_flag
      AND NOT cl.uncovered_symbol_flag
"""


def spec() -> dict:
    return yaml.safe_load(CONFOUNDS_YML.read_text())


@dataclass
class Result:
    confound_id: str
    verdict: str                 # MEASURED | NOT_APPLICABLE
    headline: str
    detail: list[str] = field(default_factory=list)
    reason: str = ""             # only for NOT_APPLICABLE

    def render(self) -> str:
        mark = "  --" if self.verdict == "NOT_APPLICABLE" else "  ok"
        out = [f"{mark}  {self.confound_id:<24}{self.headline}"]
        out += [f"        {d}" for d in self.detail]
        if self.reason:
            out.append(f"        REASON: {self.reason}")
        return "\n".join(out)


def _explore_symbols(con) -> set[str]:
    """Names in the EXPLORE stratum. Computed in Python because `split.assign`
    is the single source of truth for the partition and must not be reimplemented
    in SQL — a second implementation is a second answer."""
    syms = [r[0] for r in con.execute(
        f"SELECT DISTINCT symbol FROM ({SELL_EVENTS})").fetchall()]
    return {s for s in syms if split.assign(s)[0] == "EXPLORE"}


def run(env: str | None = None, sessions: int = 252) -> list[Result]:
    spine = str(warehouse_dir(env) / "price_spine_adj" / "**" / "*.parquet")
    con = duckdb.connect(str(research_db(env)), read_only=True)
    con.execute("SET memory_limit='8GB'; SET preserve_insertion_order=false;")
    out: list[Result] = []
    try:
        con.execute(f"CREATE OR REPLACE TEMP VIEW rets AS "
                    f"{measure._returns_sql(spine, sessions, measure.REPRODUCIBILITY_HORIZON)}")
        con.execute("CREATE OR REPLACE TEMP VIEW mkt AS "
                    "SELECT date, avg(ret) m FROM rets GROUP BY 1")
        explore = _explore_symbols(con)
        con.execute("CREATE OR REPLACE TEMP TABLE ex_syms (symbol VARCHAR)")
        con.executemany("INSERT INTO ex_syms VALUES (?)", [(s,) for s in explore])
        con.execute(f"""CREATE OR REPLACE TEMP VIEW ev AS
            SELECT e.* FROM ({SELL_EVENTS}) e JOIN ex_syms u USING (symbol)""")
        con.execute("""CREATE OR REPLACE TEMP VIEW ab AS
            SELECT ev.tdate, ev.symbol, r.ret - m.m AS ab, r.adv20
            FROM ev JOIN rets r ON r.symbol = ev.symbol AND CAST(r.date AS VARCHAR) = ev.tdate
                    JOIN mkt m ON m.date = r.date""")

        n, raw = con.execute("SELECT COUNT(*), avg(ab) FROM ab").fetchone()
        out.append(Result("_baseline", "MEASURED",
                          f"EXPLORE sell events n={n:,}, raw effect {raw:+.2%}"))

        out.append(_microstructure(con, raw))
        out.append(_volatility(con, env, raw))
        out.append(_size(con, env, raw))
        out.append(_momentum(con, spine, raw))
        out.append(_liquidity(con))
        out.append(_time_concentration(con))
        out.append(_sector())
        out.append(_survivorship(con, spine))
        out.append(_roundtrip(con, spine, explore))
    finally:
        con.close()
    return out


def _microstructure(con, raw: float) -> Result:
    """Random stocks on the IDENTICAL dates. 2026-08-16 precedent: 71% of the
    apparent 1-day bulk effect was open-to-close drift any stock would show."""
    ctrl = con.execute("""
        SELECT avg(r.ret - m.m) FROM rets r JOIN mkt m ON m.date = r.date
        WHERE CAST(r.date AS VARCHAR) IN (SELECT DISTINCT tdate FROM ev)
    """).fetchone()[0]
    share = (ctrl / raw * 100) if raw else 0.0
    return Result("microstructure", "MEASURED",
                  f"control {ctrl:+.2%} on identical dates -> explains {share:.1f}% of raw",
                  [f"event-specific residual {raw - ctrl:+.2%}"])


def _volatility(con, env, raw: float) -> Result:
    """Vol-matched peers. Deal names move more in both directions, so an
    unmatched comparison flatters any negative result."""
    ch = str(warehouse_dir(env) / "char_panel" / "**" / "*.parquet")
    r = con.execute(f"""
        WITH cp AS (SELECT symbol, rebalance_date, vol_q FROM read_parquet('{ch}')),
        ev_q AS (
            SELECT a.tdate, a.symbol, a.ab,
                   (SELECT vol_q FROM cp WHERE cp.symbol=a.symbol
                     AND CAST(cp.rebalance_date AS VARCHAR) <= a.tdate
                     ORDER BY cp.rebalance_date DESC LIMIT 1) AS vq
            FROM ab a),
        peers AS (
            SELECT r.date, r.ret - m.m AS pab,
                   (SELECT vol_q FROM cp WHERE cp.symbol=r.symbol
                     AND CAST(cp.rebalance_date AS VARCHAR) <= CAST(r.date AS VARCHAR)
                     ORDER BY cp.rebalance_date DESC LIMIT 1) AS vq
            FROM rets r JOIN mkt m ON m.date=r.date
            WHERE CAST(r.date AS VARCHAR) IN (SELECT DISTINCT tdate FROM ev))
        SELECT (SELECT avg(ab) FROM ev_q WHERE vq IS NOT NULL),
               (SELECT avg(pab) FROM peers p WHERE p.vq IN
                  (SELECT DISTINCT vq FROM ev_q WHERE vq IS NOT NULL))
    """).fetchone()
    ev_eff, peer_eff = r
    if ev_eff is None or peer_eff is None:
        return Result("volatility", "MEASURED", "insufficient vol_q coverage to match")
    return Result("volatility", "MEASURED",
                  f"vol-matched peers {peer_eff:+.2%}, residual {ev_eff - peer_eff:+.2%}",
                  [f"event effect within matched tiers {ev_eff:+.2%}"])


def _size(con, env, raw: float) -> Result:
    """Size quintile from the PIT characteristic panel. confounds.yml notes this
    is a POWER LEVER as well as a control — a crude size match cut cohort SD
    8.55% -> 5.91% for Finding 001."""
    ch = str(warehouse_dir(env) / "char_panel" / "**" / "*.parquet")
    rows = con.execute(f"""
        WITH cp AS (SELECT symbol, rebalance_date, size_q FROM read_parquet('{ch}')),
        q AS (SELECT a.ab,
                (SELECT size_q FROM cp WHERE cp.symbol=a.symbol
                  AND CAST(cp.rebalance_date AS VARCHAR) <= a.tdate
                  ORDER BY cp.rebalance_date DESC LIMIT 1) AS sq
              FROM ab a)
        SELECT sq, COUNT(*), avg(ab) FROM q WHERE sq IS NOT NULL GROUP BY 1 ORDER BY 1
    """).fetchall()
    if not rows:
        return Result("size", "MEASURED", "no size_q coverage for these events")
    detail = [f"size_q {int(s)}: n={c:,} effect {e:+.2%}" for s, c, e in rows]
    spread = max(e for _, _, e in rows) - min(e for _, _, e in rows)
    return Result("size", "MEASURED",
                  f"effect spans {spread:.2%} across size quintiles", detail)


def _momentum(con, spine: str, raw: float) -> Result:
    """Pre-event 21-session return against the forward window. Monotonic
    quintiles implicate reversal; a U-shape does not (2026-08-16 precedent:
    correlation +0.008, U-shaped -> reversal rejected)."""
    r = con.execute(f"""
        WITH px AS (SELECT symbol, date, close,
                      ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY date) i
                    FROM read_parquet('{spine}') WHERE close > 0),
        pre AS (SELECT symbol, date,
                  close / LAG(close, 21) OVER (PARTITION BY symbol ORDER BY i) - 1 AS pre21
                FROM px),
        j AS (SELECT a.ab, p.pre21 FROM ab a
              JOIN pre p ON p.symbol=a.symbol AND CAST(p.date AS VARCHAR)=a.tdate
              WHERE p.pre21 IS NOT NULL),
        qq AS (SELECT ab, pre21, NTILE(5) OVER (ORDER BY pre21) q FROM j)
        SELECT (SELECT corr(pre21, ab) FROM j),
               list(struct_pack(q := q, n := n, e := e))
        FROM (SELECT q, COUNT(*) n, avg(ab) e FROM qq GROUP BY 1 ORDER BY 1)
    """).fetchone()
    corr, quints = r
    detail = [f"pre-return quintile {d['q']}: n={d['n']:,} effect {d['e']:+.2%}"
              for d in (quints or [])]
    effs = [d["e"] for d in (quints or [])]
    monotonic = effs == sorted(effs) or effs == sorted(effs, reverse=True)
    shape = "MONOTONIC (reversal implicated)" if monotonic else "non-monotonic (reversal not implicated)"
    return Result("momentum_reversal", "MEASURED",
                  f"corr(pre21, forward) {corr:+.4f}; quintiles {shape}", detail)


def _liquidity(con) -> Result:
    """top100 / top500_ex100 / off500 by the PIT universe's own ranks. An effect
    living only in off-500 names is an effect you cannot take."""
    if not PIT_UNIVERSE.exists():
        return Result("liquidity", "MEASURED", "pit_universe.parquet absent")
    rows = con.execute(f"""
        WITH pu AS (SELECT symbol, rebal_date, top100, top500 FROM read_parquet('{PIT_UNIVERSE}')),
        t AS (SELECT a.ab,
                (SELECT CASE WHEN top100=1 THEN 'top100'
                             WHEN top500=1 THEN 'top500_ex100' ELSE 'off500' END
                 FROM pu WHERE pu.symbol=a.symbol AND CAST(pu.rebal_date AS VARCHAR) <= a.tdate
                 ORDER BY pu.rebal_date DESC LIMIT 1) AS tier
              FROM ab a)
        SELECT tier, COUNT(*), avg(ab) FROM t WHERE tier IS NOT NULL GROUP BY 1
    """).fetchall()
    if not rows:
        return Result("liquidity", "MEASURED", "no PIT universe coverage for these events")
    detail = [f"{t:<14} n={c:,} effect {e:+.2%}" for t, c, e in rows]
    tradable = [e for t, c, e in rows if t != "off500"]
    return Result("liquidity", "MEASURED",
                  f"{len(rows)} tiers; effect present in tradable tiers: "
                  f"{'yes' if tradable and min(tradable) < 0 else 'no'}", detail)


def _time_concentration(con) -> Result:
    """Era split. A result carried by one regime is a regime observation."""
    rows = con.execute("""
        SELECT CASE WHEN tdate < '2011-01-01' THEN '2006-10'
                    WHEN tdate < '2016-01-01' THEN '2011-15'
                    WHEN tdate < '2021-01-01' THEN '2016-20'
                    ELSE '2021-26' END era,
               COUNT(*), avg(ab) FROM ab GROUP BY 1 ORDER BY 1
    """).fetchall()
    detail = [f"{e:<9} n={c:,} effect {v:+.2%}" for e, c, v in rows]
    signs = {(v < 0) for _, _, v in rows}
    return Result("time_concentration", "MEASURED",
                  f"{len(rows)} eras; sign "
                  f"{'consistent' if len(signs) == 1 else 'INCONSISTENT across eras'}",
                  detail)


def _sector() -> Result:
    """NOT_APPLICABLE, declared in writing per confounds.yml skip_policy."""
    return Result(
        "sector_concentration", "NOT_APPLICABLE",
        "cannot be measured — sector_history holds 0 rows",
        reason="Plan 1 step 3.5 (sector_history, point-in-time sectors) is "
               "SPECIFIED and unbuilt, so no PIT sector exists to compute shares "
               "against. This is a REAL GAP, not an argument that sector does not "
               "matter: confounds.yml calls the leave-one-sector-out re-run "
               "'cheap, and it has killed real-looking results elsewhere'. Any "
               "registration of a sell study must either build 3.5 first or "
               "disclose this confound as unmeasured.")


def _survivorship(con, spine: str) -> Result:
    """Dead names must be in the sample. The predecessor's 45% attrition looked
    like survivorship and was naming mismatch; both are excluded separately."""
    dead = con.execute(f"""
        SELECT COUNT(*) FROM (
          SELECT symbol, MAX(date) d FROM read_parquet('{spine}') GROUP BY 1)
        WHERE d < '2026-08-01'
    """).fetchone()[0]
    ev_dead = con.execute(f"""
        WITH last AS (SELECT symbol, MAX(date) d FROM read_parquet('{spine}') GROUP BY 1)
        SELECT COUNT(*) FROM ab a JOIN last l USING (symbol) WHERE l.d < '2026-08-01'
    """).fetchone()[0]
    return Result("survivorship", "MEASURED",
                  f"spine carries {dead:,} dead names; {ev_dead:,} EXPLORE sell "
                  f"events are on names that later stopped trading",
                  ["delisting recovery factor is NOT applied — Plan 3 step 6.4 unbuilt"])


def _roundtrip(con, spine: str, explore: set[str]) -> Result:
    """PROP_HFT sensitivity. A filter touching 44% of the data must be visible."""
    r = con.execute("""
        SELECT
          (SELECT COUNT(*) FROM ab),
          (SELECT COUNT(*) FROM institutional_deals_clean cl
             JOIN institutional_deals_raw rw USING (raw_deal_id)
           WHERE cl.side='SELL' AND cl.same_day_round_trip_flag)
    """).fetchone()
    return Result("same_day_roundtrip", "MEASURED",
                  f"round trips already excluded upstream; {r[1]:,} sell rows carry "
                  f"the flag and never reach this population",
                  [f"population after exclusion n={r[0]:,}"])


def main() -> int:
    from src.research import families

    print("CONFOUNDS CHECKLIST — sell events, EXPLORE stratum, 12-month horizon")
    print("  0035: a confound answer IS an effect estimate, so this charges a family")
    print()
    results = run()
    for r in results:
        print(r.render())

    measured = [r for r in results if r.verdict == "MEASURED" and not r.confound_id.startswith("_")]
    skipped = [r for r in results if r.verdict == "NOT_APPLICABLE"]
    print(f"\n  {len(measured)} measured, {len(skipped)} NOT_APPLICABLE")

    charge = families.commit_charge(
        "TRACK_D_DEALS", trials_added=len(measured),
        description=f"confounds.yml checklist on EXPLORE sell events, "
                    f"{len(measured)} effect estimates",
    )
    print(f"  charged TRACK_D_DEALS: +{len(measured)} trials -> {charge.trials_after}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
