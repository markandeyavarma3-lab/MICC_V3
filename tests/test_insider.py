"""The insider collector and parser, and the two-month silent failure they exist to prevent.

MICC's fetcher went "silently green-but-empty for ~2 months" because
/api/corporates-pit was retired and kept answering HTTP 200 with
{"acqNameList":[],"data":[]}. Every check it had stayed green. The bytes for
those two months are gone.
"""

from __future__ import annotations

import pytest

from src.archive import insider as archive
from src.ingest import insider as parse

pytestmark = pytest.mark.unit


def test_the_live_endpoint_is_the_gg_one():
    """The retired route still answers 200. Using it is the silent failure."""
    assert "corporates-pit-gg" in archive.INDEX_URL, (
        "/api/corporates-pit (without -gg) was retired around April 2026 and "
        "answers 200 with an empty envelope"
    )


def test_an_empty_envelope_is_a_failure_not_a_quiet_day():
    """THE GUARD THAT MATTERS. A well-formed 200 carrying data:[] must not be
    recorded as success. Verified against the real retired endpoint on
    2026-09-01: 28 bytes, status FAILED."""
    import inspect

    src = inspect.getsource(archive.capture_window)
    assert "EMPTY ENVELOPE" in src
    assert 'if not rows:' in src, "no explicit empty-payload branch"
    i, j = src.index("if not rows:"), src.index("digest = hash_bytes")
    assert '"FAILED"' in src[i:j], (
        "an empty payload must be recorded FAILED; anything else reproduces the "
        "two-month silent loss"
    )


def test_one_filing_can_hold_many_transactions():
    """22 archived filings held 39 transactions. Parsing one row per file would
    have dropped 44% of them, and the drop would look like sparse data."""
    import inspect

    src = inspect.getsource(parse.parse_file)
    assert "by_ctx" in src, "no per-context grouping — this parses one row per file"
    assert "SecuritiesAcquiredOrDisposedTransactionType" in src


@pytest.mark.parametrize("raw,expected", [
    ("Promoter", "Promoters"),
    ("Promoter Group", "Promoter Group"),
    ("Promoter and Director", "Promoters"),
    ("KMP", "Key Managerial Personnel"),
])
def test_category_maps_onto_the_vocabulary_0046_measured_on(raw, expected):
    """0046's promoter power figures were measured on the SEED's vocabulary
    (Promoters / Promoter Group). XBRL says 'Promoter' and 'Promoter and
    Director'. A new row that fails to map is silently outside the population
    that measurement was about.

    'Promoter and Director' maps to Promoters because MICC's fetcher did, with
    the comment "promoter is the stronger class", and the seed was normalised
    that way.
    """
    assert parse._CATEGORY.get(raw.strip().lower(), raw) == expected


@pytest.mark.parametrize("raw,expected", [
    ("Acquisition", "Buy"), ("Disposal", "Sell"),
    ("acquired", "Buy"), ("Sale", "Sell"),
])
def test_transaction_type_maps_onto_buy_and_sell(raw, expected):
    assert parse._TXN.get(raw.strip().lower(), raw) == expected


def test_an_unknown_category_passes_through_rather_than_becoming_null():
    """Standing rule 9: UNKNOWN beats inference. 'Trust' and 'Other' are real
    values with no seed equivalent; nulling them would delete information, and
    category_raw always keeps the original either way."""
    assert parse._CATEGORY.get("trust", "Trust") == "Trust"


def test_the_parser_derives_no_eligibility():
    """Transactions in, transactions out. Whether one is an EVENT is the study's
    question; deciding it here is how a filter becomes invisible."""
    import inspect

    src = inspect.getsource(parse)
    for banned in ("eligible", "adv20", "min_value", "ret"):
        assert f"def {banned}" not in src
    assert "price_spine" not in src, "the parser must not read prices"
