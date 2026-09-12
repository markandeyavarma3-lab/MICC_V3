"""Engine 2 feasibility arithmetic. Pins every number in SEASONALITY_POWER.md.

No warehouse, no database, no seasonality_cell. A memo whose figures are not
reproducible from code is an assertion, and this project does not publish those.
"""

from __future__ import annotations

import math

import pytest

from src.research import seasonality_power as S
from src.research.power import _Z_ALPHA_TWO_SIDED_05, _Z_POWER_80, mde


class TestItem1TheScanSizeIsNotAProduct:
    def test_the_documented_axes_do_not_multiply_to_the_published_figure(self):
        """31,893,556 factors as 2^2 x 37 x 215,497 with 215,497 prime, and none
        of the documented axes (13, 242, 4200, 202, 4, 2) divide it. So the
        figure cannot be reproduced by multiplying the grid together."""
        n, factors, d = S.PRIOR_SCAN_CELLS, [], 2
        while d * d <= n:
            while n % d == 0:
                factors.append(d)
                n //= d
            d += 1
        if n > 1:
            factors.append(n)
        assert factors == [2, 2, 37, 215497]
        assert all(215497 % k for k in (13, 242, 4200, 202, 4, 2, 3, 5, 7, 11))

    def test_the_report_headline_product_is_what_it_claims(self):
        """13 x 242 x 4,200 = 13.2 million, as PROJECT_REPORT.md:386 states."""
        assert S.WINDOW_LENGTHS * S.START_POINTS * S.COMPANIES == 13_213_200

    def test_the_enumeration_is_29_percent_of_the_full_cartesian_grid(self):
        """The shortfall is the explanation: entities have unequal history, so
        not every entity supports every window x start."""
        assert S.cartesian_cells() == 110_789_536
        frac = S.PRIOR_SCAN_CELLS / S.cartesian_cells()
        assert frac == pytest.approx(0.288, abs=0.001)


class TestTheInputsAreTheProjectsOwnMeasurements:
    def test_the_annual_sd_is_backed_out_of_the_repos_own_quoted_mdes(self):
        """configs/scan.yml: "Two observations detect an effect of 49.5%/yr.
        Twenty-one detect 15.3%/yr." Both must imply the same annual sd, or the
        25%/yr this module adopts is invented rather than derived."""
        for n_obs, quoted in ((2, 49.5), (21, 15.3)):
            implied = quoted * math.sqrt(n_obs) / (_Z_ALPHA_TWO_SIDED_05 + _Z_POWER_80)
            assert implied == pytest.approx(S.SD_ANNUAL_PCT, abs=0.05)

    def test_it_agrees_with_the_projects_own_mde_function(self):
        assert mde(S.SD_ANNUAL_PCT, 21) == pytest.approx(15.3, abs=0.05)
        assert mde(S.SD_ANNUAL_PCT, 2) == pytest.approx(49.5, abs=0.05)

    def test_pooling_4200_correlated_names_buys_four(self):
        """configs/scan.yml measured "n_eff 4.3 of 21,000" at this rho."""
        assert S.n_eff(4200) == pytest.approx(4.25, abs=0.01)
        assert S.n_eff(4200) == pytest.approx(1 / S.RHO_CROSS_SECTIONAL, abs=0.02)

    def test_n_eff_is_bounded_by_one_over_rho_however_many_names(self):
        assert S.n_eff(1_000_000) < 1 / S.RHO_CROSS_SECTIONAL + 0.01


class TestItem2MonthlyCellMDEs:
    """A representative monthly cell: 20 firings, one per year."""

    def test_per_stock_mdes(self):
        assert S.mde_monthly_bps(1, correction="none") == pytest.approx(452, abs=1)
        assert S.mde_monthly_bps(S.PRIOR_SCAN_CELLS) == pytest.approx(1110, abs=2)

    def test_pooled_mdes(self):
        kw = dict(n_names=S.COMPANIES)
        assert S.mde_monthly_bps(1, correction="none", **kw) == pytest.approx(219, abs=1)
        assert S.mde_monthly_bps(S.PRIOR_SCAN_CELLS, **kw) == pytest.approx(538, abs=2)

    def test_bh_is_bonferroni_at_one_discovery_and_looser_above_it(self):
        kw = dict(n_names=S.COMPANIES, correction="bh")
        at1 = S.mde_monthly_bps(S.PRIOR_SCAN_CELLS, n_discoveries=1, **kw)
        assert at1 == pytest.approx(S.mde_monthly_bps(S.PRIOR_SCAN_CELLS,
                                                      n_names=S.COMPANIES), abs=0.5)
        at1000 = S.mde_monthly_bps(S.PRIOR_SCAN_CELLS, n_discoveries=1000, **kw)
        assert at1000 == pytest.approx(442, abs=2)
        assert at1000 < at1, "BH only loosens when discoveries exist"


class TestItem4TheBindingConstraintIsSampleSize:
    def test_even_with_no_multiplicity_correction_a_monthly_cell_is_blind(self):
        """THE DECISIVE NUMBER. At m=1 -- a single pre-registered hypothesis,
        zero multiplicity penalty -- a one-month cell still needs 219 bps/month.
        Published calendar effects are 20-300 bps and mostly 50-150. So the
        binding constraint is SAMPLE SIZE, not the correction."""
        floor = S.mde_monthly_bps(1, n_names=S.COMPANIES, correction="none")
        assert floor == pytest.approx(219, abs=1)
        assert floor > 150, "exceeds the bulk of the published effect range"

    def test_longer_windows_help_as_sqrt_of_the_window(self):
        one = S.mde_monthly_bps(1, n_names=S.COMPANIES, correction="none")
        six = S.mde_monthly_bps(1, n_names=S.COMPANIES, correction="none",
                                window_months=6.0)
        assert six == pytest.approx(one / math.sqrt(6), rel=1e-9)
        assert six == pytest.approx(90, abs=1)

    def test_the_largest_spec_that_clears_a_150bps_effect(self):
        """20 pre-registered hypotheses at a 6-month window: 123 bps."""
        v = S.mde_monthly_bps(20, n_names=S.COMPANIES, window_months=6.0)
        assert v == pytest.approx(123, abs=1)
        assert v < 150

    def test_a_full_scan_never_clears_it_at_any_window(self):
        for T in (1.0, 3.0, 6.0, 12.0):
            v = S.mde_monthly_bps(S.PRIOR_SCAN_CELLS, n_names=S.COMPANIES,
                                  window_months=T)
            assert v > 150, f"{T}mo window unexpectedly cleared the bar at {v:.0f}"

    def test_years_required_dwarfs_the_history_available(self):
        assert S.years_required(100, 1) == pytest.approx(96, abs=1)
        assert S.years_required(100, 20) == pytest.approx(183, abs=1)
        assert S.years_required(100, S.PRIOR_SCAN_CELLS) == pytest.approx(580, abs=2)
        assert S.YEARS_AVAILABLE == 21
        assert S.years_required(100, 1) > 4 * S.YEARS_AVAILABLE


class TestTheRankICRouteDiesOnTheUnitOfEvidence:
    def test_at_zero_intra_firing_correlation_it_looks_feasible(self):
        assert S.ic_observations(rho_ic=0.0) == pytest.approx(420)
        assert S.mde_rank_ic(20, rho_ic=0.0) == pytest.approx(0.0224, abs=0.0002)

    def test_but_any_realistic_correlation_pushes_it_past_the_plausible_range(self):
        """Plausible real equity signal IC is 0.02-0.05 (configs/scan.yml:148).
        The sessions inside one March move together, so rho_ic is not zero."""
        assert S.mde_rank_ic(20, rho_ic=0.2) == pytest.approx(0.0502, abs=0.0005)
        assert S.mde_rank_ic(20, rho_ic=0.2) > 0.05

    def test_the_full_scan_clears_the_bar_ONLY_at_exactly_zero_correlation(self):
        """The one place the full 31.9M scan is not hopeless -- and it depends
        entirely on an assumption known to be false. At rho_ic = 0 the scan
        reaches 0.0399, inside the plausible 0.02-0.05 band. One tenth of a
        point of intra-firing correlation destroys it. A feasibility that
        survives only at a boundary value nobody believes is not a feasibility."""
        assert S.mde_rank_ic(S.PRIOR_SCAN_CELLS, rho_ic=0.0) == pytest.approx(
            0.0399, abs=0.0005)
        for r in (0.1, 0.2, 0.3, 0.5, 1.0):
            assert S.mde_rank_ic(S.PRIOR_SCAN_CELLS, rho_ic=r) > 0.05

    def test_one_ic_per_firing_is_invisible_even_pre_registered(self):
        assert S.mde_rank_ic(20, rho_ic=1.0) == pytest.approx(0.1028, abs=0.0005)


class TestCosts:
    def test_costs_are_amortised_over_the_window_and_are_not_the_binding_term(self):
        assert S.cost_bps_per_month(1.0) == pytest.approx(29.33, abs=0.01)
        assert S.cost_bps_per_month(6.0) == pytest.approx(4.89, abs=0.01)
        gross = S.mde_monthly_bps(20, n_names=S.COMPANIES, window_months=6.0)
        assert S.cost_bps_per_month(6.0) < 0.05 * gross, (
            "costs matter, but sample size is what kills this"
        )


class TestTheRegistrationRefusesAnEmptyLedger:
    """WATCHED FAILING 2026-09-12, and it had already happened.

    Run on a machine with no warehouse, the registration script's call into
    provenance created a governance database, wrote the verdict as its only row,
    printed a hash and exited 0. The verdict looked registered and was not: no
    prior artefacts, no trial counters, an empty merkle_log.
    """

    @staticmethod
    def _script():
        import importlib.util
        from pathlib import Path

        p = Path(__file__).resolve().parents[1] / "scripts" / "register_engine2_verdict.py"
        spec = importlib.util.spec_from_file_location("_reg_e2", p)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_a_missing_ledger_is_refused(self, tmp_path, monkeypatch):
        mod = self._script()
        monkeypatch.setattr(mod, "governance_db", lambda _e: tmp_path / "nope.sqlite")
        assert "does not exist" in mod._refuse_an_empty_ledger()

    def test_a_schemaless_file_is_refused(self, tmp_path, monkeypatch):
        import sqlite3

        db = tmp_path / "governance.sqlite"
        sqlite3.connect(str(db)).close()
        mod = self._script()
        monkeypatch.setattr(mod, "governance_db", lambda _e: db)
        assert "no governance schema" in mod._refuse_an_empty_ledger()

    def test_a_freshly_migrated_but_empty_ledger_is_refused(self, tmp_path, monkeypatch):
        """THE ACTUAL FAILURE. A valid, correctly-migrated, entirely empty
        governance database — exactly what provenance creates on a machine
        without one — must not accept a verdict."""
        import sqlite3

        db = tmp_path / "governance.sqlite"
        con = sqlite3.connect(str(db))
        con.execute("CREATE TABLE artefact (artefact_hash TEXT)")
        con.execute("CREATE TABLE merkle_log (id INTEGER)")
        con.commit()
        con.close()
        mod = self._script()
        monkeypatch.setattr(mod, "governance_db", lambda _e: db)
        why = mod._refuse_an_empty_ledger()
        assert why is not None and "empty ledger" in why

    def test_a_ledger_with_history_is_accepted(self, tmp_path, monkeypatch):
        import sqlite3

        db = tmp_path / "governance.sqlite"
        con = sqlite3.connect(str(db))
        con.execute("CREATE TABLE artefact (artefact_hash TEXT)")
        con.execute("INSERT INTO artefact VALUES ('prop_hft_classifier_coverage')")
        con.execute("CREATE TABLE merkle_log (id INTEGER)")
        con.execute("INSERT INTO merkle_log VALUES (1)")
        con.commit()
        con.close()
        mod = self._script()
        monkeypatch.setattr(mod, "governance_db", lambda _e: db)
        assert mod._refuse_an_empty_ledger() is None
