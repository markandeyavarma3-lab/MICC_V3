"""The promoter list (Plan 1 §6.6, step 3.11) and the two deal flags it feeds.

Pinned here: which XBRL axes count as promoters (measured, and one public axis
that looks like a promoter one is deliberately out); that validity runs open
and close on BROADCAST dates, never quarter-ends; that a filing naming nobody
does not un-flag a company; and that the identity rebuild can still empty
security_master once promoter rows reference it.
"""

from __future__ import annotations

import gzip

import duckdb
import pytest

from src.identity import promoters
from src.identity.promoters import Filing
from src.ingest import shp

pytestmark = pytest.mark.unit


# --- the parser ---------------------------------------------------------------

def _xbrl(holders: list[tuple[str, str, str]], promoter: str = "0.60", public: str = "0.40") -> bytes:
    """A filing with category totals and named holders: (axis, name, pct)."""
    def ctx(cid, scen="", instant=True):
        period = ("<xbrli:instant>2026-06-30</xbrli:instant>" if instant else
                  "<xbrli:startDate>2026-04-01</xbrli:startDate><xbrli:endDate>2026-06-30</xbrli:endDate>")
        return (f'<xbrli:context id="{cid}"><xbrli:entity><xbrli:identifier scheme="x">1</xbrli:identifier>'
                f'</xbrli:entity><xbrli:period>{period}</xbrli:period>{scen}</xbrli:context>')

    def cat(member):
        return (f'<xbrli:scenario><xbrldi:explicitMember dimension="in-bse-shp:CategoryOfShareholdersAxis">'
                f'in-bse-shp:{member}</xbrldi:explicitMember></xbrli:scenario>')

    def typed(axis, n):
        dom = axis.replace("Axis", "Domain")
        return (f'<xbrli:scenario><xbrldi:typedMember dimension="in-bse-shp:{axis}">'
                f'<in-bse-shp:{dom}>{axis}{n}</in-bse-shp:{dom}></xbrldi:typedMember></xbrli:scenario>')

    def fact(name, cid, val):
        return f'<in-bse-shp:{name} contextRef="{cid}" unitRef="pure">{val}</in-bse-shp:{name}>'

    body = (ctx("MainD") + fact("ISIN", "MainD", "INE000A01010") + fact("Symbol", "MainD", "ACME")
            + ctx("Prom_I", cat("ShareholdingOfPromoterAndPromoterGroupMember"))
            + ctx("Pub_I", cat("PublicShareholdingMember"))
            + fact("ShareholdingAsAPercentageOfTotalNumberOfShares", "Prom_I", promoter)
            + fact("ShareholdingAsAPercentageOfTotalNumberOfShares", "Pub_I", public))
    for i, (axis, name, pct) in enumerate(holders, 1):
        # The real layout: name on the duration context, percent on the instant.
        body += (ctx(f"H{i}D", typed(axis, i), instant=False) + ctx(f"H{i}I", typed(axis, i))
                 + fact("NameOfTheShareholder", f"H{i}D", name)
                 + fact("ShareholdingAsAPercentageOfTotalNumberOfShares", f"H{i}I", pct))
    return gzip.compress(f'<?xml version="1.0"?><xbrli:xbrl>{body}</xbrli:xbrl>'.encode())


def test_only_table_ii_holders_are_promoters_and_the_name_meets_its_percentage(tmp_path):
    f = tmp_path / "f.xml.gz"
    f.write_bytes(_xbrl([
        ("DetailsSharesHeldByIndividualsOrHUFAxis", "Ashish Rajanibhai Patel", "0.35"),
        ("DetailsOfSharesHeldByOthersIndianShareholdersAxis", "Patel Holdings Pvt Ltd", "0.25"),
        # Public Table III — must not become promoters.
        ("DetailsOfSharesHeldByOtherNonInstitutionsAxis", "Some Public Holder", "0.02"),
        # 2018-2022: the PUBLIC financial-institutions line uses this axis too.
        ("DetailsOfSharesHeldByFinancialInstitutionOrBanksAxis", "State Bank Of India", "0.03"),
    ]))
    got = {p.name: p for p in shp.parse_promoters_file(str(f))}
    assert set(got) == {"Ashish Rajanibhai Patel", "Patel Holdings Pvt Ltd"}
    # Fraction-scale filing, normalised to percent like the category rows.
    assert got["Ashish Rajanibhai Patel"].pct_shares == pytest.approx(35.0)
    assert got["Patel Holdings Pvt Ltd"].quarter_end == "2026-06-30"


def test_the_holdings_rows_are_unchanged_by_the_promoter_pass(tmp_path):
    f = tmp_path / "f.xml.gz"
    f.write_bytes(_xbrl([("DetailsSharesHeldByIndividualsOrHUFAxis", "A Person", "0.60")]))
    cats = {r.category for r in shp.parse_xbrl_file(str(f))}
    assert cats == {"Promoter", "PublicTotal"}


# --- validity runs ------------------------------------------------------------

def _f(q, bd, names, pct=50.0):
    return Filing(q, bd, {n: (n, 1.0) for n in names}, pct)


def test_a_run_opens_and_closes_on_broadcast_dates_not_quarter_ends():
    rs, *_ = promoters.runs([
        _f("2025-03-31", "2025-04-20", ["A", "B"]),
        _f("2025-06-30", "2025-07-18", ["A"]),
        _f("2025-09-30", "2025-10-21", ["A"]),
    ])
    by = {r.normalized_name: r for r in rs}
    assert (by["A"].valid_from, by["A"].valid_to) == ("2025-04-20", None)
    assert (by["B"].valid_from, by["B"].valid_to) == ("2025-04-20", "2025-07-18")


def test_a_filing_that_names_nobody_does_not_unflag_the_company():
    rs, _, no_names, _ = promoters.runs([
        _f("2025-03-31", "2025-04-20", ["A"]),
        _f("2025-06-30", "2025-07-18", [], pct=50.0),   # Table II missing
        _f("2025-09-30", "2025-10-21", ["A"]),
    ])
    assert no_names == 1
    assert [(r.valid_from, r.valid_to) for r in rs] == [("2025-04-20", None)]


def test_a_filing_with_no_promoter_holding_does_close_the_runs():
    rs, _, no_names, _ = promoters.runs([
        _f("2025-03-31", "2025-04-20", ["A"]),
        _f("2025-06-30", "2025-07-18", [], pct=0.0),
    ])
    assert no_names == 0
    assert [(r.valid_from, r.valid_to) for r in rs] == [("2025-04-20", "2025-07-18")]


def test_a_filing_with_no_broadcast_date_is_skipped_not_guessed():
    rs, no_date, _, _ = promoters.runs([_f("2025-03-31", "", ["A"]),
                                        _f("2025-06-30", "2025-07-18", ["A"])])
    assert no_date == 1 and [r.valid_from for r in rs] == ["2025-07-18"]


def test_an_omission_published_before_the_listing_does_not_close_the_run():
    """Older news cannot end a run that newer news opened."""
    rs, _, _, out_of_order = promoters.runs([
        _f("2025-03-31", "2025-08-01", ["A"]),       # published late
        _f("2025-06-30", "2025-07-18", ["B"]),       # published earlier, omits A
    ])
    assert out_of_order == 1
    by = {r.normalized_name: (r.valid_from, r.valid_to) for r in rs}
    assert by == {"A": ("2025-08-01", None), "B": ("2025-07-18", None)}


def test_out_of_order_broadcasts_merge_into_one_run_not_a_duplicate_key():
    """Found on the first real build: a later quarter published on the same
    day as an earlier one reopened a run on its own start date."""
    rs, *_ = promoters.runs([
        _f("2024-03-31", "2024-08-27", ["A"]),
        _f("2024-06-30", "2024-09-10", []  , pct=0.0),
        _f("2024-09-30", "2024-08-27", ["A"]),
    ])
    keys = [(r.normalized_name, r.valid_from) for r in rs]
    assert len(keys) == len(set(keys))
    assert [(r.valid_from, r.valid_to) for r in rs] == [("2024-08-27", None)]


def test_separate_spells_stay_separate():
    rs, *_ = promoters.runs([
        _f("2024-03-31", "2024-04-20", ["A"]),
        _f("2024-06-30", "2024-07-20", [], pct=0.0),
        _f("2024-09-30", "2024-10-20", ["A"]),
    ])
    assert [(r.valid_from, r.valid_to) for r in rs] == [("2024-04-20", "2024-07-20"), ("2024-10-20", None)]


# --- the deal flags -------------------------------------------------------------

@pytest.fixture
def flags():
    from src.mart.clean import promoter_flags

    con = duckdb.connect()
    con.execute("""CREATE TABLE institutional_deals_raw (raw_deal_id INT, trade_date DATE,
                   symbol_raw VARCHAR, side_raw VARCHAR, client_name_raw VARCHAR)""")
    con.execute("CREATE TABLE deal_resolution (raw_deal_id INT, security_id BIGINT)")
    con.execute("""CREATE TABLE promoter_entities (security_id BIGINT, entity_name VARCHAR,
                   normalized_name VARCHAR, valid_from DATE, valid_to DATE,
                   holding_pct REAL, source_file_id BIGINT)""")
    con.execute("""INSERT INTO promoter_entities VALUES
        (1, 'Patel Holdings Pvt Ltd', 'PATEL HOLDINGS', '2025-04-20', NULL, 25, NULL),
        (1, 'Ashish Patel', 'ASHISH PATEL', '2025-04-20', '2025-10-21', 35, NULL)""")
    deals = [
        (1, "2025-05-02", "ACME", "SELL", "ASHISH PATEL"),             # promoter, internal
        (2, "2025-05-02", "ACME", "BUY", "PATEL HOLDINGS PRIVATE LIMITED"),  # promoter, internal
        (3, "2025-04-10", "ACME", "SELL", "ASHISH PATEL"),             # before the filing
        (4, "2025-11-03", "ACME", "SELL", "ASHISH PATEL"),             # after the run closed
        (5, "2025-06-02", "ACME", "SELL", "PATEL HOLDINGS LTD"),       # promoter, not internal
        (6, "2025-06-02", "ACME", "BUY", "SOME FUND"),                 # the counterparty
        (7, "2025-06-02", "OTHER", "SELL", "ASHISH PATEL"),            # another company
    ]
    con.executemany("INSERT INTO institutional_deals_raw VALUES (?,?,?,?,?)", deals)
    con.executemany("INSERT INTO deal_resolution VALUES (?,?)",
                    [(d[0], 2 if d[2] == "OTHER" else 1) for d in deals])
    promoter_flags(con)
    out = {r[0]: r[1:] for r in con.execute(
        "SELECT raw_deal_id, promoter_related, internal_transfer, list_in_force FROM pflag").fetchall()}
    con.close()
    return out


def test_a_promoter_trading_its_own_company_inside_the_window_is_flagged(flags):
    assert flags[1][0] and flags[2][0] and flags[5][0]


def test_the_flag_is_point_in_time(flags):
    assert not flags[3][0], "flagged from a filing broadcast AFTER the trade"
    assert not flags[4][0], "flagged after the filing that dropped the name"


def test_a_promoter_of_one_company_is_nobody_in_another(flags):
    assert not flags[7][0]


def test_internal_transfer_needs_a_different_promoter_on_the_other_side(flags):
    assert flags[1][1] and flags[2][1]
    assert not flags[5][1], "a promoter selling to a fund is not an internal transfer"
    assert not flags[6][0] and not flags[6][1]


def test_list_in_force_says_whether_the_question_could_be_asked(flags):
    assert flags[6][2] and flags[1][2]
    assert not flags[3][2], "no list was published yet"
    assert not flags[7][2], "no list for that security at all"


# --- the identity rebuild ---------------------------------------------------------

def test_security_master_can_still_be_rebuilt_once_promoters_reference_it(tmp_path):
    """DuckDB enforces the FK. Without clearing promoter_entities first, the
    nightly identity stage would be refused and freeze the mart (0055)."""
    from src.common import migrate
    from src.identity.master import clear_for_rebuild

    db = tmp_path / "w.duckdb"
    migrate.migrate_duckdb(db)
    con = duckdb.connect(str(db))
    try:
        con.execute("INSERT INTO security_master (security_id, isin, canonical_symbol, company_name,"
                    " status, source, confidence) VALUES (1, 'INE000A01010', 'ACME', 'Acme',"
                    " 'ACTIVE', 't', 'HIGH')")
        con.execute("INSERT INTO promoter_entities VALUES (1, 'A', 'A', DATE '2025-01-01', NULL, 1, NULL)")
        with pytest.raises(duckdb.ConstraintException):
            con.execute("DELETE FROM security_master")
        clear_for_rebuild(con)
        assert con.execute("SELECT COUNT(*) FROM security_master").fetchone()[0] == 0
    finally:
        con.close()
