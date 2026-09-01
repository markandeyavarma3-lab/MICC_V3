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

from src.ingest.corp_actions import classify

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
