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
    cols = ["isin", "quarter_end", "broadcast_date", "is_calendar_quarter",
            "revised", "identity_total", "category", "pct_shares"]
    extra = ["num_shareholders", "num_shares", "category_raw"]
    df = pd.DataFrame([r if len(r) == len(cols) + 3 else (*r, 10.0, float("nan"), r[6]) for r in rows],
                      columns=cols + extra)
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


def test_revised_filings_are_kept_on_their_own_broadcast_date_and_bad_identity_is_excluded(tmp_path):
    """Owner decision (a): the revision is the only version NSE keeps, and its
    broadcast is when the corrected figures became public."""
    p = _holdings(tmp_path, [
        ("I1", "2026-03-31", "2026-04-20", True, False, 100.0, "MutualFund", 5.0),
        ("I1", "2026-06-30", "2026-08-11", True, True, 100.0, "MutualFund", 6.0),     # revised, late
        ("I1", "2026-09-30", "2026-10-15", True, False, 119.6, "MutualFund", 7.0),    # bad file
        ("I1", "2026-12-31", "2027-01-15", True, False, 100.0, "MutualFund", 8.0),
    ])
    s = h.signals(p)
    assert s.attrs["counts"] == {"filings": 4, "revised_kept": 1, "identity_excluded": 1,
                                 "first_filings_excluded": 1, "interval_excluded": 0}
    assert list(s["d_mf"]) == [1.0, 2.0]                  # 06-30 vs 03-31 (revised, kept); 12-31 vs 06-30
    assert list(s["broadcast_date"]) == ["2026-08-11", "2027-01-15"]
    assert list(s["revised"]) == [True, False]


def test_a_change_spanning_more_than_the_interval_cap_is_excluded_and_counted(tmp_path):
    """Owner decision (a): 200 days. A resumption after a three-year gap is
    not a quarterly signal."""
    p = _holdings(tmp_path, [
        ("I1", "2023-03-31", "2023-04-20", True, False, 100.0, "MutualFund", 5.0),
        ("I1", "2026-03-31", "2026-04-20", True, False, 100.0, "MutualFund", 9.0),    # 1,096 days later
        ("I1", "2026-06-30", "2026-07-15", True, False, 100.0, "MutualFund", 9.5),    # 91 days
    ])
    s = h.signals(p)
    assert s.attrs["counts"]["interval_excluded"] == 1
    assert list(s["interval_days"]) == [91] and list(s["d_mf"]) == [0.5]


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
    assert pytest.approx(5e7) == h.CAP_SESSIONS * h.CAP_PCT_ADV * 20e7


# --- verdict, gate, report --------------------------------------------------------


def _res(signal, spread, mde, q, p=0.01):
    return h.TestResult(signal, "char_rel", 18, 3000, spread, 0.005, spread / 0.005, p, q_fdr=q, mde=mde)


def _panel_for_gate(adv=50e7):
    df = _panel(cohorts=3, n=100)
    df["adv20"] = adv; df["tradeable"] = True
    return df


def test_underpowered_when_every_signal_mde_exceeds_the_bound():
    rs = [_res("d_fpi", 0.03, 0.05, 0.01), _res("d_foreign", 0.02, 0.04, 0.01), _res("d_mf", 0.01, 0.03, 0.01)]
    v = h.verdict(rs, {}, _panel_for_gate())
    assert v.landing == "UNDERPOWERED"
    assert all("kill 1" in k[0] for k in v.kills.values())
    assert not any(v.event_gate.values())  # a 3% spread does not pass when the MDE is 5%


def test_alive_needs_the_event_gate_and_a_positive_net_of_cost_spread():
    rs = [_res("d_fpi", 0.04, 0.01, 0.01), _res("d_foreign", 0.001, 0.01, 0.9), _res("d_mf", 0.002, 0.01, 0.9)]
    v = h.verdict(rs, {}, _panel_for_gate(adv=50e7))
    assert v.landing == "POWERED_ALIVE" and v.event_gate["d_fpi"] and v.portfolio_gate["d_fpi"] > 0
    # the same spread in names too thin to trade at the pessimistic level: costs eat it
    v2 = h.verdict(rs, {}, _panel_for_gate(adv=1e6))
    assert v2.portfolio_gate["d_fpi"] < rs[0].spread_mean


def test_dead_when_powered_but_nothing_clears_the_bound_after_fdr():
    rs = [_res("d_fpi", 0.005, 0.01, 0.3), _res("d_foreign", -0.004, 0.01, 0.5), _res("d_mf", 0.002, 0.01, 0.9)]
    v = h.verdict(rs, {}, _panel_for_gate())
    assert v.landing == "POWERED_DEAD" and not any(v.event_gate.values())


def test_kill_2_and_3_name_the_confound_they_found():
    prim = [_res("d_fpi", 0.002, 0.01, 0.9)]
    rob = {"raw_return (kill 3: momentum)": [_res("d_fpi", 0.04, 0.01, 0.01)],
           "untradeable names only (kill 2: liquidity)": [_res("d_fpi", 0.05, 0.01, 0.01)]}
    v = h.verdict(prim, rob, _panel_for_gate())
    assert any("kill 2" in k for k in v.kills["d_fpi"]) and any("kill 3" in k for k in v.kills["d_fpi"])


def test_the_report_names_the_hash_the_landing_and_every_test():
    rs = [_res("d_fpi", 0.005, 0.01, 0.3), _res("d_foreign", -0.004, 0.01, 0.5), _res("d_mf", 0.002, 0.01, 0.9)]
    v = h.verdict(rs, {}, _panel_for_gate())
    text = h.render("abcdef0123456789", rs, {"robustness": {}, "counts": {"filings": 5119}}, v)
    assert "abcdef012345" in text and "POWERED_DEAD" in text
    assert all(s in text for s in ("d_fpi", "d_foreign", "d_mf")) and "filings: 5,119" in text


def test_an_event_gate_pass_that_costs_eat_is_dead_not_alive():
    """Decision 0003: both gates, not either. A 2% spread in names thin enough
    that the pessimistic round trip costs more than 2% is a paper result."""
    rs = [_res("d_fpi", 0.02, 0.01, 0.01), _res("d_foreign", 0.001, 0.01, 0.9), _res("d_mf", 0.002, 0.01, 0.9)]
    v = h.verdict(rs, {}, _panel_for_gate(adv=2e5))   # Rs 2 lakh/day ADV: impact dwarfs the spread
    assert v.event_gate["d_fpi"] and v.portfolio_gate["d_fpi"] < 0
    assert v.landing == "POWERED_DEAD"


# --- the market leg (0077) --------------------------------------------------------


def test_the_market_leg_is_the_total_return_level_and_never_the_net_one(tmp_path, monkeypatch):
    """`ntr` is net of withholding and the host did not compute it before
    ~2014 — NULL on 4,957 of 7,860 rows. Reading it in place of `tri` does not
    fail; it silently starts the market series nineteen years late and drops
    every cohort before then for want of a benchmark."""
    import duckdb

    d = tmp_path / "index_tri"
    d.mkdir()
    df = pd.DataFrame(
        [("1995-01-01", "NIFTY500", 1000.0, None),
         ("2026-09-18", "NIFTY500", 37000.0, 30000.0),
         ("2026-09-18", "NIFTY50", 26000.0, 21000.0),   # a different index, not this leg
         ("2026-09-17", "NIFTY500", 0.0, None)],        # a zero level is not a level
        columns=["date", "index_key", "tri", "ntr"])
    duckdb.connect().execute(f"COPY (SELECT * FROM df) TO '{d / 'index_tri.parquet'}' (FORMAT PARQUET)")
    monkeypatch.setattr(h, "COLLECTED", tmp_path)

    got = duckdb.connect().execute(h.market_tri_sql()).fetchall()
    assert sorted((str(a), b) for a, b in got) == [("1995-01-01", 1000.0), ("2026-09-18", 37000.0)]


def test_the_panel_measures_market_relative_against_the_headline_total_return_index():
    """0077, and the owner's decision this session. `mkt_rel` subtracted a
    PRICE index until 2026-09-19, crediting the strategy with the market's
    dividends — ~0.3%/quarter against this study's own 1.5%/quarter bound."""
    import inspect

    src = inspect.getsource(h.panel)
    assert "market_tri_sql()" in src
    assert "market_series_sql()" not in src


def test_the_registration_spec_says_which_market_the_secondary_measure_uses():
    """The spec is hashed as a whole, so prose that names the wrong benchmark
    freezes the wrong description of what was measured."""
    import importlib.util
    import json
    from pathlib import Path

    root = Path(h.__file__).resolve().parents[2]
    spec_mod = importlib.util.spec_from_file_location(
        "register_exp004", root / "scripts" / "register_exp004.py")
    reg = importlib.util.module_from_spec(spec_mod)
    spec_mod.loader.exec_module(reg)

    spec = reg.build_spec((2500, 2500, 2886))
    assert "NIFTY 500 TOTAL RETURN" in spec["benchmark_policy"].upper()
    assert "collected:index_tri" in spec["benchmark_policy"]
    # Every preliminary run is recorded: one power number with nothing to
    # compare it against cannot say whether the sweep is helping.
    runs = json.loads(spec["exploratory_prior_run"])["runs"]
    assert len(runs) >= 3 and [r["date"] for r in runs] == sorted(r["date"] for r in runs)


# --- exits: the names that did not reach the horizon (0076, owner 2026-10-02) ----

from datetime import date, timedelta  # noqa: E402

CAL = [date(2025, 1, 1) + timedelta(days=i) for i in range(40)]


def _ev(**kw):
    base = dict(isin="I1", quarter_end="2024-12-31", symbol="ACME", entry_date=CAL[0],
                entry_open=100.0, entry_open_raw=50.0, own_exit_date=None, own_exit_close=float("nan"),
                last_eq_date=CAL[3], last_eq_close=80.0)
    base.update(kw)
    return pd.DataFrame([base])


def _later(rows):
    return pd.DataFrame(rows, columns=["symbol", "d", "close", "adjusted"])


def test_a_name_that_reaches_the_horizon_exits_there():
    out = h.price_exits(_ev(own_exit_date=CAL[5], own_exit_close=110.0, last_eq_date=CAL[30]),
                        CAL, _later([]), 5).iloc[0]
    assert out["exit_reason"] == "HORIZON" and out["ret"] == pytest.approx(0.10)


def test_a_name_moved_to_another_series_exits_at_its_real_price_against_the_raw_entry():
    """The 105: left EQ for BE and kept trading. Its BE price is raw, so the
    entry must be the raw open too — never the adjusted one."""
    out = h.price_exits(_ev(), CAL, _later([("ACME", CAL[4], 45.0, False),
                                             ("ACME", CAL[5], 40.0, False),
                                             ("ACME", CAL[9], 30.0, False)]), 5).iloc[0]
    assert out["exit_reason"] == "MOVED"
    assert out["exit_date"] == CAL[5] and out["ret"] == pytest.approx(40.0 / 50.0 - 1)


def test_a_new_isin_on_the_same_symbol_exits_on_the_adjusted_spine():
    out = h.price_exits(_ev(), CAL, _later([("ACME", CAL[5], 120.0, True),
                                             ("ACME", CAL[8], 121.0, True)]), 5).iloc[0]
    assert out["exit_reason"] == "MOVED" and out["ret"] == pytest.approx(0.20)


def test_a_name_that_stopped_everywhere_is_priced_at_the_recovery_factors():
    out = h.price_exits(_ev(), CAL, _later([]), 5).iloc[0]
    assert out["exit_reason"] == "STOPPED"
    assert out["ret"] == pytest.approx(-1.0)                 # rf 0.0, the headline (0052)
    assert out["ret_rf25"] == pytest.approx(80 * 0.25 / 100 - 1)
    assert out["ret_rf50"] == pytest.approx(80 * 0.50 / 100 - 1)


def test_a_name_that_moved_then_stopped_before_the_exit_is_stopped_at_its_last_trade():
    out = h.price_exits(_ev(), CAL, _later([("ACME", CAL[4], 45.0, False)]), 5).iloc[0]
    assert out["exit_reason"] == "STOPPED" and out["exit_date"] == CAL[4]
    assert out["ret_rf50"] == pytest.approx(45 * 0.5 / 50 - 1)


def test_a_window_past_the_data_or_a_name_still_trading_is_censored_not_priced():
    past = h.price_exits(_ev(entry_date=CAL[-3]), CAL, _later([]), 5).iloc[0]
    live = h.price_exits(_ev(last_eq_date=CAL[-2]), CAL, _later([]), 5).iloc[0]
    assert past["exit_reason"] == "CENSORED" and live["exit_reason"] == "CENSORED"
    assert np.isnan(past["ret"]) and np.isnan(live["ret"])


# --- the robustness lines the spec promises ---------------------------------------


def test_holder_counts_and_the_share_change_flag_come_from_the_filing(tmp_path):
    p = _holdings(tmp_path, [
        ("I1", "2026-03-31", "2026-04-20", True, False, 100.0, "FPI_Cat1", 10.0, 40.0, None, "x"),
        ("I1", "2026-03-31", "2026-04-20", True, False, 100.0, "Promoter", 60.0, 5.0, 1000.0,
         "ShareholdingOfPromoterAndPromoterGroupMember"),
        ("I1", "2026-06-30", "2026-07-15", True, False, 100.0, "FPI_Cat1", 9.0, 46.0, None, "x"),
        ("I1", "2026-06-30", "2026-07-15", True, False, 100.0, "Promoter", 60.0, 5.0, 2000.0,
         "ShareholdingOfPromoterAndPromoterGroupMember"),   # a 1:1 bonus
    ])
    s = h.signals(p)
    assert list(s["d_n_fpi"]) == [6.0]
    assert bool(s["share_change"].iloc[0]) is True


def test_the_block_bootstrap_ci_brackets_the_mean_and_is_seeded():
    x = pd.Series(np.random.default_rng(3).normal(0.02, 0.05, size=40))
    lo, hi = h.block_bootstrap_ci(x)
    assert lo < x.mean() < hi and h.block_bootstrap_ci(x) == (lo, hi)
    assert all(np.isnan(v) for v in h.block_bootstrap_ci(pd.Series([0.1, 0.2])))


def test_kill_4_names_a_spread_that_lives_in_corporate_actions():
    real = _res("d_fpi", 0.05, 0.01, 0.01)
    robust = {h.KILL4: [_res("d_fpi", 0.001, 0.01, 0.5)]}
    v = h.verdict([real, _res("d_foreign", 0.0, 0.01, 0.9), _res("d_mf", 0.0, 0.01, 0.9)],
                  robust, _panel_for_gate())
    assert any("kill 4" in k for k in v.kills["d_fpi"])


def test_run_computes_every_robustness_line_the_spec_names():
    """The spec promised seven robustness lines and the code computed three.
    run() cannot execute unregistered, so its source is the contract."""
    import inspect
    src = inspect.getsource(h.run)
    for promised in ("market-relative", "winsorised", "holder-count", "horizon",
                     "recovery factor", "KILL2", "KILL3", "KILL4", "calendar filings only"):
        assert promised in src, promised
