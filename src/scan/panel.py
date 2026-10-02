"""panel.py — the session x security panel Track S signals are computed on.
Plan 4 §7, Plan 3 step 6S.5.

ONE ROW PER SESSION, ONE COLUMN PER IDENTIFIED SECURITY. Prices come through
`measure.identified_px_ctes`, the one rule for "which security is this price
row" (decision 0061), so a renamed company is one column and a recycled
ticker is two. Arrays are float32: a 21-year panel of ~4,400 securities is
~95 MB per field.

THE UNIVERSE IS POINT-IN-TIME. A security is in the scan on session t only if
it was in the top 500 by ADV at the most recent monthly rebalance on or before
t (seed `pit_universe`, 2005-02 .. 2026-06). Signals are still COMPUTED on
every security — a 252-session lookback needs the history before a name
entered — and only RANKED inside the universe. scan.yml's floor of 100 names a
date is checked by the IC.

WHAT IS DELIBERATELY NOT LOADED.
  shareholding (SHP) changes   exp_004's own signal. Scanning it before exp_004
                               is registered would look at that study's
                               signal-return link with nothing frozen.
  insider trades               begin 2016-01: no explore-period data at all.
Institutional inputs are bulk/block deals only (scan.yml family `institutional`),
excluding PROP_HFT participants and same-day round trips — the two the mart
already says are not institutional conviction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import numpy as np

from src.common.paths import SEED, research_db, warehouse_dir
from src.research.measure import identified_px_ctes

FIELDS = ("open", "high", "low", "close", "volume")


@dataclass
class Panel:
    dates: list[date]
    ids: np.ndarray                      # security_id per column
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray
    universe: np.ndarray                 # bool, T x N
    deal_buy: np.ndarray                 # rupee value bought in disclosed deals, T x N
    deal_sell: np.ndarray
    extra: dict = field(default_factory=dict)

    @property
    def shape(self) -> tuple[int, int]:
        return self.close.shape

    def log_returns(self) -> np.ndarray:
        with np.errstate(divide="ignore", invalid="ignore"):
            r = np.log(self.close[1:] / self.close[:-1])
        return np.vstack([np.full((1, self.shape[1]), np.nan, dtype=np.float32), r]).astype(np.float32)


def load(env: str | None = None, start: date = date(2005, 1, 1), end: date | None = None) -> Panel:
    """Read the panel for sessions in [start, end] from the warehouse."""
    import duckdb

    spine = str(warehouse_dir(env) / "price_spine_adj" / "**" / "*.parquet")
    cut = f" AND CAST(date AS DATE) <= DATE '{end}'" if end else ""
    con = duckdb.connect(str(research_db(env)), read_only=True)
    try:
        con.execute(f"""CREATE TEMP TABLE px AS
            WITH {identified_px_ctes(spine)}
            SELECT s.security_id, s.symbol, CAST(s.date AS DATE) AS d, s.open, s.close, s.volume,
                   p.high, p.low
            FROM sec s JOIN read_parquet('{spine}') p
              ON UPPER(TRIM(p.symbol)) = s.symbol AND p.date = s.date
            WHERE CAST(s.date AS DATE) >= DATE '{start}'{cut}""")
        dates = [r[0] for r in con.execute("SELECT DISTINCT d FROM px ORDER BY d").fetchall()]
        ids = np.array([r[0] for r in con.execute(
            "SELECT DISTINCT security_id FROM px ORDER BY 1").fetchall()], dtype=np.int64)
        di = {d: i for i, d in enumerate(dates)}
        ii = {int(s): j for j, s in enumerate(ids)}
        T, N = len(dates), len(ids)
        arrays = {f: np.full((T, N), np.nan, dtype=np.float32) for f in FIELDS}
        rows = con.execute(f"SELECT d, security_id, {', '.join(FIELDS)} FROM px").fetchnumpy()
        t = np.array([di[x] for x in rows["d"].astype("datetime64[D]").astype(object)])
        j = np.array([ii[int(x)] for x in rows["security_id"]])
        for f in FIELDS:
            arrays[f][t, j] = rows[f].astype(np.float32)

        # Point-in-time top 500, carried forward from each monthly rebalance.
        uni = np.zeros((T, N), dtype=bool)
        pit = con.execute(f"""
            SELECT u.rebal_date, x.security_id
            FROM read_parquet('{SEED / "pit_universe.parquet"}') u
            JOIN px x ON x.symbol = UPPER(TRIM(u.symbol)) AND x.d = CAST(u.rebal_date AS DATE)
            WHERE u.top500 = 1""").fetchall()
        by_reb: dict = {}
        for d, s in pit:
            by_reb.setdefault(d, set()).add(int(s))
        rebs = sorted(by_reb)
        k = -1
        for ti, d in enumerate(dates):
            while k + 1 < len(rebs) and rebs[k + 1] <= d:
                k += 1
            if k >= 0:
                cols = [ii[s] for s in by_reb[rebs[k]] if s in ii]
                uni[ti, cols] = True

        buy = np.zeros((T, N), dtype=np.float32)
        sell = np.zeros((T, N), dtype=np.float32)
        for d, s, side, v in con.execute("""
                SELECT trade_date, security_id, side, SUM(gross_deal_value)
                FROM institutional_deals_clean
                WHERE security_id IS NOT NULL
                  AND COALESCE(ineligibility_reason, '') NOT IN
                      ('same-day round trip', 'PROP_HFT participant', 'unparseable side',
                       'unparseable quantity or price')
                GROUP BY 1, 2, 3""").fetchall():
            if d in di and int(s) in ii:
                (buy if side == "BUY" else sell)[di[d], ii[int(s)]] += np.float32(v or 0.0)
    finally:
        con.close()
    return Panel(dates, ids, arrays["open"], arrays["high"], arrays["low"], arrays["close"],
                 arrays["volume"], uni, buy, sell)
