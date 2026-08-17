#!/usr/bin/env python3
"""register_exp001.py — log the exploratory episode, then freeze exp_001's spec.

RUN THIS BEFORE THE TEST. That ordering is the entire point: once the spec is
REGISTERED a trigger refuses any change to the hypothesis, bars, test count, or
cost policy. If the registration ran after the holdout result were known, every
number downstream would be unfalsifiable.

The exploratory search on 2026-08-16 is logged first, with its test count, so
exp_001's bar accounts for the fact that we already went looking.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import sys  # noqa: E402

sys.path.insert(0, str(ROOT))

from src.common.hashing import spec_hash  # noqa: E402
from src.common.migrate import migrate_sqlite  # noqa: E402
from src.common.paths import governance_db  # noqa: E402

NOW = datetime.now(UTC).isoformat()
COMMIT = subprocess.run(
    ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True
).stdout.strip()

# The exploratory episode, counted honestly. Roughly 100 cells: 4 event sets
# (bulk/block x buy/sell) x 5 horizons x 4 liquidity tiers, plus random and
# volatility-matched controls, pre-event quintiles, and 4 era splits.
EXPLORATORY_TESTS = 100

# Expected portfolio-level magnitude, derived BEFORE the test so the bar is not
# fitted to the answer:
#   ~6,217 top500 buy events / 20.6 yr   = ~302 events/yr
#   effect vs vol-matched peers          = -0.805% over 10 sessions
#   names excluded at any time           = 302 * 10 / 250 = ~12 of 500 = 2.4%
#   annual book-level benefit            = 302 * 0.805% / 500 = ~0.49%/yr
# So a plausible true effect is ~0.5%/yr, and the bar must sit below the point
# where turnover costs consume it.
EXPECTED_ANNUAL_BENEFIT = 0.0049

SPEC = {
    "hypothesis": (
        "A long-only equal-weighted top-500 book that EXCLUDES names with a "
        "disclosed bulk-deal BUY in the trailing 10 trading sessions earns a "
        "higher net return than the identical unfiltered book. Direction: the "
        "filter helps, because such names underperform volatility-matched peers "
        "by ~0.805% over the following 10 sessions."
    ),
    "universe_definition": (
        "warehouse.pit_universe top500=1, point-in-time, delisting-aware, "
        "monthly rebalance"
    ),
    "holding_period": "10-session exclusion window; monthly rebalance",
    "entry_policy": "next-session OPEN after the disclosure is observable",
    "exit_policy": "name becomes eligible again 10 sessions after its last event",
    "cost_policy": (
        "configs/costs.yml verified schedule: STT 0.10% BOTH sides, NSE 0.00307%, "
        "GST on brokerage+SEBI+txn, 0.03% brokerage headline = 29.33bps round "
        "trip; plus tiered slippage. Charged on the INCREMENTAL turnover the "
        "filter causes, since that is the only cost the filter adds."
    ),
    "benchmark_policy": (
        "the identical unfiltered equal-weighted top500 book — a paired "
        "difference, so market and style exposure cancel"
    ),
    "pass_bar": (
        "net annualised return difference > +0.25%/yr AND the paired-difference "
        "block-bootstrap 95% CI excludes zero, in BOTH holdouts (stock-split and "
        "forward-only). +0.25% is half the ~0.49%/yr expected benefit, so the "
        "bar demands the effect be at least half as large as the event study "
        "implies once diluted to portfolio level."
    ),
    "kill_criteria": (
        "net annualised difference <= 0 in either holdout, OR MDE exceeds the "
        "0.49%/yr expected benefit (in which case the verdict is UNDERPOWERED, "
        "not FAIL — the study could not have seen it either way)."
    ),
}

EXPERIMENT = {
    "experiment_id": "exp_001_bulk_deal_avoidance_filter",
    "engine_id": None,
    "prior_belief": (
        "Weakly positive that the filter helps, and explicitly uncertain that it "
        "survives dilution. Three things temper the prior: (1) the effect was "
        "found in an unregistered search of ~100 cells, where t=-3.93 pooled sits "
        "near what noise produces at that scale; (2) it is absent in 2011-2015 "
        "(t=-0.54) and only t=-2.25 in 2021-2026; (3) at portfolio level it "
        "dilutes to ~0.49%/yr, which incremental turnover cost could consume "
        "entirely. The predecessor system's champion showed exactly this shape — "
        "full-sample Sharpe 1.52, trailing-24m 0.11."
    ),
    "data_version": "v1_export 2026-07-10 + spine to 2026-08-14",
    "participant_definition": (
        "directional bulk BUY: client-stock-days with buy quantity and zero sell "
        "quantity, i.e. same-day round-trippers already removed. PROP_HFT names "
        "(>=95% round-trip over >=20 client-stock-days) excluded per "
        "configs/participants.yml."
    ),
    "interpretation_mode": "INDIVIDUAL",
    "training_period": "2006-01-02 .. 2026-08-14 (fit half of names)",
    "validation_period": "stock-split holdout: the complementary half of names",
    "final_test_period": "forward-only: 2026-08-17 onward, genuinely unseen",
    "search_space_definition": (
        f"ONE specification, no free parameters. Preceded by an exploratory search "
        f"of ~{EXPLORATORY_TESTS} cells on 2026-08-16, logged in trial_counter and "
        f"disclosed in exploratory_prior_run."
    ),
    "test_count": 2,  # two holdouts, both must pass
    "multiple_testing_policy": (
        f"trials_before carries the cumulative counter including the "
        f"{EXPLORATORY_TESTS}-cell exploratory episode. Both holdouts must pass, "
        f"so no cherry-picking between them."
    ),
    "permutation_policy": (
        "paired-difference moving-block bootstrap, block length 10 sessions "
        "(the exclusion window), 10,000 draws, seed fixed at 0"
    ),
    "exploratory_prior_run": json.dumps(
        {
            "date": "2026-08-16",
            "approx_tests": EXPLORATORY_TESTS,
            "what_was_seen": {
                "pooled_10d_top500_vs_random": "-1.147%",
                "pooled_10d_top500_vs_vol_matched": "-0.805% (t -3.93)",
                "era_2011_2015_vs_vol_matched": "-0.220% (t -0.54)",
                "era_2016_2020_vs_vol_matched": "-1.296% (t -2.60)",
                "era_2021_2026_vs_vol_matched": "-0.894% (t -2.25)",
                "note": (
                    "2021-2026 has ALREADY BEEN EXAMINED and is therefore NOT a "
                    "clean holdout. This is why a stock-split and a forward-only "
                    "holdout are both required."
                ),
            },
            "confounds_tested": {
                "open_to_close_microstructure": (
                    "controlled — random stocks lose 0.236% at 1d, so 71% of the "
                    "1-day effect was microstructure, not signal"
                ),
                "volatility": (
                    "controlled — vol-matched peers lose 0.274%, leaving -0.805% "
                    "event-specific"
                ),
                "momentum_reversal": (
                    "rejected — corr(pre-event 21d, forward 10d) = +0.008, and the "
                    "pre-event quintile pattern is U-shaped, not monotonic"
                ),
            },
            "known_data_defect": (
                "the 2006-2010 era cell returned NaN, indicating at least one bad "
                "price. Those 2,925 events are excluded until the quality layer "
                "resolves it."
            ),
        }
    ),
    "configuration_json": json.dumps(
        {
            "exclusion_window_sessions": 10,
            "rebalance": "month_end",
            "weighting": "equal",
            "universe": "top500",
            "expected_annual_benefit": EXPECTED_ANNUAL_BENEFIT,
            "holdouts": ["stock_split", "forward_only"],
        }
    ),
    "status": "REGISTERED",
}


def main() -> int:
    db = governance_db()
    migrate_sqlite(db)
    con = sqlite3.connect(db)
    con.execute("PRAGMA foreign_keys = ON")

    # 1. Carry the predecessor's counter, once.
    if not con.execute("SELECT 1 FROM trial_counter LIMIT 1").fetchone():
        con.execute(
            "INSERT INTO trial_counter (source, description, recorded_at) VALUES (?,?,?)",
            (
                "MICCV2_carried",
                "Predecessor cumulative trial count carried forward: 47 factory "
                "trials + 21 v1 legacy = 68. Never reset. Applies to incumbents too.",
                NOW,
            ),
        )
        # Represent the carried 68 as a single accounted row plus an offset note,
        # rather than 68 fabricated rows.
        con.execute(
            "INSERT INTO trial_counter (source, description, recorded_at) VALUES (?,?,?)",
            ("MICCV2_offset", "offset=68", NOW),
        )

    # 2. The exploratory episode, counted honestly.
    already = con.execute(
        "SELECT 1 FROM trial_counter WHERE source='exploratory_2026_08_16'"
    ).fetchone()
    if not already:
        con.execute(
            "INSERT INTO trial_counter (source, description, recorded_at) VALUES (?,?,?)",
            (
                "exploratory_2026_08_16",
                f"Unregistered exploratory search, ~{EXPLORATORY_TESTS} cells: "
                "4 event sets x 5 horizons x 4 liquidity tiers, plus random and "
                "volatility-matched controls, pre-event quintiles and era splits. "
                "Logged so every later study's bar accounts for it.",
                NOW,
            ),
        )
    con.commit()

    offset = 68
    counted = con.execute("SELECT COUNT(*) FROM trial_counter").fetchone()[0]
    trials_before = offset + EXPLORATORY_TESTS + counted

    # 3. Freeze the spec.
    sh = spec_hash(SPEC)
    row = {**EXPERIMENT, **SPEC, "spec_hash": sh, "created_at": NOW,
           "created_by": "Markandeya Varma (owner) / Claude Opus 5",
           "code_commit_hash": COMMIT, "trials_before": trials_before}
    cols = ", ".join(row)
    con.execute(
        f"INSERT OR IGNORE INTO experiment_registry ({cols}) "
        f"VALUES ({', '.join('?' * len(row))})",
        tuple(row.values()),
    )
    con.commit()

    print(f"trial counter        : {trials_before} "
          f"(68 carried + {EXPLORATORY_TESTS} exploratory + {counted} logged)")
    print(f"experiment           : {EXPERIMENT['experiment_id']}")
    print(f"spec_hash            : {sh}")
    print(f"status               : {EXPERIMENT['status']}  <- spec now frozen")
    print(f"pass bar             : {SPEC['pass_bar'][:72]}...")
    print(f"expected benefit     : {EXPECTED_ANNUAL_BENEFIT*100:.2f}%/yr")

    # Prove the freeze is real rather than asserted.
    try:
        con.execute(
            "UPDATE experiment_registry SET pass_bar='anything' WHERE experiment_id=?",
            (EXPERIMENT["experiment_id"],),
        )
        print("\n!!! THE FREEZE DID NOT HOLD — the spec is editable")
        return 1
    except sqlite3.IntegrityError as exc:
        con.rollback()
        print(f"\nfreeze verified      : {exc}")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
