"""eligibility.py — which disclosed deals are research events. Plan 1 §7.1.

THE FILTER THAT DECIDES EVERYTHING DOWNSTREAM.

Measured on 2026-08-16: **54.8% of bulk-deal client-stock-days are same-day round
trips.** The most active "institutions" in the corpus are high-frequency market
makers whose disclosure is a mechanical consequence of crossing the 0.5% volume
threshold intraday — Graviton 6,748 of 6,748 round trips, HRTI 2,968 of 2,968,
Tower Research and XTX both 100%. They end the day flat. Block deals are clean at
0.7%.

Studying institutional conviction without removing them is not studying
institutional conviction.

BEHAVIOUR CLASSIFIES BEFORE NAMES DO. Graviton never declares itself a market
maker; 6,748/6,748 does. `participants.yml` sets `classification_order:
[behavioural, name_pattern, unknown]` for this reason, and the ordering matters —
a firm named "... SECURITIES PRIVATE LIMITED" that round-trips every day is
PROP_HFT, not a broker.

THE THRESHOLDS ARE NOT TUNED, AND THEY ARE NOT SETTLED EITHER. The observed
round-trip distribution is near-bimodal: the top twenty participants sit at
100.0, 100.0, 100.0, 98.9, 85.6, 62.0, 52.9 … — a dense cluster at ~100% and a
long tail below 90%. 0.95 sits inside the gap; 20 client-stock-days is where the
ratio stops being dominated by small-sample noise. Because this removes 44% of
the data, `participants.yml` requires a 3x3 sensitivity grid in every study: a
finding that moves between 0.90 and 0.95 is a finding about the cut.

NOTHING IS DELETED. Rows are flagged, never dropped, and every study reports its
N with and without. A 44%-of-data filter must be visible.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import duckdb
import yaml

from src.common.paths import CONFIGS, SEED


@lru_cache(maxsize=1)
def spec() -> dict:
    return yaml.safe_load((CONFIGS / "participants.yml").read_text())


@dataclass(frozen=True, slots=True)
class Thresholds:
    """One point on the sensitivity grid."""

    roundtrip_ratio: float
    min_client_stock_days: int

    @classmethod
    def default(cls) -> Thresholds:
        b = spec()["behavioural"]["prop_hft"]
        return cls(float(b["roundtrip_ratio"]), int(b["min_client_stock_days"]))


def grid() -> list[Thresholds]:
    """The 3x3 sensitivity grid participants.yml requires be published."""
    b = spec()["behavioural"]["prop_hft"]
    ratios = [float(b["roundtrip_ratio"]), *[float(x) for x in b["sensitivity_roundtrip_ratio"]]]
    days = [int(b["min_client_stock_days"]), *[int(x) for x in b["sensitivity_min_days"]]]
    return [Thresholds(r, d) for r in sorted(set(ratios)) for d in sorted(set(days))]


def _deals_sql() -> str:
    """Bulk and block deals, normalised. Client names are cleaned per
    participants.yml before any grouping: 'ABC PVT LTD' and 'ABC PRIVATE LIMITED'
    are one participant, and counting them separately would understate every
    round-trip ratio and let a market maker through the filter."""
    strip = spec()["normalisation"]["strip_suffixes"]
    expr = "UPPER(TRIM(client))"
    for suffix in sorted(strip, key=len, reverse=True):
        expr = f"TRIM(REGEXP_REPLACE({expr}, '\\s*{suffix}\\s*$', '', 'g'))"
    expr = f"TRIM(REGEXP_REPLACE({expr}, '[^A-Z0-9 ]', ' ', 'g'))"
    expr = f"TRIM(REGEXP_REPLACE({expr}, '\\s+', ' ', 'g'))"
    return f"""
    SELECT {expr} AS participant,
           UPPER(TRIM(symbol)) AS symbol,
           date,
           UPPER(TRIM(buy_sell)) AS side,
           CAST(qty AS DOUBLE) AS qty,
           CAST(price AS DOUBLE) AS price,
           'BULK' AS deal_type
    FROM read_parquet('{SEED}/bulk_deals.parquet')
    UNION ALL
    SELECT {expr}, UPPER(TRIM(symbol)), date, UPPER(TRIM(buy_sell)),
           CAST(qty AS DOUBLE), CAST(price AS DOUBLE), 'BLOCK'
    FROM read_parquet('{SEED}/block_deals.parquet')
    """


def classify(con: duckdb.DuckDBPyConnection, t: Thresholds | None = None) -> None:
    """Create `deals`, `participant_stats` and `eligible_events` views.

    A CLIENT-STOCK-DAY is the unit, not a deal row: a participant that trades one
    name ten times in a day has one observation of intent, not ten. Using deal
    rows would let a single busy day dominate a participant's ratio.
    """
    t = t or Thresholds.default()
    con.execute(f"CREATE OR REPLACE VIEW deals AS {_deals_sql()}")

    # One row per (participant, symbol, date): did they both buy AND sell?
    con.execute("""
        CREATE OR REPLACE VIEW client_stock_days AS
        SELECT participant, symbol, date,
               MAX(CASE WHEN side LIKE 'B%' THEN 1 ELSE 0 END) AS bought,
               MAX(CASE WHEN side LIKE 'S%' THEN 1 ELSE 0 END) AS sold
        FROM deals GROUP BY 1,2,3
    """)
    con.execute("""
        CREATE OR REPLACE VIEW participant_stats AS
        SELECT participant,
               COUNT(*) AS client_stock_days,
               SUM(CASE WHEN bought=1 AND sold=1 THEN 1 ELSE 0 END) AS roundtrips,
               SUM(CASE WHEN bought=1 AND sold=1 THEN 1 ELSE 0 END)*1.0/COUNT(*) AS roundtrip_ratio
        FROM client_stock_days GROUP BY 1
    """)
    con.execute(f"""
        CREATE OR REPLACE VIEW prop_hft AS
        SELECT participant FROM participant_stats
        WHERE client_stock_days >= {t.min_client_stock_days}
          AND roundtrip_ratio >= {t.roundtrip_ratio}
    """)
    # An EVENT is one (participant, symbol, side, date) — owner decision Q28
    # keeps a client's multiple same-day rows as separate events, but a
    # round-tripped day is not a directional event at all.
    con.execute("""
        CREATE OR REPLACE VIEW eligible_events AS
        SELECT d.participant, d.symbol, d.date, d.deal_type,
               SUM(d.qty) AS qty, SUM(d.qty*d.price)/NULLIF(SUM(d.qty),0) AS vwap,
               SUM(d.qty*d.price) AS value_inr
        FROM deals d
        JOIN client_stock_days c USING (participant, symbol, date)
        WHERE d.side LIKE 'B%'
          AND c.sold = 0                                    -- not a same-day round trip
          AND d.participant NOT IN (SELECT participant FROM prop_hft)
        GROUP BY 1,2,3,4
    """)


def summarise(con: duckdb.DuckDBPyConnection) -> dict:
    n_deals, n_part = con.execute(
        "SELECT COUNT(*), COUNT(DISTINCT participant) FROM deals").fetchone()
    csd, rt = con.execute(
        "SELECT COUNT(*), SUM(CASE WHEN bought=1 AND sold=1 THEN 1 ELSE 0 END)"
        " FROM client_stock_days").fetchone()
    n_hft = con.execute("SELECT COUNT(*) FROM prop_hft").fetchone()[0]
    n_ev = con.execute("SELECT COUNT(*) FROM eligible_events").fetchone()[0]
    hft_rows = con.execute(
        "SELECT COUNT(*) FROM deals WHERE participant IN (SELECT participant FROM prop_hft)"
    ).fetchone()[0]
    return {
        "deal_rows": n_deals, "participants": n_part,
        "client_stock_days": csd, "roundtrip_days": rt,
        "roundtrip_share": rt / csd if csd else 0,
        "prop_hft_participants": n_hft,
        "prop_hft_deal_rows": hft_rows,
        "prop_hft_share_of_rows": hft_rows / n_deals if n_deals else 0,
        "eligible_buy_events": n_ev,
    }


def main() -> int:
    con = duckdb.connect()
    con.execute("SET memory_limit='8GB';")
    t = Thresholds.default()
    classify(con, t)
    s = summarise(con)
    print(f"ELIGIBILITY  (roundtrip >= {t.roundtrip_ratio:.0%}, "
          f">= {t.min_client_stock_days} client-stock-days)")
    print(f"  deal rows              {s['deal_rows']:>10,}")
    print(f"  participants           {s['participants']:>10,}")
    print(f"  client-stock-days      {s['client_stock_days']:>10,}")
    print(f"  same-day round trips   {s['roundtrip_days']:>10,}  "
          f"({s['roundtrip_share']:.1%}  — expect ~54.8%)")
    print(f"  PROP_HFT participants  {s['prop_hft_participants']:>10,}")
    print(f"  ...their deal rows     {s['prop_hft_deal_rows']:>10,}  "
          f"({s['prop_hft_share_of_rows']:.1%}  — expect ~44%)")
    print(f"  ELIGIBLE buy events    {s['eligible_buy_events']:>10,}")

    print("\n  sensitivity grid (participants.yml requires this be published):")
    print(f"    {'ratio':>6} {'min days':>9} {'PROP_HFT':>9} {'eligible':>10}")
    for g in grid():
        classify(con, g)
        gs = summarise(con)
        print(f"    {g.roundtrip_ratio:>6.2f} {g.min_client_stock_days:>9} "
              f"{gs['prop_hft_participants']:>9,} {gs['eligible_buy_events']:>10,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
