"""Pre-register exp_004 — quarterly institutional holding change, cross-sectional.

REFUSES TO RUN UNTIL THE SWEEP IS COMPLETE. `data_version` names the panel the
study reads; a registration frozen at 19% coverage would have to be rewritten
when the other 81% lands, and a registered spec is not rewritten. The guard
below asks the manifest how many of the universe's companies hold their XBRL,
and refuses under COVERAGE_REQUIRED. The owner can override with --coverage
only by typing the number, so a partial registration is a deliberate act with
the number in the shell history.

Everything else in this file is the draft (docs/plan/EXP004_HOLDINGS_REGISTRATION_DRAFT.md)
made machine-readable. The tail rule, the three signals, the off-cycle rule
and the three tests are the owner's 2026-09-18 decisions. A plain INSERT: a
second registration of this id fails loudly.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.common.hashing import spec_hash  # noqa: E402
from src.common.paths import ARCHIVE, governance_db  # noqa: E402
from src.research import families  # noqa: E402
from src.research.holdings import (  # noqa: E402
    BOUND, CAP_PCT_ADV, CAP_SESSIONS, EXPERIMENT_ID, FAMILY, FDR_ALPHA, HORIZON,
    HORIZONS_REPORTED, INTERVAL_CAP_DAYS, MIN_NAMES_PER_COHORT, NOTIONAL_INR, SIGNALS,
)

COVERAGE_REQUIRED = 0.95


def sweep_coverage() -> tuple[int, int, int]:
    """(companies with XBRL held, companies with a non-empty master, universe)."""
    from src.archive.shp import universe
    man = ARCHIVE / "manifest.jsonl"
    masters, empties, xbrl = set(), set(), set()
    for line in man.read_text(errors="ignore").splitlines():
        if '"nse_shp' not in line:
            continue
        r = json.loads(line)
        s = r.get("symbol")
        if r.get("source_id") == "nse_shp_master" and s:
            (empties if r.get("status") == "EMPTY" else masters if r.get("status") in ("STORED", "DUPLICATE") else set()).add(s)
        elif r.get("source_id") == "nse_shp_xbrl" and r.get("status") == "STORED" and s:
            xbrl.add(s)
    u = set(universe())
    return len(xbrl & u), len((masters - empties) & u), len(u - empties)


def build_spec(coverage: tuple[int, int, int]) -> dict:
    held, indexed, universe_n = coverage
    return {
        "hypothesis":
            "The top decile of filing-over-filing change in a stock's institutional holding — "
            "FPI (Category I + II, undivided before 2025), all foreign institutions, and mutual "
            "funds, each a separate test — ranked within the calendar quarter of the filing's "
            "period-end, earns a higher 63-session CHAR_MATCHED abnormal return than the bottom "
            "decile, after Benjamini-Hochberg across the three tests.",
        "prior_belief":
            "Weak-to-moderate. The preliminary dispersion runs (HOLDINGS_POWER_PRELIMINARY.md, "
            "no signal read) put the unclipped MDE at 8.0x the bound on 8% of the universe "
            "(2026-09-18) and 6.2x on 16% (2026-09-19, 449 companies), winsorised 3.3x then 2.3x. "
            "It improves with the sweep and is not on a path to 1x; the tail rule below is what "
            "makes the study askable at all, and UNDERPOWERED remains the likeliest landing.",
        "data_version":
            f"shp_holdings.parquet from src/ingest/shp.py at registration: {held} of {universe_n} "
            f"non-empty companies hold XBRL ({held / universe_n:.1%}); {indexed} indexed. "
            "price_spine_adj and char_panel as of the registration commit. Identity by ISIN (0069).",
        "universe_definition":
            "Every ISIN with (a) a filing and a prior filing within INTERVAL_CAP_DAYS, (b) a spine "
            "session after broadcast_date and 63 sessions after entry, (c) a CHAR_MATCHED cell at "
            "entry, (d) identity_total within 1pt of 100, (e) TRADEABLE under the tail rule. Off-cycle "
            "and revised filings are KEPT (see the two policies). Exclusion counts reported per reason.",
        "tail_rule":
            f"A name is in the primary universe only if CAP_SESSIONS x CAP_PCT_ADV x ADV20 >= its "
            f"equal-weight share of one side of a Rs {NOTIONAL_INR / 1e7:.0f} crore long-short book "
            f"({CAP_SESSIONS} sessions x {CAP_PCT_ADV:.0%} of 20-day median rupee volume) — the "
            "pessimistic participation level of costs.yml, applied per cohort. Chosen 2026-09-18 "
            "before any signal was ranked. Winsorisation at 1st/99th is REPORTED as robustness.",
        "signal_definition":
            "Delta pct_shares (percent of shares outstanding, scale-normalised per file) since the "
            "previous filing. FPI = FPI_Cat1 + FPI_Cat2 + FPI_Undivided (three taxonomies, never "
            "co-occurring). FOREIGN = ForeignInst_Total (new taxonomy only; NULL before). MF = "
            "MutualFund. A category absent from a filing is ZERO within that filing's taxonomy. "
            "Robustness (reported, not tested): delta num_shareholders under the same members.",
        "interpretation_mode": "CROSS_SECTIONAL",
        "holding_period":
            f"primary {HORIZON} sessions; {', '.join(str(h) for h in HORIZONS_REPORTED)} reported. "
            "A quarterly signal at 252 sessions overlaps three cohorts of four; declared as the "
            "departure from research.yml's 12-month primary, as 0067 declared 21.",
        "entry_policy": "OPEN of the first session strictly after broadcast_date, per name. Never the period-end.",
        "exit_policy": "close of entry + h sessions; 0052 delisting policy; no same-day close.",
        "cost_policy":
            "Portfolio gate: long top decile / short bottom, equal weight within side, rebalanced per "
            "cohort, full costs.yml stack at the pessimistic level.",
        "benchmark_policy":
            "CHAR_MATCHED primary (size/momentum/volatility cell at entry, self-excluded, "
            "min_names_per_cell from benchmarks.yml, degradation ladder SIZE_MOM_VOL -> SIZE_MOM -> "
            "SIZE — outcomes.py's construction, mirrored in holdings.py). Market-relative reported "
            "alongside, against the NIFTY 500 TOTAL RETURN index (collected:index_tri, "
            "benchmarks.yml's headline_index, decision 0077) — not a price index: the ~0.3%/quarter "
            "dividend leg is a fifth of this study's own bound. Swapping the primary re-registers.",
        "training_period": "none — within-cohort decile ranks have no fitted parameter",
        "validation_period": "none",
        "final_test_period": "every cohort whose 63-session horizon has matured at the run; touched once",
        "search_space_definition":
            f"ONE specification, no free parameters. Deciles within cohort; cohorts with fewer than "
            f"{MIN_NAMES_PER_COHORT} names dropped. Estimator = mean over cohorts of (top - bottom) "
            "CHAR_MATCHED abnormal return at 63 sessions, Bartlett serial correction (power.py).",
        "test_count": len(SIGNALS),
        "multiple_testing_policy":
            f"Benjamini-Hochberg FDR {FDR_ALPHA:.0%} across the {len(SIGNALS)} tests, declared here. "
            "Robustness horizons, the count signal, the calendar-only and winsorised variants "
            "reported, never tested.",
        "permutation_policy":
            "Within-cohort label permutation, 1,000 draws, seed 20260918 — the signal is shuffled among "
            "the names of each cohort so composition and outcome dispersion are kept and only the "
            "ranking is destroyed. Moving-block bootstrap over cohorts (block 2) for the CI.",
        "pass_bar":
            f"Event gate: |spread| at 63 sessions clears the serial-corrected MDE AND the plausible "
            f"bound ({BOUND:.1%} per quarter = 0.5%/month x 3, decision 0028) at BH-FDR {FDR_ALPHA:.0%}; "
            "AND portfolio gate (0003): the long-short beats CHAR_MATCHED net of costs. Both.",
        "kill_criteria":
            "(1) MDE > bound -> UNDERPOWERED, reported, no fitting. (2) Spread present in the "
            "untradeable names and absent in the tradeable -> liquidity, not information. (3) Spread "
            "present in raw returns and absent under CHAR_MATCHED -> momentum, not institutions. "
            "(4) Spread driven by rows with an abnormal identity_total or share-count change -> "
            "corporate action, not holding.",
        "confounds":
            "momentum APPLICABLE (CHAR_MATCHED; kill 3); share count APPLICABLE (identity_total; "
            "kill 4); index inclusion APPLICABLE, NOT CONTROLLED — constituents archived daily "
            "from 2026-09-18 only, stated limitation; delisting APPLICABLE (0052); liquidity "
            "APPLICABLE (tail rule; kill 2); industry NOT CONTROLLED (sector_history is Phase 3).",
        "revised_policy":
            "KEEP revised filings (owner decision 2026-09-18, option a). NSE's master replaces the "
            "original with the revision and keeps no copy; the revision is the only version that "
            "exists, and its broadcast_date — the day the corrected figures became public — is the "
            "point-in-time entry. The `revised` flag rides on every row and is reported by cohort.",
        "interval_policy":
            f"CAP the change at {INTERVAL_CAP_DAYS} days between filings (owner decision 2026-09-18, "
            "option a). A change spanning longer is a resumption after a filing gap, not a quarterly "
            "signal; excluded from the primary and counted. Off-cycle filings inside the cap are kept.",
        "trial_family": FAMILY,
        "exploratory_prior_run": json.dumps({
            "note": "docs/reports/HOLDINGS_POWER_PRELIMINARY.md: dispersion of the outcome under "
                    "RANDOM deciles, no signal column read (tests parse the SQL). Run twice as the "
                    "sweep brought companies in; the report holds the later one. Nothing charged.",
            "runs": [
                {"date": "2026-09-18", "companies": 220, "stock_quarters": 3092, "quarters": 18,
                 "market_leg": "seed NIFTY 50 price index, ends 2026-07-07",
                 "mde": 0.1205, "mde_winsor": 0.0489},
                {"date": "2026-09-19", "companies": 449, "stock_quarters": 6749, "quarters": 19,
                 "market_leg": "NIFTY 500 total return, collected:index_tri (0077)",
                 "mde": 0.0936, "mde_winsor": 0.0339},
            ],
        }),
    }


def main() -> int:
    import argparse
    import sqlite3

    ap = argparse.ArgumentParser()
    ap.add_argument("--coverage", type=float, default=None,
                    help="override COVERAGE_REQUIRED; a partial registration is deliberate only when typed")
    args = ap.parse_args()
    need = COVERAGE_REQUIRED if args.coverage is None else args.coverage

    cov = sweep_coverage()
    held, indexed, universe_n = cov
    frac = held / universe_n if universe_n else 0.0
    print(f"  sweep: {held}/{universe_n} companies hold XBRL ({frac:.1%}); {indexed} indexed")
    if frac < need:
        print(f"  REFUSED: coverage {frac:.1%} < {need:.0%}. A spec frozen on a partial panel is a spec "
              f"rewritten later. Wait for the sweep, or pass --coverage {frac:.2f} to register on purpose.")
        return 1

    spec = build_spec(cov)
    for k in ("revised_policy", "interval_policy"):
        if spec[k].startswith("TO BE SET"):
            print(f"  REFUSED: {k} is unset in the draft. The owner decides it before the hash exists.")
            return 1

    sh = spec_hash(spec)
    trials_before = families.persisted_counter(FAMILY)
    row = {"experiment_id": EXPERIMENT_ID, "engine_id": "ENGINE_H_HOLDINGS", "status": "REGISTERED",
           "decision_reason": None, **spec, "spec_hash": sh,
           "created_at": datetime.now(UTC).isoformat(),
           "created_by": "Markandeya Varma (owner) / Claude Opus 5",
           "configuration_json": json.dumps({
               "primary_horizon_sessions": HORIZON, "horizons_sessions": list(HORIZONS_REPORTED),
               "signals": {k: list(v) for k, v in SIGNALS.items()}, "fdr_alpha": FDR_ALPHA,
               "notional_inr": NOTIONAL_INR, "cap_sessions": CAP_SESSIONS, "cap_pct_adv": CAP_PCT_ADV,
               "interval_cap_days": INTERVAL_CAP_DAYS,
               "family": FAMILY, "decision": "0076", "coverage_at_registration": frac}),
           "code_commit_hash": subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip(),
           "trials_before": trials_before}
    con = sqlite3.connect(str(governance_db(None)))
    try:
        cols = [r[1] for r in con.execute("PRAGMA table_info(experiment_registry)")]
        use = {k: v for k, v in row.items() if k in cols}
        if con.execute("SELECT 1 FROM experiment_registry WHERE experiment_id = ?", (EXPERIMENT_ID,)).fetchone():
            print(f"  REFUSED: {EXPERIMENT_ID} is already registered; a registered spec is not rewritten.")
            return 1
        con.execute(f"INSERT INTO experiment_registry ({','.join(use)}) VALUES ({','.join('?' * len(use))})",
                    list(use.values()))
        con.commit()
    finally:
        con.close()
    print(f"  experiment_id  : {EXPERIMENT_ID}\n  spec_hash      : {sh}\n  family         : {FAMILY}  trials_before={trials_before}")
    print(f"  test_count     : {spec['test_count']}  (declared)\n  status         : REGISTERED — no result computed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
