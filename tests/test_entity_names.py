"""Counting-grade entity-name normalisation, for Workstream 3.

NOT step 3.6. `participant_aliases` is a reviewed, persisted alias table with a
merge queue; this is a pure function that makes a COUNT trustworthy. 0057
measured the cost of not having it: 19 round-trip pairs escape detection because
one entity appears under two spellings on the same symbol and day.

The bar is deliberately low and the failure mode is deliberately chosen. Merging
two distinct entities inflates a track record and manufactures a finding;
failing to merge two spellings of one entity splits a track record and hides one.
Of those, the second is the safe error, so this normalises conservatively.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


def test_case_and_punctuation_collapse():
    from src.research.entity_names import normalize

    assert normalize("Societe Generale") == normalize("SOCIETE GENERALE")
    assert normalize("CROSSEAS CAPITAL SERVICES PVT. LTD.") == \
        normalize("CROSSEAS CAPITAL SERVICES PVT LTD")


def test_entity_suffix_variants_merge():
    """The measured case from 0057: Goldman Sachs Investments (Mauritius) I
    appears under six spellings and splits a 36-deal record into 20/9/4/1/1/1."""
    from src.research.entity_names import normalize

    variants = [
        "GOLDMAN SACHS INVESTMENTS MAURITIUS  I LTD",
        "GOLDMAN SACHS INVESTMENTS MAURITIUS I LIMITED",
        "GOLDMAN SACHS INVESTMENTS (MAURITIUS) I LIMITED",
        "GOLDMAN SACHS INVESTMENTS (MAURITIUS) I LTD.",
        "GOLDMAN SACHS INVESTMENTS MAURITIUS  I LIMITED",
        "GOLDMAN SACHS INVESTMENTS MAURITIUS I LTD",
    ]
    assert len({normalize(v) for v in variants}) == 1


def test_distinct_entities_do_not_merge():
    """THE ERROR THAT MANUFACTURES FINDINGS. Merging two real entities pools
    their trades into one inflated track record. Numbered and regional variants
    are different legal entities and must survive."""
    from src.research.entity_names import normalize

    assert normalize("GOLDMAN SACHS INVESTMENTS MAURITIUS I LTD") != \
        normalize("GOLDMAN SACHS INVESTMENTS MAURITIUS II LTD")
    assert normalize("ISHARES MSCI INDIA ETF") != \
        normalize("ISHARES MSCI INDIA SMALL-CAP ETF")
    assert normalize("CITIGROUP GLOBAL MARKETS MAURITIUS PVT LTD") != \
        normalize("CITIGROUP GLOBAL MARKETS INDIA PVT LTD")
    assert normalize("MORGAN STANLEY ASIA SINGAPORE PTE") != \
        normalize("MORGAN STANLEY FRANCE SA")


def test_a_suffix_only_name_does_not_collapse_to_nothing():
    """Stripping every suffix from a name that is only suffixes would map it to
    the empty string, and every such name would then merge into one entity."""
    from src.research.entity_names import normalize

    assert normalize("LIMITED") != ""
    assert normalize("THE PVT LTD") != ""


def test_normalisation_is_idempotent():
    from src.research.entity_names import normalize

    for s in ("SOCIETE GENERALE", "BNP PARIBAS ARBITRAGE", "HRTI PRIVATE LIMITED"):
        assert normalize(normalize(s)) == normalize(s)
