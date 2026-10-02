"""Participant identity (Plan 1 §6.4-6.5; steps 3.6, 3.9, 3.10, 3.12).

The owner's rules, pinned: exact after cleaning (Q19); a likely duplicate is
suggested and NEVER merged without a ruling (Q20); fund houses come from a
manual file (Q21); behaviour classifies before names; and a ruling is keyed on
the cleaned name, so it survives every rebuild.
"""

from __future__ import annotations

import duckdb
import pytest

from src.identity import participants as P
from src.identity import review as R

pytestmark = pytest.mark.unit


# --- pure ----------------------------------------------------------------------------

def test_name_patterns_apply_in_file_order():
    pats = P.config()["name_pattern"]
    assert P.classify_name("SBI MUTUAL FUND", pats) == "MUTUAL_FUND"
    assert P.classify_name("ICICI BANK", pats) == "BANK"
    # MUTUAL_FUND is listed before BANK: a bank's fund arm is a fund.
    assert P.classify_name("CANARA BANK MUTUAL FUND", pats) == "MUTUAL_FUND"
    assert P.classify_name("ZZYX ALPHA HOLDINGS GROUP", pats) is None


def test_the_fund_house_file_groups_renamed_houses_and_keeps_merged_ones_apart():
    import yaml
    groups = yaml.safe_load(P.FUND_HOUSES.read_text())["groups"]
    assert P.fund_house("RELIANCE MUTUAL FUND", groups) == "NIPPON_INDIA_AMC"
    assert P.fund_house("NIPPON INDIA MUTUAL FUND", groups) == "NIPPON_INDIA_AMC"
    assert P.fund_house("IDFC MUTUAL FUND", groups) == "BANDHAN_AMC"
    assert P.fund_house("L AND T MUTUAL FUND", groups) == "LNT_AMC"     # merged into HSBC: separate
    assert P.fund_house("SBI LIFE INSURANCE", groups) is None          # a house, not a conglomerate


def test_typos_and_reordered_words_are_suggested_smaller_into_larger():
    deals = {"ABN AMRO BANK NV LONDON BRANCH": 40, "ABN AMRO BANK NV LINDON BRANCH": 2,
             "GOLDMAN SACHS SINGAPORE": 30, "SINGAPORE GOLDMAN SACHS": 3, "UNRELATED NAME HERE": 50}
    got = {(a, b): why for a, b, why in P.suggest_merges(deals, min_deals=6)}
    assert ("ABN AMRO BANK NV LINDON BRANCH", "ABN AMRO BANK NV LONDON BRANCH") in got
    assert got[("SINGAPORE GOLDMAN SACHS", "GOLDMAN SACHS SINGAPORE")] == "same words, different order"
    assert all("UNRELATED" not in a and "UNRELATED" not in b for a, b in got)


def test_two_minor_names_are_not_suggested():
    """At least one side must matter for a track record."""
    assert P.suggest_merges({"TINY TRADER ONE": 1, "TINY TRADER ONF": 2}, min_deals=6) == []
    assert P.suggest_merges({"TINY TRADER ONE": 1, "ONE TINY TRADER": 2}, min_deals=6) == []


# --- the build, against a tiny migrated warehouse ---------------------------------------

@pytest.fixture
def wh(tmp_path, monkeypatch):
    from src.common import migrate
    db = tmp_path / "w.duckdb"
    migrate.migrate_duckdb(db)
    con = duckdb.connect(str(db))
    con.execute("INSERT INTO deal_source_files (source_file_id, exchange, report_type, source_url,"
                " report_date, downloaded_at, file_name, file_hash, file_bytes, parser_version, ingestion_status)"
                " VALUES (1, 'NSE', 'BULK', 'x', DATE '2025-01-01', now(), 'f', 'h', 1, 't', 'OK')")
    rows = []
    i = 0

    def deal(name, sym, day, side, n=1):
        nonlocal i
        for _ in range(n):
            i += 1
            rows.append((i, 1, "NSE", "BULK", f"2025-01-{day:02d}", sym, name, side, "1000", "100",
                         "{}", i))
    deal("SBI MUTUAL FUND", "ACME", 2, "BUY", 3)
    deal("SBI Mutual Fund.", "ACME", 3, "BUY", 2)                  # a spelling: same participant
    deal("ZZYX ALPHA CAPITAL PARTNERS", "ACME", 4, "BUY", 7)             # UNKNOWN, >= 6 deals: queued
    deal("ZZYX ALPHA CAPITAL PARTNRS", "ACME", 5, "SELL", 1)             # its likely typo
    for d in range(1, 25):                                          # a round-tripper
        deal("FAST MAKER", "ACME", d, "BUY")
        deal("FAST MAKER", "ACME", d, "SELL")
    con.executemany("INSERT INTO institutional_deals_raw (raw_deal_id, source_file_id, exchange, deal_type,"
                    " trade_date, symbol_raw, client_name_raw, side_raw, quantity_raw, deal_price_raw,"
                    " raw_row_json, row_index, ingested_at) VALUES (?,?,?,?,CAST(? AS DATE),?,?,?,?,?,?,?,now())",
                    rows)
    con.close()
    monkeypatch.setattr(P, "research_db", lambda env=None: db)
    monkeypatch.setattr(R, "research_db", lambda env=None: db)
    monkeypatch.setattr(R, "review_db", lambda env=None: tmp_path / "review.sqlite")
    monkeypatch.setattr(P.prov, "register", lambda *a, **k: None)
    migrate.migrate_sqlite(tmp_path / "gov.sqlite")
    monkeypatch.setattr(P, "governance_db", lambda env=None: tmp_path / "gov.sqlite")
    return db


def _master(db):
    con = duckdb.connect(str(db), read_only=True)
    out = {r[0]: r[1:] for r in con.execute(
        "SELECT canonical_name, participant_type, classification_method, review_status, parent_group_id"
        " FROM participant_master").fetchall()}
    con.close()
    return out


def test_spellings_collapse_behaviour_comes_first_and_unknowns_are_queued(wh):
    rep = P.build()
    m = _master(wh)
    assert rep.raw_names == 5 and "SBI MUTUAL FUND" in m and len([k for k in m if "SBI" in k and m[k][0] != "FUND_HOUSE"]) == 1
    assert m["FAST MAKER"][:2] == ("PROP_HFT", "BEHAVIOURAL")
    assert m["ZZYX ALPHA CAPITAL PARTNERS"][2] == "PENDING"
    assert m["SBI MUTUAL FUND"][3] is not None, "the fund house parent was not set"
    assert R.suggestions() == [("ZZYX ALPHA CAPITAL PARTNRS", "ZZYX ALPHA CAPITAL PARTNERS",
                                f"differs by at most {P.SUGGEST_MAX_EDITS} characters")]


def test_a_suggestion_is_never_applied_without_a_ruling(wh):
    P.build()
    assert "ZZYX ALPHA CAPITAL PARTNRS" in _master(wh)


def test_rulings_survive_a_rebuild_and_take_effect(wh):
    P.build()
    R.set_type("ZZYX ALPHA CAPITAL PARTNERS", "FOREIGN_INSTITUTION", note="hedge fund")
    R.decide_merge("ZZYX ALPHA CAPITAL PARTNRS", "ZZYX ALPHA CAPITAL PARTNERS", accept=True)
    P.build()
    P.build()                                   # twice: rebuilding over existing rows
    m = _master(wh)
    assert m["ZZYX ALPHA CAPITAL PARTNERS"][:3] == ("FOREIGN_INSTITUTION", "MANUAL", "REVIEWED")
    assert "ZZYX ALPHA CAPITAL PARTNRS" not in m
    assert R.suggestions() == []


def test_a_rejected_suggestion_is_not_suggested_again(wh):
    P.build()
    R.decide_merge("ZZYX ALPHA CAPITAL PARTNRS", "ZZYX ALPHA CAPITAL PARTNERS", accept=False)
    P.build()
    assert R.suggestions() == [] and "ZZYX ALPHA CAPITAL PARTNRS" in _master(wh)
    # The builder's own filter, not only the queue's: the alias row carries no
    # suggestion once the owner has said no.
    con = duckdb.connect(str(wh), read_only=True)
    left = con.execute("SELECT COUNT(*) FROM participant_aliases WHERE suggested_merge_id IS NOT NULL"
                       ).fetchone()[0]
    con.close()
    assert left == 0


def test_a_ruling_must_name_a_declared_type(wh):
    with pytest.raises(ValueError, match="not a declared type"):
        R.set_type("ANYONE", "HEDGE_FUND_ISH")
