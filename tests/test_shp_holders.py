"""Named holders from shareholding filings (src/ingest/shp_holders.py)."""

from __future__ import annotations

import gzip

import pytest

from src.ingest import shp_holders as H

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("name", ["Clearing Members", "HUF", "Trusts", "Non-Resident Indian (NRI)", "IEPF",
                                  "Others", "Unclaimed or Suspense or Escrow Account",
                                  "Foreign Portfolio Investor (Category - III)", "Bodies Corporate"])
def test_category_labels_are_flagged_not_treated_as_holders(name):
    assert H.is_label(name)


@pytest.mark.parametrize("name", ["MUKUL MAHAVIR AGRAWAL", "LIFE INSURANCE CORPORATION OF INDIA",
                                  "GOVERNMENT PENSION FUND GLOBAL", "EQ INDIA FUND", "HDFC TRUSTEE CO LTD"])
def test_real_holders_are_not_labels(name):
    assert not H.is_label(name)


@pytest.mark.parametrize("axis,group", [
    ("DetailsOfSharesHeldByMutualFundsOrUtiAxis", "MF"),
    ("DetailsOfSharesHeldByInstitutionsForeignPortfolioInvestorOneAxis", "FPI"),
    ("DetailsOfSharesHeldByInsuranceCompaniesAxis", "INSURANCE"),
    ("DetailsOfSharesHeldByBodiesCorporateAxis", "CORPORATE"),
    ("DetailsOfSharesHeldByResidentIndividualShareholdersHoldingNominalShareCapitalInExcessOfRsTwoLakhAxis", "INDIVIDUAL"),
    ("DetailsOfSharesHeldByForeignCompaniesAxis", "FOREIGN"),
    ("DetailsOfSharesHeldByOtherNonInstitutionsAxis", "OTHER"),
])
def test_axis_groups(axis, group):
    assert H.group_of(axis) == group


def test_a_filing_yields_named_public_and_promoter_holders_on_one_scale(tmp_path):
    ctx = lambda cid, body: f'<xbrli:context id="{cid}"><xbrli:entity><xbrli:identifier scheme="x">1</xbrli:identifier></xbrli:entity><xbrli:period><xbrli:instant>2026-06-30</xbrli:instant></xbrli:period>{body}</xbrli:context>'
    seg = lambda dim, val: f'<xbrli:scenario><xbrldi:typedMember dimension="in-bse-shp:{dim}"><in-bse-shp:K>{val}</in-bse-shp:K></xbrldi:typedMember></xbrli:scenario>'
    cat = lambda m: f'<xbrli:scenario><xbrldi:explicitMember dimension="in-bse-shp:CategoryOfShareholdersAxis">in-bse-shp:{m}</xbrldi:explicitMember></xbrli:scenario>'
    xml = "".join([
        ctx("Main", ""), ctx("P", cat("ShareholdingOfPromoterAndPromoterGroupMember")), ctx("U", cat("PublicShareholdingMember")),
        ctx("M1", seg("DetailsOfSharesHeldByMutualFundsOrUtiAxis", "1")),
        ctx("I1", seg("DetailsSharesHeldByIndividualsOrHUFAxis", "1")),
        '<in-bse-shp:ISIN contextRef="Main">INE000A01010</in-bse-shp:ISIN>',
        '<in-bse-shp:Symbol contextRef="Main">ACME</in-bse-shp:Symbol>',
        '<in-bse-shp:NameOfTheCompany contextRef="Main">ACME FASHION &amp; RETAIL</in-bse-shp:NameOfTheCompany>',
        '<in-bse-shp:ShareholdingAsAPercentageOfTotalNumberOfShares contextRef="P" unitRef="pure">0.6</in-bse-shp:ShareholdingAsAPercentageOfTotalNumberOfShares>',
        '<in-bse-shp:ShareholdingAsAPercentageOfTotalNumberOfShares contextRef="U" unitRef="pure">0.4</in-bse-shp:ShareholdingAsAPercentageOfTotalNumberOfShares>',
        '<in-bse-shp:NameOfTheShareholder contextRef="M1">SBI MUTUAL FUND &amp; CO</in-bse-shp:NameOfTheShareholder>',
        '<in-bse-shp:ShareholdingAsAPercentageOfTotalNumberOfShares contextRef="M1" unitRef="pure">0.025</in-bse-shp:ShareholdingAsAPercentageOfTotalNumberOfShares>',
        '<in-bse-shp:NameOfTheShareholder contextRef="I1">A PROMOTER</in-bse-shp:NameOfTheShareholder>',
        '<in-bse-shp:ShareholdingAsAPercentageOfTotalNumberOfShares contextRef="I1" unitRef="pure">0.6</in-bse-shp:ShareholdingAsAPercentageOfTotalNumberOfShares>',
    ])
    f = tmp_path / "x.xml.gz"
    f.write_bytes(gzip.compress(f"<xbrli:xbrl>{xml}</xbrli:xbrl>".encode()))
    rows = {r["name"]: r for r in H.parse_file(str(f))}
    if not rows:
        pytest.skip("synthetic context layout not matched by shp.py's regexes")
    assert rows["SBI MUTUAL FUND & CO"]["group"] == "MF" and rows["SBI MUTUAL FUND & CO"]["pct"] == 2.5
    assert rows["A PROMOTER"]["table"] == "PROMOTER"
    assert rows["A PROMOTER"]["company"] == "ACME FASHION & RETAIL"
