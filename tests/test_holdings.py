"""exp_004's machinery, before its data is complete and behind its guard."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.research import holdings as h

pytestmark = pytest.mark.unit


# --- the guard -----------------------------------------------------------------


def test_the_panel_refuses_to_run_unregistered(monkeypatch, tmp_path):
    """signals() is a parse; panel() joins them to returns. The second must not
    exist before the spec is frozen."""
    monkeypatch.setattr(h, "governance_db", lambda env=None: tmp_path / "none.sqlite")
    with pytest.raises(RuntimeError, match="not REGISTERED"):
        h.panel()
    with pytest.raises(RuntimeError, match="not REGISTERED"):
        h.run()


# --- signals, from a tiny holdings table -----------------------------------------


def _holdings(tmp_path, rows):
    import duckdb
    p = tmp_path / "h.parquet"
    df = pd.DataFrame(rows, columns=["isin", "quarter_end", "broadcast_date", "is_calendar_quarter",
                                     "revised", "identity_total", "category", "pct_shares"])
    duckdb.connect().execute(f"COPY (SELECT * FROM df) TO '{p}' (FORMAT PARQUET)")
    return p


def test_signals_are_changes_since_the_previous_filing_with_the_interval_carried(tmp_path):
    p = _holdings(tmp_path, [
        ("I1", "2026-03-31", "2026-04-20", True, False, 100.0, "FPI_Cat1", 10.0),
        ("I1", "2026-03-31", "2026-04-20", True, False, 100.0, "MutualFund", 5.0),
        ("I1", "2026-06-04", "2026-06-11", False, False, 100.0, "FPI_Cat1", 12.0),   # off-cycle
        ("I1", "2026-06-04", "2026-06-11", False, False, 100.0, "MutualFund", 5.0),
        ("I1", "2026-06-30", "2026-07-15", True, False, 100.0, "FPI_Cat1", 11.0),
        ("I1", "2026-06-30", "2026-07-15", True, False, 100.0, "MutualFund", 4.0),
    ])
    s = h.signals(p)
    assert len(s) == 2                                   # the first filing has no prior
    assert list(s["d_fpi"].round(2)) == [2.0, -1.0]      # since the PREVIOUS filing, off-cycle kept
    assert list(s["interval_days"]) == [65, 26]
    assert list(s["cohort"]) == ["2026Q2", "2026Q2"]
    assert s.attrs["counts"]["first_filings_excluded"] == 1


def test_an_absent_category_is_zero_in_the_new_taxonomy_and_null_foreign_in_the_old(tmp_path):
    """V1.1+ omits a zero holding; a fund's EXIT would otherwise vanish. The old
    taxonomy cannot express the foreign total, so it stays unknown there."""
    p = _holdings(tmp_path, [
        ("N1", "2026-03-31", "2026-04-20", True, False, 100.0, "MutualFund", 2.0),
        ("N1", "2026-03-31", "2026-04-20", True, False, 100.0, "PublicTotal", 60.0),
        ("N1", "2026-06-30", "2026-07-15", True, False, 100.0, "PublicTotal", 60.0),  # MF omitted = 0
        ("O1", "2021-09-30", "2021-10-20", True, False, 100.0, "Institutions_Total_OldTaxonomy", 5.0),
        ("O1", "2021-09-30", "2021-10-20", True, False, 100.0, "FPI_Undivided", 3.0),
        ("O1", "2021-12-31", "2022-01-20", True, False, 100.0, "Institutions_Total_OldTaxonomy", 5.0),
        ("O1", "2021-12-31", "2022-01-20", True, False, 100.0, "FPI_Undivided", 4.0),
    ])
    s = h.signals(p).set_index("isin")
    assert s.loc["N1", "d_mf"] == pytest.approx(-2.0)     # the exit is a signal
    assert s.loc["O1", "d_fpi"] == pytest.approx(1.0)
    assert np.isnan(s.loc["O1", "d_foreign"])             # unknown, not zero


def test_revised_and_bad_identity_filings_are_excluded_and_counted(tmp_path):
    p = _holdings(tmp_path, [
        ("I1", "2026-03-31", "2026-04-20", True, False, 100.0, "MutualFund", 5.0),
        ("I1", "2026-06-30", "2026-07-15", True, True, 100.0, "MutualFund", 6.0),     # revised
        ("I1", "2026-09-30", "2026-10-15", True, False, 119.6, "MutualFund", 7.0),    # bad file
        ("I1", "2026-12-31", "2027-01-15", True, False, 100.0, "MutualFund", 8.0),
    ])
    s = h.signals(p)
    assert s.attrs["counts"] == {"filings": 4, "revised_excluded": 1, "identity_excluded": 1, "first_filings_excluded": 1}
    assert list(s["d_mf"]) == [3.0]                       # 2026-12-31 vs 2026-03-31, the survivors


# --- the estimator ---------------------------------------------------------------


def _panel(cohorts=6, n=100, effect=0.0, seed=0):
    rng = np.random.default_rng(seed)
    rows = []
    for c in range(cohorts):
        sig = rng.normal(size=n)
        out = rng.normal(0, 0.1, size=n) + effect * sig
        for i in range(n):
            rows.append((f"I{i}", f"202{c // 4}Q{c % 4 + 1}", sig[i], out[i], 1e8))
    return pd.DataFrame(rows, columns=["isin", "cohort", "d_x", "y", "adv20"])


def test_decile_spread_is_top_minus_bottom_per_cohort_and_drops_thin_cohorts():
    df = _panel(cohorts=3, n=100)
    thin = pd.DataFrame([("T", "2030Q1", 1.0, 1.0, 1e8)] * 5, columns=df.columns)
    s = h.decile_spreads(pd.concat([df, thin]), "d_x", "y")
    assert len(s) == 3 and "2030Q1" not in s.index
    g = df[df.cohort == "2020Q1"].sort_values("d_x")
    assert s["2020Q1"] == pytest.approx(g["y"].iloc[-10:].mean() - g["y"].iloc[:10].mean())


def test_a_real_effect_is_found_and_no_effect_is_not():
    null = h._test(_panel(cohorts=8, n=200, effect=0.0), "d_x", "y", permutations=200)
    real = h._test(_panel(cohorts=8, n=200, effect=0.05), "d_x", "y", permutations=200)
    assert null.p_perm > 0.05 and real.p_perm < 0.05
    assert real.spread_mean > 0.1  # 5% x ~1.75 sd gap between decile means


def test_bh_is_the_step_up_with_the_running_minimum():
    rs = [h.TestResult("a", "y", 5, 100, 0, 1, 0, p) for p in (0.01, 0.04, 0.03)]
    h.bh(rs)
    q = {r.p_perm: r.q_fdr for r in rs}
    assert q[0.01] == pytest.approx(0.03) and q[0.03] == pytest.approx(0.04) and q[0.04] == pytest.approx(0.04)


def test_the_tail_rule_is_per_cohort_and_uses_the_pessimistic_cap():
    """Rs 50 crore a side over a decile of 10 = Rs 5 crore a name; 5 sessions
    at 5% must absorb it, so ADV20 must be >= Rs 20 crore/day."""
    df = _panel(cohorts=1, n=100)
    df["adv20"] = 19.9e7
    df.loc[df.index[:3], "adv20"] = 20.1e7
    t = h.tradeable(df)
    assert t["tradeable"].sum() == 3
    assert h.CAP_SESSIONS * h.CAP_PCT_ADV * 20e7 == pytest.approx(5e7)
