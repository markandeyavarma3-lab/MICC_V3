"""The resignation rule, on real filing wordings (NSE announcements, 2014-2026)."""

from __future__ import annotations

import pytest

from src.research import resignations as R

CASES = [  # (category, text, role) — every text is a real filing's wording
    ("Resignation", "Gulshan Polyols Limited has informed the Exchange regarding Resignation of M/s Rajeev "
     "Singal & Co., Chartered Accountants, from the office of Statutory Auditor of the Company.", "AUDITOR"),
    ("Resignation of Statutory Auditor", "BHARAT WIRE ROPES LIMITED has informed the Exchange about "
     "Resignation of Statutory Auditor", "AUDITOR"),
    ("Resignation", "MIRC Electronics Limited has informed the Exchange regarding Resignation of Mr Rafique "
     "Malik as Non- Executive Independent Director of the company w.e.f. November 02, 2023.", "INDEPENDENT_DIRECTOR"),
    ("Resignation of Independent director", "KSHITIJ POLYLINE LIMITED has informed the Exchange about "
     "Resignation of Independent director.", "INDEPENDENT_DIRECTOR"),
    ("Change in Director(s)", "Uniply Industries Limited has informed the Exchange that Mr. Ramakanta Panda and "
     "Mr. M.S Shaine Indepedent Directors of the Company have resigned from the Board", "INDEPENDENT_DIRECTOR"),
    ("Resignation", "Bliss GVS Pharma Limited has informed the Exchange regarding Resignation of Mr Gagan "
     "Harsh Sharma as Managing Director of the company w.e.f. November 06, 2025.", "CEO_MD"),
    ("Resignation", "TPL Plastech Limited has informed the Exchange regarding Resignation of Mr. Akshay "
     "Chandan as Chief Executive Officer of the company w.e.f. February 09, 2025", "CEO_MD"),
    ("Resignation", "JM Financial Limited has informed the Exchange regarding Resignation of Mr Manish Sheth "
     "as Chief Financial Officer of the company w.e.f. September 30, 2023.", "CFO"),
    ("Change in Directors/ Key Managerial Personnel", "Intimation under Regulation 30 ... Resignation of "
     "Mr. Anjanikumar Sharma as CFO & KMP", "CFO"),
    ("Resignation", "Xpro India Limited has informed the Exchange regarding Resignation of Mr Amit Dhanuka as "
     "Company Secretary & Compliance Officer of the company w.e.f. January 15, 2023.", "ROUTINE"),
    ("Resignation", "Abans Holdings Limited has informed the Exchange regarding Resignation of Mr Shivshankar "
     "Singh as Non- Executive Director of the company w.e.f. February 13, 2024.", "OTHER_DIRECTOR"),
    ("Resignation", "PDS Limited has informed the Exchange regarding Resignation of Mr Saurabh Saxena as Group "
     "Chief Information Officer of the company w.e.f. May 18, 2025.", "OTHER_OFFICER"),
    ("Resignation of Director/KMP/SMP", "Welspun Corp Limited has informed the Exchange about Resignation of "
     "Director/KMP/SMP", "UNKNOWN"),
    ("General Updates", "Shradha Infraprojects Limited has informed the Exchange about General Updates regarding "
     "execution of Supplemental Limited Liability Agreement related to the Resignation-cum-disinvestment from "
     "certain LLPs", None),
    ("Updates", "Lumax Industries Limited has informed the Exchange regarding Intimation to Shareholders for "
     "Transfer of Unpaid/Unclaimed Interim Dividend", None),
]


@pytest.mark.unit
@pytest.mark.parametrize("cat, text, role", CASES)
def test_each_role_is_read_from_the_filing(cat, text, role):
    assert R.classify(cat, text) == role


@pytest.mark.unit
def test_an_internal_auditor_is_not_the_statutory_auditor():
    assert R.classify("Resignation", "Resignation of M/s X & Co. as Internal Auditor of the Company") == "OTHER_OFFICER"


@pytest.mark.unit
def test_a_company_day_keeps_its_strongest_role_and_clusters_are_one_event():
    rows = [{"desc": "Resignation", "attchmntText": "Resignation of Mr A as Company Secretary", "sm_isin": "INE1",
             "sort_date": "2020-01-06 10:00"},
            {"desc": "Resignation", "attchmntText": "Resignation of Mr B as Independent Director", "sm_isin": "INE1",
             "sort_date": "2020-01-06 18:00"},
            {"desc": "Resignation", "attchmntText": "Resignation of Mr C as Independent Director", "sm_isin": "INE1",
             "sort_date": "2020-01-10 10:00"}]
    evs = R.events(rows)
    assert [(e.date, e.role) for e in evs] == [("2020-01-06", "INDEPENDENT_DIRECTOR"), ("2020-01-10", "INDEPENDENT_DIRECTOR")]
    sessions = ["2020-01-06", "2020-01-07", "2020-01-08", "2020-01-09", "2020-01-10"]
    assert [e.date for e in R.first_in_window(evs, sessions)] == ["2020-01-06"]


@pytest.mark.unit
def test_a_role_named_elsewhere_in_a_multi_item_filing_is_not_the_one_that_resigned():
    text = ("Outcome of Board Meeting: the Board considered and approved the unaudited financial results with the "
            "limited review report of the Statutory Auditors of the Company. " + "x " * 120 +
            "The Board noted the resignation of Mr. A as Company Secretary of the Company.")
    assert R.classify("Outcome of Board Meeting", text) == "ROUTINE"


@pytest.mark.unit
def test_an_auditor_of_a_subsidiary_is_not_the_companys_auditor():
    text = ("views of the audit committee of the Company on resignation of the statutory auditor of Arvind Youth "
            "Brands Private Limited, a material subsidiary of the Company")
    assert R.classify("Updates", text) == "OTHER_OFFICER"


@pytest.mark.unit
def test_explore_refuses_any_confirm_event():
    import pandas as pd

    from src.research import resignation_study as S
    df = pd.DataFrame({"tdate": ["2018-12-31", "2019-01-02"], "role": ["CFO", "CFO"],
                       **{f"ab_{b}": [0.01, -0.02] for b in S.BENCHES}})
    with pytest.raises(S.ConfirmDataError):
        S.explore(df)
    ok = S.explore(df[df["tdate"] < S.EXPLORE_END].copy())
    assert ok.empty                                        # one event is below the 10-event floor


@pytest.mark.unit
def test_governance_is_the_four_information_roles():
    assert R.GOVERNANCE == {"AUDITOR", "INDEPENDENT_DIRECTOR", "CEO_MD", "CFO"}


@pytest.mark.unit
def test_the_registered_read_needs_both_the_t_and_the_effect_floor():
    import numpy as np
    import pandas as pd

    from src.research import resignation_study as S
    months = pd.date_range("2014-01-15", periods=150, freq="MS").strftime("%Y-%m-%d")
    rng = np.random.default_rng(3)
    def run(mu, sd):
        d = pd.Series(np.repeat(months, 5)); x = pd.Series(rng.normal(mu, sd, len(d)))
        return S.decide(d, x)["verdict"]
    assert run(-0.02, 0.05) == "DRIFT_CONFIRMED"
    assert run(-0.003, 0.004) == "SIGNIFICANT_BUT_SMALL"
    assert run(0.0, 0.05) == "NO_DRIFT"
    short = pd.Series(np.repeat(months[:100], 3))
    assert S.decide(short, pd.Series(np.zeros(len(short))))["verdict"] == "UNDERPOWERED"
