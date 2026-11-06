"""Site-only corrections to investor labels (src/site/labels.py)."""

from __future__ import annotations

import pytest

from src.site import labels

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("raw,want", [
    ("TATA SONS LTD", "CORPORATE"),
    ("HERO MOTOCORP LIMITED", "CORPORATE"),
    ("THREPSI CARE LLP", "CORPORATE"),
    ("SOCIETE GENERALE", "BANK"),
    ("CITIBANK NA", "BANK"),
    ("VONTOBEL FUNDS INC", "FOREIGN_INSTITUTION"),
    ("HULST B V", "FOREIGN_INSTITUTION"),
    ("BRITISH TELECOMMUNICATIONS PLC", "FOREIGN_INSTITUTION"),
])
def test_a_company_s_raw_name_corrects_an_individual_label(raw, want):
    assert labels.proposed("INDIVIDUAL", "NAME_PATTERN", [raw]) == want


@pytest.mark.parametrize("raw", ["SAMINA HAMIED", "VIRENDRA D MHAISKAR", "RAKESH GANGWAL", "LTDA SHAH"])
def test_a_person_s_name_is_left_alone(raw):
    assert labels.proposed("INDIVIDUAL", "NAME_PATTERN", [raw]) is None


def test_a_manual_ruling_is_never_overruled():
    assert labels.proposed("INDIVIDUAL", "MANUAL", ["TATA SONS LTD"]) is None


def test_a_brand_alone_moves_a_broker_only_for_vanguard():
    """FIDELITY SHARES AND SECURITIES is an Indian broker, not the US fund house."""
    assert labels.proposed("BROKER_SEC", "NAME_PATTERN", ["FIDELITY SHARES AND SECURITIES"]) is None
    assert labels.proposed("BROKER_SEC", "NAME_PATTERN", ["VANGUARD TOTAL WORLD STOCK INDEX FUND"]) == "FOREIGN_INSTITUTION"


def test_other_types_are_left_alone():
    assert labels.proposed("UNKNOWN", "NAME_PATTERN", ["SOME FUND LIMITED"]) is None


def test_no_file_means_no_corrections(tmp_path):
    assert labels.load(tmp_path / "absent.csv") == {}


def test_the_corrected_label_reaches_a_deal_and_nothing_else_changes(monkeypatch):
    from src.site import export as X
    monkeypatch.setattr(X, "site_labels", lambda: {"TATA SONS": "CORPORATE"})
    row = lambda name, ptype: ("2026-01-01", "TCS", "INE467B01029", "TCS", "TATA SONS LTD", name, ptype,  # noqa: E731
                               "NAME_PATTERN", None, "SELL", 1, 1.0, 1e7, "NSE", "BULK", False, True)
    d = X._deal(row("TATA SONS", "INDIVIDUAL"))
    assert d["type"] == "CORPORATE" and d["how"] == labels.METHOD
    other = X._deal(row("RAKESH GANGWAL", "INDIVIDUAL"))
    assert other["type"] == "INDIVIDUAL" and other["how"] == "NAME_PATTERN"
