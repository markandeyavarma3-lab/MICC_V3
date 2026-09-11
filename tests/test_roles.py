"""Economic-role classification, Workstream 3 item 2.

THE STEP THAT PREVENTS A MANUFACTURED EDGE. A cash bulk buy from a derivatives
arbitrage desk is one leg of a hedge, not a directional view. Tiering returns
without separating those from genuine long-only positions measures the hedge
and calls it skill — and it would look excellent in-sample, because a delta
hedge is mechanically related to the underlying's move.

Classification happens BEFORE any return statistic is computed. These tests are
written before src/research/roles.py exists.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


def test_odi_issuers_are_identified_by_their_own_label():
    """`- ODI` in an NSE counterparty name means Offshore Derivative Instrument:
    a participatory note. The named entity is the ISSUER, never the beneficial
    owner who chose the trade."""
    from src.research.roles import classify

    assert classify("GOLDMAN SACHS BANK EUROPE SE ODI") == "ODI_ISSUER"
    assert classify("MORGAN STANLEY ASIA SINGAPORE PTE ODI") == "ODI_ISSUER"


def test_index_vehicles_are_identified():
    from src.research.roles import classify

    for n in ("ISHARES MSCI INDIA ETF", "ISHARES CORE MSCI EMERGING MARKETS ETF",
              "POWERSHARES INDIA PORTFOLIO"):
        assert classify(n) == "INDEX_VEHICLE", n

    # `SMALLCAP WORLD FUND` was in this list and the classifier called it
    # UNKNOWN. The TEST was wrong. A bare "... FUND" cannot be told from a hedge
    # fund by name, and loosening the pattern to `FUND` would sweep in CRESTA
    # FUND, MAVI INVESTMENT FUND and INDIA MAX INVESTMENT FUND — none of which
    # is demonstrably long-only. UNKNOWN is the conservative default working as
    # designed, and the fix was to correct the expectation rather than the rule.
    assert classify("SMALLCAP WORLD FUND") == "UNKNOWN"


def test_arbitrage_desks_are_identified():
    from src.research.roles import classify

    assert classify("BNP PARIBAS ARBITRAGE") == "ARBITRAGE"
    assert classify("INTEGRATED CORE STRATEGIES ASIA PTE") == "ARBITRAGE"


def test_indian_long_only_institutions_are_identified():
    """The class the study is actually about. These were invisible before
    normalisation — HDFC Standard Life carried eight spellings."""
    from src.research.roles import classify

    for n in ("HDFC MUTUAL FUND", "SBI MUTUAL FUND", "ICICI PRUDENTIAL MUTUAL FUND",
              "ICICI PRUDENTIAL LIFE INSURANCE", "SBI LIFE INSURANCE",
              "RELIANCE MUTUAL FUND"):
        assert classify(n) == "LONG_ONLY", n


def test_bank_execution_arms_are_identified():
    """An offshore vehicle of a global bank is executing for someone else. The
    name on the disclosure is the conduit."""
    from src.research.roles import classify

    for n in ("CITIGROUP GLOBAL MARKETS MAURITIUS", "DEUTSCHE SECURITIES MAURITIUS",
              "MERRILL LYNCH CAPITAL MARKETS ESPANA S A SVB",
              "CREDIT SUISSE SINGAPORE", "NOMURA SINGAPORE", "MACQUARIE BANK"):
        assert classify(n) == "BANK_EXECUTION", n


def test_an_unrecognised_name_is_unknown_not_long_only():
    """THE DEFAULT MATTERS. Defaulting to LONG_ONLY would sweep every
    unclassifiable conduit into the alpha test. UNKNOWN is excluded from the
    headline and reported separately."""
    from src.research.roles import classify

    assert classify("SILVERTOSS SHOPPERS") == "UNKNOWN"
    assert classify("L7 HITECH") == "UNKNOWN"


def test_the_excluded_classes_are_declared_not_inferred():
    from src.research import roles

    assert "ARBITRAGE" in roles.EXCLUDED_FROM_ALPHA
    assert "ODI_ISSUER" in roles.EXCLUDED_FROM_ALPHA
    assert "INDEX_VEHICLE" in roles.EXCLUDED_FROM_ALPHA
    assert "LONG_ONLY" not in roles.EXCLUDED_FROM_ALPHA
    for cls in roles.EXCLUDED_FROM_ALPHA:
        assert len(roles.EXCLUSION_REASON[cls]) > 60, f"{cls} excluded without a reason"
