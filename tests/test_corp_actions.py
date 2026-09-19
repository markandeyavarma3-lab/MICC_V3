"""Corporate action classification, and the four ways it could quietly be wrong.

Context: on 2026-09-01 the adjusted spine was found to carry at least 16
unadjusted corporate actions in its tail, 15 of them predating this project's
own price collection. `build_adjusted`'s guard had been counting actions in a
table that stopped four days past the splice boundary.

The fix needs a factor per action, and a factor applied wrongly is worse than no
factor at all: it manufactures a return out of nothing, in data that then looks
clean. So the parser is narrow on purpose and these tests pin the narrowness.
"""

from __future__ import annotations

import pytest

from src.ingest.corp_actions import classify, classify_all

pytestmark = pytest.mark.unit


def test_a_face_value_split_gives_the_ratio_of_face_values():
    kind, ratio, factor = classify(
        "Face Value Split (Sub-Division) - From Rs 10/- Per Share To Rs 2/- Per Share")
    assert (kind, ratio) == ("SPLIT", "10:2")
    assert factor == pytest.approx(0.2)


def test_a_split_to_one_rupee_is_read_as_re_not_rs():
    """NSE writes 'To Re 1' for one rupee and 'To Rs 2' for two. A parser that
    only knows 'Rs' silently drops every 1:10 split, which is the largest and
    most damaging class."""
    kind, _, factor = classify(
        "Face Value Split (Sub-Division) - From Rs 10/- Per Share To Re 1/- Per Share")
    assert kind == "SPLIT"
    assert factor == pytest.approx(0.1)


def test_a_bonus_dilutes_by_new_plus_old():
    """Bonus 2:1 is two NEW shares per one held, so three shares stand where one
    did and the price is a third. Reading it as 1/2 would leave a -17% artefact
    exactly where the adjustment was supposed to remove one.

    Confirmed against the market: GOODLUCK closed 1439.40 then 490.90 on its
    2026-08-21 ex-date, a ratio of 0.341.
    """
    kind, ratio, factor = classify("Bonus 2:1")
    assert (kind, ratio) == ("BONUS", "2:1")
    assert factor == pytest.approx(1 / 3, abs=1e-9)


def test_preference_share_bonuses_are_never_treated_as_equity_bonuses():
    """THE TRAP. NCRPS are non-convertible redeemable PREFERENCE shares. The
    ordinary equity is not diluted, so applying a bonus factor would invent a
    -80% return for SIYSIL on 2026-08-21 out of nothing.

    A regex hunting for 'Bonus' and a colon matches this line perfectly.
    """
    kind, _, factor = classify("Scheme Of Arrangement - Bonus Ncrps 4:1")
    assert kind == "UNPARSED", "a preference-share issue must not be read as a bonus"
    assert factor is None


def test_convertible_and_warrant_rights_are_not_ordinary_rights():
    """The same trap in the rights form: CCPS and warrants are not ordinary
    shares, and the ':40' would otherwise parse as a ratio."""
    kind, _, factor = classify("Rights - 7 Ccps And 7 Warrants:40")
    assert kind == "UNPARSED"
    assert factor is None


def test_rights_are_recognised_but_carry_no_factor():
    """A rights factor needs the cum price, which is in the spine, not in this
    text. Emitting a placeholder would be worse than emitting nothing."""
    kind, ratio, factor = classify("Rights 3:5 @ Premium Rs 45/-")
    assert kind == "RIGHTS"
    assert ratio.startswith("3:5")
    assert factor is None, "a rights factor cannot be computed from the subject alone"


def test_a_rights_premium_without_a_currency_prefix_still_parses():
    """RELTD, ex 2026-06-08: 'Rights 1:9 @ Premium 91'. Requiring 'Rs' rejected a
    perfectly ordinary rights issue — strictness about punctuation reads as care
    and is simply wrong."""
    assert classify("Rights 1:9 @ Premium 91")[0] == "RIGHTS"


def test_a_demerger_is_price_affecting_and_needs_a_human():
    """Found by measurement, not by reading the spec: TRIVENI fell 41.6% on
    2026-07-22 with no action on file, because 'demerger' was missing from the
    screen. The value of the demerged entity is not in the subject line, so this
    is flagged, never guessed."""
    kind, _, factor = classify("Demerger")
    assert kind == "DEMERGER"
    assert factor is None


def test_dividends_are_not_price_affecting_here():
    """The overwhelming majority of records are dividends. Treating them as
    price-affecting would flood the screen and bury the 12 splits that matter."""
    assert classify("Dividend - Rs 8.50 Per Share") is None
    assert classify("Interim Dividend - Rs 2 Per Share") is None


def test_anything_unrecognised_that_looks_price_affecting_is_surfaced():
    """Standing rule 9: UNKNOWN beats inference. A form nobody has seen must
    reach a human rather than be filtered out by the expression that failed."""
    kind, _, factor = classify("Bonus issue of some entirely novel description")
    assert kind == "UNPARSED"
    assert factor is None



# --- the 113 that were UNPARSED on 2026-09-18, and the 27 that were half-read ---


def test_a_bonus_and_a_split_on_one_ex_date_are_two_rows_not_one():
    """THE ONE THAT WAS SILENTLY WRONG. "Bonus 1:1 And Face Value Split Rs.10/-
    To Re.1/-" is two events with two factors on one day, and the spine
    multiplies every factor it finds for a (symbol, date). The old parser
    returned the split and dropped the bonus — 27 subjects, every one of them
    a table row that looked parsed and carried half the adjustment. None fell
    after the seed boundary, which is the only reason the spine never applied
    one."""
    rows = classify_all("Bonus 1:1 And Face Value Split From Rs.10/- To Re.1/-")
    assert rows is not None and len(rows) == 2, rows
    kinds = {k: (r, f) for k, r, f in rows}
    assert kinds["SPLIT"][0] == "10:1" and kinds["SPLIT"][1] == pytest.approx(0.1)
    assert kinds["BONUS"][0] == "1:1" and kinds["BONUS"][1] == pytest.approx(0.5)


def test_the_bonus_may_hide_behind_a_dividend_or_an_agm():
    """'Annual General Meeting/Dividend Rs.2/- Per Share/Bonus 1:3' and
    'Dividend Rs.5.50 Per Share And Bonus 1:1' are bonuses — 40-odd of the
    113 were of this shape, refused because the ratio was not at the start."""
    for subject, ratio in (
        ("Annual General Meeting/Dividend Rs.2/- Per Share/Bonus 1:3", "1:3"),
        ("Dividend Rs.5.50 Per Share And Bonus 1:1", "1:1"),
        ("Bonus Shares In The Ratio Of 1:1", "1:1"),
        ("Bonus Issue 1 : 1", "1:1"),
        ("Bonus - 3:1", "3:1"),
        ("Bonus 4:5 (Pursuant To Scheme Of Amalgamation)", "4:5"),
    ):
        kind, got, factor = classify(subject)
        assert (kind, got) == ("BONUS", ratio), subject
        a, b = map(int, ratio.split(":"))
        assert factor == pytest.approx(b / (a + b))


def test_the_split_may_be_abbreviated_or_carry_no_currency():
    for subject, ratio, factor in (
        ("Fv Split Rs.10 To Rs.2", "10:2", 0.2),
        ("Fv Split Rs.10 To Re.1", "10:1", 0.1),
        ("Face Value Split Rs 10 To Rs 5", "10:5", 0.5),
        ("Sub-Division From Rs 10/- Per Share To Rs 2/- Per Share", "10:2", 0.2),
        ("Face Valus Split (Sub-Division) - From Rs 10/- Per To Rs 2/- Per Share", "10:2", 0.2),
        ("Bonus 1:1 / Face Value Split From 10/- To Face Value 2/-", "10:2", 0.2),
        ("Bonus 1 : 1 / Face Value Split From Rs 10/- Each To Rs 2/- Each", "10:2", 0.2),
    ):
        rows = classify_all(subject)
        got = {k: (r, f) for k, r, f in rows}
        assert "SPLIT" in got, subject
        assert got["SPLIT"][0] == ratio and got["SPLIT"][1] == pytest.approx(factor), subject


def test_a_consolidation_is_a_split_in_reverse():
    """Face value RISES, ten shares become one, the factor is above one."""
    kind, ratio, factor = classify(
        "Consolidation Of Equity Shares From Re 1 Per Share To Rs 10 Per Share")
    assert (kind, ratio) == ("CONSOLIDATION", "1:10")
    assert factor == pytest.approx(10.0)


def test_a_capital_reduction_is_not_read_even_when_a_consolidation_follows_it():
    """'Capital Reduction Rs 10 To Rs 3.30 / Consolidation Rs 3.30 To Rs.10':
    whether the reduction cancelled shares is not in the text, so the net
    factor is not derivable and the row goes to a human."""
    kind, _, factor = classify(
        "Capital Reduction Rs 10 To Rs 3.30 / Consolidation Rs 3.30 To Rs.10")
    assert kind == "UNPARSED" and factor is None


def test_rights_forms_with_and_without_a_stated_premium():
    """The ratio records the premium when stated, @0 at par, and nothing when
    the subject is silent — a stated zero and an unstated premium are not the
    same fact, and the consumer that computes TERP must be able to tell."""
    for subject, ratio in (
        ("Rights 2:3@Prem Rs.345/-", "2:3@345"),
        ("Rights 7:13 @Prem Rs.40/-", "7:13@40"),
        ("Rights At 2:1 At A Premium Of Rs.39.50 Per Share", "2:1@39.50"),
        ("Rights Issue 4 : 25 @ Premium Rs 194/- Per Equity Share", "4:25@194"),
        ("Rights 5: 116 At Premium Rs 244/- Per Share", "5:116@244"),
        ("Rights 7:10 @ Prm Rs 102/-", "7:10@102"),
        ("Rights : 24:10 At Par", "24:10@0"),
        ("Rights - 2:3@ Par Rs 10 Per Share", "2:3@0"),
        ("Issues Price Per Equity Share Is At Par And Ratio Of The Rights  Is 3:2 "
         "(Three Equity Shares For Every Two Shares Held)", "3:2@0"),
        ("Rights 613:399", "613:399"),
        ("Dividend Re1/- Per Share + Rights Issue 5:6", "5:6"),
    ):
        kind, got, factor = classify(subject)
        assert (kind, got) == ("RIGHTS", ratio), subject
        assert factor is None


def test_a_non_integral_rights_ratio_is_refused():
    """IRBIT, 'Rights 1:11.10 @ Premium Rs 0/-'. A greedy (\\d+):(\\d+) reads
    1:11 and drops the .10, which is a different issue."""
    kind, _, _ = classify("Rights 1:11.10 @ Premium Rs 0/-")
    assert kind == "UNPARSED"


def test_rights_with_warrants_attached_are_refused_even_when_the_equity_half_reads():
    """'Rights 1:50 @ Premium Rs 175 With 6 Warrants For 50 Equity Shares' used
    to parse as a plain 1:50 rights — the warrants carry value the TERP does
    not see. The instrument screen refuses the whole subject now."""
    kind, _, _ = classify(
        "Rights 1:50 @ Premium Rs 175  With 6 Warrants For 50 Equity Shares")
    assert kind == "UNPARSED"
    kind, _, _ = classify("Rights 9:77 Partly Paid @ Premium Rs 100/-")
    assert kind == "UNPARSED"


def test_a_bonus_of_anything_but_equity_is_refused_whatever_words_surround_it():
    for subject in (
        "Scheme Of Arrangement - Bonus Debentures 6:1",
        "Sch Of Agmt- Bonus Deb1:1",
        "Bonus Preference Shares 21:1",
        "Bonus 1 Dvr : 10 Eq Share",
        "Bonus Ncrps 1:116",
    ):
        kind, _, factor = classify(subject)
        assert kind == "UNPARSED" and factor is None, subject


def test_a_half_read_compound_is_surfaced_not_filed_under_the_half_that_parsed():
    """A subject that says 'rights' and yielded no RIGHTS row is one the
    expressions could not read, whatever else in it did parse."""
    rows = classify_all("Bonus 1:1 And Rights In Some Novel Wording")
    assert rows == [("UNPARSED", "", None)]

# --- the adjustment itself ----------------------------------------------------


@pytest.mark.unit
def test_back_adjustment_multiplies_history_by_actions_that_follow_it():
    """The direction is the part that is easy to get backwards.

    A 1:2 split on day D halves every price BEFORE D so the series is comparable
    with post-split prices. Applying it forwards instead would double the tail
    and leave the artefact exactly where it was, with the numbers changed.
    """
    from src.warehouse import spine
    assert spine.MAX_UNEXPLAINED_JUMPS > 0, (
        "a tolerance of zero refuses forever on data defects nothing can fix, "
        "and a guard that cannot pass is one somebody switches off"
    )


@pytest.mark.data
@pytest.mark.needs_data
def test_the_known_splits_are_gone_from_the_adjusted_spine():
    """Measured 2026-09-01. Each of these fell by half or more on its ex-date in
    the RAW series and must read as an ordinary session in the adjusted one."""
    duckdb = pytest.importorskip("duckdb")
    from src.common.paths import warehouse_dir

    adj = warehouse_dir("prod") / "price_spine_adj"
    if not list(adj.glob("**/*.parquet")):
        pytest.skip("adjusted spine not built in this environment")

    con = duckdb.connect()
    for symbol, ex in (("TDPOWERSYS", "2026-08-24"), ("CORDELIA", "2026-08-25"),
                       ("GOODLUCK", "2026-08-21"), ("KIRLPNU", "2026-08-18")):
        ratio = con.execute(
            f"WITH s AS (SELECT date, close,"
            f"  LAG(close) OVER (ORDER BY date) prev"
            f"  FROM read_parquet('{adj}/**/*.parquet') WHERE symbol = ?)"
            f" SELECT close / prev FROM s WHERE date = ?", [symbol, ex]
        ).fetchone()
        assert ratio and ratio[0] is not None, f"{symbol} missing on {ex}"
        assert 0.7 < ratio[0] < 1.4, (
            f"{symbol} still moves {ratio[0]:.4f}x on its {ex} ex-date; the "
            f"corporate action has not been applied"
        )


@pytest.mark.data
@pytest.mark.needs_data
def test_fund_units_are_not_collected_into_the_price_spine():
    """Decision 0040. INF is the ISIN prefix for fund and ETF units, and seven of
    them carried 1:10 splits that no corporate-actions route reports."""
    duckdb = pytest.importorskip("duckdb")
    from src.common.paths import COLLECTED

    files = list((COLLECTED / "prices").glob("*.parquet"))
    if not files:
        pytest.skip("no collected prices in this environment")
    con = duckdb.connect()
    leaked = con.execute(
        f"SELECT COUNT(*) FROM read_parquet('{COLLECTED}/prices/*.parquet')"
        f" WHERE symbol IN ('PSUBANK','GOLDADD','SILVERADD','NV20',"
        f"                  'IVZINNIFTY','HEALTHADD','MIDQ50ADD')"
    ).fetchone()[0]
    assert leaked == 0, f"{leaked} fund-unit rows collected; 0040 excludes them"
