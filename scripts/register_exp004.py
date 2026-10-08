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
    BOUND,
    CAP_PCT_ADV,
    CAP_SESSIONS,
    EXPERIMENT_ID,
    FAMILY,
    FDR_ALPHA,
    HORIZON,
    HORIZONS_REPORTED,
    INTERVAL_CAP_DAYS,
    MIN_NAMES_PER_COHORT,
    NOTIONAL_INR,
    SHARE_CHANGE_FLAG,
    SIGNALS,
)

COVERAGE_REQUIRED = 0.95


def sweep_coverage() -> tuple[int, int, int]:
    """(companies with XBRL held, companies with a non-empty master, universe)."""
    from src.archive.shp import universe
    # A COMPANY'S LATEST MASTER DECIDES WHETHER IT IS EMPTY (2026-10-08). This
    # took any EMPTY ever seen, so ten new listings — empty when first asked,
    # filing since — left the denominator but stayed in the numerator, and the
    # final sweep read "2300/2290 companies hold XBRL (100.4%)". The manifest
    # is append-only in fetch order, so the last master row is the latest.
    man = ARCHIVE / "manifest.jsonl"
    latest: dict[str, str] = {}
    xbrl: set[str] = set()
    for line in man.read_text(errors="ignore").splitlines():
        if '"nse_shp' not in line:
            continue
        r = json.loads(line)
        s = r.get("symbol")
        if r.get("source_id") == "nse_shp_master" and s and r.get("status") in ("STORED", "DUPLICATE", "EMPTY"):
            latest[s] = r["status"]
        elif r.get("source_id") == "nse_shp_xbrl" and r.get("status") == "STORED" and s:
            xbrl.add(s)
    empties = {s for s, st in latest.items() if st == "EMPTY"}
    masters = set(latest) - empties
    u = set(universe())
    # Both sides over the same set, so the fraction cannot pass 1.
    base = u - empties
    return len(xbrl & base), len(masters & base), len(base)


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
            "(2026-09-18), 6.2x on 16% (2026-09-19, 449 companies) and 6.8x on 40% (2026-09-28, "
            "1,147 companies); winsorised 3.3x, 2.3x, 3.5x. Those runs admitted quarters of 20 names; "
            "the 2018-2021-Q2 quarters (13-40 early filers) set the MDE. At the registered floor of 100 "
            "names a quarter (2026-09-29, 1,309 companies, 19 quarters from 2021-Q3) it is 2.6x, "
            "winsorised 1.3x. The tail rule below is what makes the study askable at all, and "
            "UNDERPOWERED remains the likeliest landing.",
        "data_version":
            f"shp_holdings.parquet from src/ingest/shp.py at registration: {held} of {universe_n} "
            f"non-empty companies hold XBRL ({held / universe_n:.1%}); {indexed} indexed. "
            "price_spine_adj and char_panel as of the registration commit. Identity by ISIN (0069).",
        "universe_definition":
            "Every ISIN with (a) a filing and a prior filing within INTERVAL_CAP_DAYS, (b) an EQ spine "
            "session after broadcast_date (the entry), (c) a CHAR_MATCHED cell at entry, (d) "
            "identity_total within 1pt of 100, (e) TRADEABLE under the tail rule. A name need NOT "
            "survive the window: see exit_policy (owner decision 2026-10-02 — requiring 63 sessions "
            "after entry would drop every name that stopped or left EQ, 111 of 26,443 filing pairs). "
            "Off-cycle and revised filings are KEPT (see the two policies). Exclusion counts reported "
            "per reason: no security for the ISIN, no EQ session after broadcast, window still open "
            "(CENSORED), no CHAR_MATCHED cell, untradeable, cohort under the name floor.",
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
        "exit_policy":
            "close of the name's own h-th EQ session after entry (HORIZON). A name that left EQ "
            "before it: if still trading at the calendar exit date — under the same symbol as a new "
            "ISIN, or in another series such as BE/BZ (0082) — its last close on or before that date, "
            "against the adjusted entry for EQ and the RAW entry for another series (MOVED). If it "
            "traded nowhere on or after the exit date, 0052: last close x recovery factor 0.0 "
            "headline, 0.25 and 0.50 reported (STOPPED). A window running past the data is CENSORED: "
            "excluded and counted. The market leg spans the calendar window. No same-day close.",
        "cost_policy":
            "Portfolio gate: long top decile / short bottom, equal weight within side, rebalanced per "
            "cohort, full costs.yml stack at the pessimistic level.",
        "benchmark_policy":
            "CHAR_MATCHED primary (size/momentum/volatility cell at entry, self-excluded, "
            "min_names_per_cell from benchmarks.yml, degradation ladder SIZE_MOM_VOL -> SIZE_MOM -> "
            "SIZE — ONE definition in src/research/charmatch.py, consumed by outcomes.py and "
            "holdings.py alike; the peer pool is this study's own, over its fixed 63-session "
            "horizon). Market-relative reported "
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
            "Reported, never tested (200 permutations, no family charge): horizons "
            f"{', '.join(str(x) for x in HORIZONS_REPORTED if x != HORIZON)}; the holder-count signal; "
            "calendar filings only; winsorised 1st/99th; market-relative against the NIFTY 500 TR; "
            "stopped names at recovery factors 0.25 and 0.50; raw returns, untradeable names and "
            "rows without share-count changes (kill criteria 3, 2 and 4).",
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
            "corporate action, not holding: shares outstanding changed by more than "
            f"{SHARE_CHANGE_FLAG:.0%} between the two filings, and the spread falls below half the "
            "bound without those rows.",
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
                    "RANDOM deciles, no signal column read (tests parse the SQL). Run as the sweep "
                    "brought companies in; the report holds the latest. The first three used a floor "
                    "of 20 names a quarter; the fourth the registered 100. Nothing charged.",
            "runs": [
                {"date": "2026-09-18", "companies": 220, "stock_quarters": 3092, "quarters": 18,
                 "market_leg": "seed NIFTY 50 price index, ends 2026-07-07",
                 "mde": 0.1205, "mde_winsor": 0.0489},
                {"date": "2026-09-19", "companies": 449, "stock_quarters": 6749, "quarters": 19,
                 "market_leg": "NIFTY 500 total return, collected:index_tri (0077)",
                 "mde": 0.0936, "mde_winsor": 0.0339},
                {"date": "2026-09-28", "companies": 1147, "stock_quarters": 17451, "quarters": 21,
                 "market_leg": "NIFTY 500 total return, collected:index_tri (0077)",
                 "mde": 0.1014, "mde_winsor": 0.0520},
                {"date": "2026-09-29", "companies": 1309, "stock_quarters": 20013, "quarters": 19,
                 "market_leg": "NIFTY 500 total return, collected:index_tri (0077)",
                 "min_names_per_quarter": 100,
                 "mde": 0.0389, "mde_winsor": 0.0195},
            ],
        }),
    }


#: Spec fields the registry has no column for. They are hashed with the rest
#: and stored in configuration_json under this key, so the stored row
#: reproduces the hash. FOUND BY THE REHEARSAL 2026-10-02: the first version
#: kept only the fields with a column — tail_rule, signal_definition,
#: confounds, revised_policy, interval_policy and trial_family were hashed and
#: then silently dropped, so the registry would have held a hash nobody could
#: recompute and none of the rules the study turns on.
EXTRA_KEY = "spec_fields_without_a_column"


def stored_spec(row: dict, spec_keys: list[str]) -> dict:
    """The spec as the registry row holds it: columns, plus the extras."""
    extra = json.loads(row["configuration_json"] or "{}").get(EXTRA_KEY, {})
    return {k: (extra[k] if k in extra else row[k]) for k in spec_keys}


def register(con, spec: dict, coverage_frac: float, commit: str) -> str:
    """INSERT the registration, read it back, recompute the hash from what was
    stored, and COMMIT only if it matches. Returns the spec hash."""
    sh = spec_hash(spec)
    cols = [r[1] for r in con.execute("PRAGMA table_info(experiment_registry)")]
    extras = {k: v for k, v in spec.items() if k not in cols}
    config = {
        "primary_horizon_sessions": HORIZON, "horizons_sessions": list(HORIZONS_REPORTED),
        "signals": {k: list(v) for k, v in SIGNALS.items()}, "fdr_alpha": FDR_ALPHA,
        "notional_inr": NOTIONAL_INR, "cap_sessions": CAP_SESSIONS, "cap_pct_adv": CAP_PCT_ADV,
        "interval_cap_days": INTERVAL_CAP_DAYS, "share_change_flag": SHARE_CHANGE_FLAG,
        "family": FAMILY, "decision": "0076", "coverage_at_registration": coverage_frac,
        EXTRA_KEY: extras}
    row = {"experiment_id": EXPERIMENT_ID, "engine_id": "ENGINE_H_HOLDINGS", "status": "REGISTERED",
           "decision_reason": None, **{k: v for k, v in spec.items() if k in cols}, "spec_hash": sh,
           "created_at": datetime.now(UTC).isoformat(),
           "created_by": "Markandeya Varma (owner) / Claude Opus 5.5",
           "configuration_json": json.dumps(config, sort_keys=True),
           "code_commit_hash": commit,
           "trials_before": families.persisted_counter(FAMILY)}
    if con.execute("SELECT 1 FROM experiment_registry WHERE experiment_id = ?", (EXPERIMENT_ID,)).fetchone():
        raise RuntimeError(f"{EXPERIMENT_ID} is already registered; a registered spec is not rewritten.")
    use = {k: v for k, v in row.items() if k in cols}
    con.execute(f"INSERT INTO experiment_registry ({','.join(use)}) VALUES ({','.join('?' * len(use))})",
                list(use.values()))
    back = dict(zip(cols, con.execute("SELECT * FROM experiment_registry WHERE experiment_id = ?",
                                      (EXPERIMENT_ID,)).fetchone(), strict=True))
    again = spec_hash(stored_spec(back, list(spec)))
    if again != sh or back["spec_hash"] != sh:
        con.rollback()
        raise RuntimeError(f"the stored row does not reproduce the hash ({again[:12]} != {sh[:12]}); "
                           "nothing was committed")
    con.commit()
    return sh


def input_problems() -> list[str]:
    """Every input the spec names, opened and counted — never joined. A study
    that cannot read one of these on the day it runs is a registration that
    has to be withdrawn, and a withdrawal is not free."""
    import duckdb

    from src.common.paths import COLLECTED, research_db, warehouse_dir
    checks = {
        "shp_holdings": f"SELECT COUNT(*) FROM read_parquet('{COLLECTED / 'shp' / 'shp_holdings.parquet'}')",
        "price_spine_adj": f"SELECT COUNT(*) FROM read_parquet('{warehouse_dir() / 'price_spine_adj' / '**' / '*.parquet'}')",
        "price_spine (raw, for MOVED exits)": f"SELECT COUNT(*) FROM read_parquet('{warehouse_dir() / 'price_spine' / '**' / '*.parquet'}')",
        "char_panel": f"SELECT COUNT(*) FROM read_parquet('{warehouse_dir() / 'char_panel' / '**' / '*.parquet'}')",
        "index_tri (NIFTY500)": f"SELECT COUNT(*) FROM read_parquet('{COLLECTED / 'index_tri' / 'index_tri.parquet'}') WHERE index_key = 'NIFTY500'",
        "listing history (MOVED exits)": f"SELECT COUNT(*) FROM read_parquet('{COLLECTED / 'listing' / 'series_presence.parquet'}')",
    }
    out = []
    con = duckdb.connect()
    for name, sql in checks.items():
        try:
            n = con.execute(sql).fetchone()[0]
            print(f"    input  {name:<36} {n:>12,} rows")
            if not n:
                out.append(f"{name}: empty")
        except Exception as e:  # noqa: BLE001 — every failure is a finding here
            out.append(f"{name}: {type(e).__name__}: {str(e)[:80]}")
    con.close()
    db = duckdb.connect(str(research_db()), read_only=True)
    try:
        n = db.execute("SELECT COUNT(*) FROM security_master WHERE isin IS NOT NULL").fetchone()[0]
        print(f"    input  {'security_master':<36} {n:>12,} rows")
    except Exception as e:  # noqa: BLE001
        out.append(f"security_master: {type(e).__name__}")
    finally:
        db.close()
    return out


def code_is_committed() -> list[str]:
    """Tracked code or config with uncommitted changes. code_commit_hash names
    HEAD, so a registration made from a dirty tree names code that is not the
    code that will run."""
    out = subprocess.run(["git", "status", "--porcelain", "--", "src", "scripts", "configs", "migrations"],
                         capture_output=True, text=True).stdout
    return [ln for ln in out.splitlines() if ln.strip()]


def main() -> int:
    import argparse
    import shutil
    import sqlite3
    import tempfile

    ap = argparse.ArgumentParser()
    ap.add_argument("--coverage", type=float, default=None,
                    help="override COVERAGE_REQUIRED; a partial registration is deliberate only when typed")
    ap.add_argument("--rehearse", action="store_true",
                    help="register into a throwaway COPY of the governance db, verify, and delete it; "
                         "the real registry is never opened for writing")
    args = ap.parse_args()
    need = COVERAGE_REQUIRED if args.coverage is None else args.coverage

    cov = sweep_coverage()
    held, indexed, universe_n = cov
    frac = held / universe_n if universe_n else 0.0
    print(f"  sweep: {held}/{universe_n} companies hold XBRL ({frac:.1%}); {indexed} indexed")
    if frac < need and not args.rehearse:
        print(f"  REFUSED: coverage {frac:.1%} < {need:.0%}. A spec frozen on a partial panel is a spec "
              f"rewritten later. Wait for the sweep, or pass --coverage {frac:.2f} to register on purpose.")
        return 1
    dirty = code_is_committed()
    if dirty and not args.rehearse:
        print("  REFUSED: uncommitted code or config — code_commit_hash would name other code:")
        print("\n".join(f"    {d}" for d in dirty))
        return 1

    problems = input_problems()
    if problems:
        print("  REFUSED: an input the spec names cannot be read:")
        print("\n".join(f"    {p}" for p in problems))
        return 1

    spec = build_spec(cov)
    for k in ("revised_policy", "interval_policy"):
        if spec[k].startswith("TO BE SET"):
            print(f"  REFUSED: {k} is unset in the draft. The owner decides it before the hash exists.")
            return 1
    commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()

    real = governance_db(None)
    if args.rehearse:
        tmp = Path(tempfile.mkdtemp(prefix="exp004_rehearsal_"))
        target = tmp / real.name
        shutil.copy2(real, target)
        print(f"  REHEARSAL on a copy: {target}")
        if frac < need:
            print(f"  (coverage {frac:.1%} < {need:.0%} — the real run would refuse here)")
        if dirty:
            print(f"  ({len(dirty)} uncommitted code/config path(s) — the real run would refuse here)")
    else:
        target = real
    con = sqlite3.connect(str(target))
    try:
        sh = register(con, spec, frac, commit)
    except RuntimeError as e:
        print(f"  REFUSED: {e}")
        return 1
    finally:
        con.close()
        if args.rehearse:
            shutil.rmtree(target.parent, ignore_errors=True)
    print(f"  experiment_id  : {EXPERIMENT_ID}\n  spec_hash      : {sh}\n  family         : {FAMILY}")
    print(f"  test_count     : {spec['test_count']}  (declared)")
    print(f"  stored fields  : {len(spec)} of {len(spec)} — the stored row reproduces the hash")
    print("  status         : " + ("REHEARSED — nothing registered, the copy is deleted" if args.rehearse
                                   else "REGISTERED — no result computed"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
