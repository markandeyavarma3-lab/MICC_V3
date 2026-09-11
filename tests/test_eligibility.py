"""The PROP_HFT classifier, and the field that is not a membership test.

`src/mart/eligibility.py` removes 41% of the corpus. Nothing tested it directly
until 2026-09-11, which is how a misreading of `ineligibility_reason` reached a
decision record and stood for a day.
"""

from __future__ import annotations

import duckdb
import pytest

from src.common.paths import research_db

pytestmark = pytest.mark.needs_data


@pytest.fixture(scope="module")
def con():
    c = duckdb.connect(str(research_db("prod")), read_only=True)
    c.execute("""CREATE TEMP VIEW _csd AS
      SELECT UPPER(TRIM(r.client_name_raw)) AS participant,
             UPPER(TRIM(r.symbol_raw)) AS sym, cl.trade_date,
             MAX(CASE WHEN cl.side='BUY' THEN 1 ELSE 0 END) AS bought,
             MAX(CASE WHEN cl.side='SELL' THEN 1 ELSE 0 END) AS sold
      FROM institutional_deals_clean cl
      JOIN institutional_deals_raw r USING (raw_deal_id)
      GROUP BY 1,2,3""")
    c.execute("""CREATE TEMP VIEW _hft AS
      SELECT participant FROM (
        SELECT participant, COUNT(*) AS days,
               SUM(CASE WHEN bought=1 AND sold=1 THEN 1 ELSE 0 END)*1.0/COUNT(*) AS ratio
        FROM _csd GROUP BY 1)
      WHERE days >= 20 AND ratio >= 0.95""")
    yield c
    c.close()


def test_ineligibility_reason_is_a_display_field_not_a_membership_test(con):
    """THE MISREADING THAT REACHED A DECISION RECORD, 2026-09-10.

    `ineligibility_reason` carries ONE reason per row in priority order, and
    `same-day round trip` is evaluated one line above `PROP_HFT participant` in
    `src/mart/clean.py`. Counting the label answers "how many rows DISPLAY this
    reason", not "how many rows BELONG to this class" — the two differ by
    whatever a higher-priority rule absorbs.

    Measured: 168 rows display PROP_HFT; 310 participants covering 97,249 rows
    (41.2%) belong to it. I read the first as the second, published "the
    classifier does almost nothing", and retracted it a day later. The gap is
    97,081 rows.

    This asserts the gap EXISTS, so the next person to count the label trips
    over the discrepancy instead of publishing it.
    """
    labelled = con.execute(
        "SELECT COUNT(*) FROM institutional_deals_clean "
        "WHERE ineligibility_reason = 'PROP_HFT participant'").fetchone()[0]
    member_rows = con.execute("""
      SELECT COUNT(*) FROM institutional_deals_clean cl
      JOIN institutional_deals_raw r USING (raw_deal_id)
      WHERE UPPER(TRIM(r.client_name_raw)) IN (SELECT participant FROM _hft)
    """).fetchone()[0]

    assert member_rows > 50_000, (
        f"PROP_HFT membership covers only {member_rows:,} rows; the classifier "
        f"has genuinely stopped working and 0056 amendment 3 needs revisiting"
    )
    assert member_rows > labelled * 10, (
        f"label={labelled:,} membership={member_rows:,} — close enough that the "
        f"display/membership distinction has collapsed. If the CASE ordering in "
        f"src/mart/clean.py changed, its comment must change too"
    )


def test_the_known_market_makers_are_classified(con):
    """Graviton, HRTI, Tower and XTX round-trip essentially every client-stock-day.
    The docstring of eligibility.py names them; behaviour, not the name, is what
    catches them, so this fails if the thresholds ever stop working."""
    caught = {r[0] for r in con.execute("SELECT participant FROM _hft").fetchall()}
    for name in ("GRAVITON RESEARCH CAPITAL LLP", "HRTI PRIVATE LIMITED",
                 "XTX MARKETS LLP"):
        assert name in caught, f"{name} is no longer classified PROP_HFT"


def test_the_directional_population_contains_no_market_makers(con):
    """The population Workstream 3's entity study draws from. If a market maker
    ever appears among the candidates, tiering will find 'skill' in inventory
    management."""
    n = con.execute("""
      WITH dir AS (
        SELECT UPPER(TRIM(r.client_name_raw)) AS p, cl.trade_date
        FROM institutional_deals_clean cl JOIN institutional_deals_raw r USING (raw_deal_id)
        WHERE NOT cl.same_day_round_trip_flag
          AND NOT cl.unresolved_symbol_flag AND NOT cl.uncovered_symbol_flag),
      cand AS (
        SELECT p FROM dir GROUP BY 1
        HAVING COUNT(*) >= 30 AND COUNT(DISTINCT strftime(trade_date,'%Y-%m')) >= 12)
      SELECT COUNT(*) FROM cand WHERE p IN (SELECT participant FROM _hft)
    """).fetchone()[0]
    assert n == 0, f"{n} entity-study candidates are PROP_HFT market makers"
