"""Tests for the exploration/selection/confirmation partition.

The load-bearing test in this file is `test_rename_does_not_move_a_company`. It
encodes the measurement that justified the whole ISIN design: 459 renamed symbols
covering 26,046 deal rows, 11.04% of the corpus. If that test ever fails the
confirmation set is contaminated silently, and no downstream output would look
wrong.
"""

from __future__ import annotations

import pytest

from src.research.split import (
    BUCKETS,
    ConfirmationGuard,
    SplitViolation,
    assign,
    bucket,
    effective_sample_size,
    excluded,
    spec,
    split_key,
)

pytestmark = pytest.mark.unit


# --- the spec itself ---------------------------------------------------------


def test_spec_loads_and_self_validates():
    cfg = spec()
    assert cfg["version"] == 1
    assert set(cfg["strata"]) == {"EXPLORE", "SELECT", "CONFIRM"}


def test_fractions_sum_to_one():
    assert abs(sum(s["fraction"] for s in spec()["strata"].values()) - 1.0) < 1e-9


def test_declared_fractions_match_the_ranges_that_do_the_work():
    # Two sources of truth for one number is how docs drift. Here the drift would
    # be silent and statistical, so the loader refuses it.
    cfg = spec()
    for name, (lo, hi) in cfg["assignment"]["ranges"].items():
        assert abs(cfg["strata"][name]["fraction"] - (hi - lo) / BUCKETS) < 1e-9


def test_exploration_is_free_and_the_other_two_are_not():
    # If EXPLORE ever starts charging, the file has lost its entire purpose.
    cfg = spec()["strata"]
    assert cfg["EXPLORE"]["charges_trial_counter"] is False
    assert cfg["SELECT"]["charges_trial_counter"] is True
    assert cfg["CONFIRM"]["charges_trial_counter"] is True


# --- keys --------------------------------------------------------------------


def test_isin_is_preferred_over_symbol():
    key, kind = split_key("ZYDUSLIFE", "INE010B01027")
    assert (key, kind) == ("INE010B01027", "ISIN")


@pytest.mark.parametrize("missing", [None, "", "  ", "nan", "NaN"])
def test_falls_back_to_symbol_when_isin_is_absent(missing):
    key, kind = split_key("SOMENAME", missing)
    assert (key, kind) == ("SYM:SOMENAME", "SYM")


def test_rename_does_not_move_a_company():
    """The measurement this design exists for.

    CADILAHC -> ZYDUSLIFE and PRISMCEM -> PRSMJOHNSN are real renames in
    isin_renames.parquet. Keyed on the symbol these companies would sit in one
    stratum under the old name and another under the new one. 459 such symbols
    appear in deal data, carrying 11.04% of all bulk and block rows.
    """
    for isin, old, new in [
        ("INE010B01027", "CADILAHC", "ZYDUSLIFE"),
        ("INE010A01011", "PRISMCEM", "PRSMJOHNSN"),
        ("INE007B01023", "GEOJITBNPP", "GEOJITFSL"),
    ]:
        assert assign(old, isin) == assign(new, isin), f"{isin} split across strata"

    # And the failure mode is real, not hypothetical: without the ISIN these
    # three companies do land in different places.
    apart = sum(
        assign(old)[0] != assign(new)[0]
        for old, new in [
            ("CADILAHC", "ZYDUSLIFE"),
            ("PRISMCEM", "PRSMJOHNSN"),
            ("GEOJITBNPP", "GEOJITFSL"),
        ]
    )
    assert apart > 0, "symbol keying happens to agree here; pick a sharper example"


def test_assignment_is_deterministic_across_processes():
    # sha256, not hash() — Python salts str hashing per process, so a naive
    # implementation would repartition the universe on every run.
    assert bucket("INE010B01027") == bucket("INE010B01027")
    # Golden values, computed independently of this module:
    #   python -c "import hashlib; print(int(hashlib.sha256(b'INE010B01027')
    #              .hexdigest()[:8],16)%1000)"
    # Pinned so a future refactor of the hash cannot silently repartition the
    # universe — which would invalidate every result derived under the old one.
    assert bucket("INE010B01027") == 442
    assert bucket("INE010A01011") == 963
    assert bucket("INE007B01023") == 48


def test_case_and_whitespace_do_not_change_assignment():
    assert assign("  zyduslife ", " ine010b01027 ") == assign("ZYDUSLIFE", "INE010B01027")


# --- distribution ------------------------------------------------------------


def test_distribution_is_close_to_the_declared_fractions():
    from collections import Counter

    counts = Counter(assign(f"SYNTH{i:05d}")[0] for i in range(20_000))
    for name, s in spec()["strata"].items():
        got = counts[name] / 20_000
        assert abs(got - s["fraction"]) < 0.02, f"{name}: {got:.3f} vs {s['fraction']}"


# --- exclusions --------------------------------------------------------------


@pytest.mark.parametrize("sym", ["AARTI-RE", "3IINFO-RE"])
def test_rights_entitlements_are_excluded(sym):
    # 160 of these are in the seed. They trade for days and expire, so an event
    # on one has no forward return to measure.
    assert excluded(sym) is not None


def test_ordinary_equities_are_not_excluded():
    assert excluded("RELIANCE") is None
    assert excluded("ZYDUSLIFE") is None


# --- the honest sample size --------------------------------------------------


def test_correlation_destroys_effective_sample_size():
    # The number every MDE in this project currently ignores. 2,100 names at
    # rho=0.20 are worth about five independent observations.
    assert effective_sample_size(2100, 0.0) == pytest.approx(2100)
    assert effective_sample_size(2100, 0.20) < 6
    assert effective_sample_size(2100, 0.02) < 50


def test_effective_sample_size_is_monotone_in_correlation():
    prev = float("inf")
    for rho in (0.0, 0.01, 0.05, 0.10, 0.30):
        cur = effective_sample_size(1000, rho)
        assert cur < prev
        prev = cur


# --- enforcement -------------------------------------------------------------


def test_explore_needs_no_registration():
    ConfirmationGuard().check("EXPLORE", "poking around")  # must not raise


def test_confirm_without_registration_is_refused():
    with pytest.raises(SplitViolation, match="without a registered experiment"):
        ConfirmationGuard().check("CONFIRM", "sneaking a look")


def test_select_without_registration_is_refused():
    with pytest.raises(SplitViolation):
        ConfirmationGuard().check("SELECT", "comparing candidates")


def test_confirm_is_spent_once_and_then_refused():
    g = ConfirmationGuard(registered_experiment="exp_002_block_deals")
    g.check("CONFIRM", "the one registered test")
    with pytest.raises(SplitViolation, match="wearing a costume"):
        g.check("CONFIRM", "just one more look")


def test_accesses_are_logged():
    g = ConfirmationGuard(registered_experiment="exp_002_block_deals")
    g.check("EXPLORE", "a")
    g.check("CONFIRM", "b")
    assert [a.stratum for a in g.accesses] == ["EXPLORE", "CONFIRM"]
