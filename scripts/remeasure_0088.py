"""Re-measure the registered verdicts on the corrected price spine (decision 0088, step 2).

Nothing here touches the registry. A registered result is write-once; this is
a NEW, documented measurement of the same committed analysis on corrected
inputs, run two ways:

  corrected    the spine after 0088's 226 confirmed corrections
  quarantined  the same, with every forward return whose window crosses a
               day in configs/price_suspect_days.csv set to NULL — for the
               event AND for its benchmark peers, so the comparison stays fair

    RESEARCH_ENV=prod .venv/bin/python scripts/remeasure_0088.py exp002
    RESEARCH_ENV=prod .venv/bin/python scripts/remeasure_0088.py grid
"""

from __future__ import annotations

import dataclasses
import json
import sys
import time
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.common.paths import CONFIGS, ROOT  # noqa: E402
from src.research import measure  # noqa: E402

SUSPECTS = CONFIGS / "price_suspect_days.csv"
OUT = ROOT / "data" / "derived" / "remeasure_0088"


def quarantined_returns_sql(spine: str, sessions: int, cutoff: str | None = None) -> str:
    """measure._returns_sql with one more NULL: a window (date, exit_date]
    that contains a quarantined day. Same entry, exit and span rule."""
    return f"""
    WITH {measure.identified_px_ctes(spine, cutoff)},
    sus AS (SELECT symbol, date FROM read_csv('{SUSPECTS}', header=true, all_varchar=true)),
    f AS (
        SELECT a.security_id, a.symbol, a.date,
               LEAD(a.open, 1) OVER w AS entry,
               LEAD(a.close, {sessions}) OVER w AS exit_px,
               LEAD(a.date, {sessions}) OVER w AS exit_date,
               median(a.close * a.volume) OVER (
                   PARTITION BY a.security_id ORDER BY a.date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW
               ) AS adv20
        FROM sec a WINDOW w AS (PARTITION BY a.security_id ORDER BY a.date)
    )
    SELECT security_id, symbol, date, adv20,
           CASE WHEN date_diff('day', CAST(date AS DATE), CAST(exit_date AS DATE))
                     <= {measure.max_span_days(sessions)}
                 AND NOT EXISTS (SELECT 1 FROM sus s WHERE s.symbol = f.symbol
                                 AND s.date > f.date AND s.date <= f.exit_date)
                THEN exit_px / entry - 1 END AS ret
    FROM f WHERE entry > 0
    """


@contextmanager
def quarantine():
    orig = measure._returns_sql
    measure._returns_sql = quarantined_returns_sql
    try:
        yield
    finally:
        measure._returns_sql = orig


def _verdict_summary(v) -> dict:
    passers = [s for s in v.entities if s.q_form is not None and s.q_form < 0.05]
    return {
        "alive": v.alive, "reason": v.reason, "passed_fdr": v.passed_fdr,
        "passers": [(s.entity, s.n_form, round(s.mean_excess_form or 0, 4)) for s in passers],
        "max_n_form_of_passers": max((s.n_form for s in passers), default=0),
        "rank_ic": None if v.rank_ic is None else round(v.rank_ic, 4),
        "tier_eval": {k: round(x, 5) for k, x in v.tier_eval.items()},
        "horizon_excess": {str(k): round(x, 5) for k, x in v.horizon_excess.items()},
        "entities": len(v.entities),
    }


def exp002() -> dict:
    from src.research import entity_verdict as E
    out = {}
    for name, ctx in (("corrected", None), ("quarantined", quarantine)):
        t0 = time.time()
        if ctx:
            with ctx():
                v = E.build()
        else:
            v = E.build()
        out[name] = _verdict_summary(v)
        out[name]["seconds"] = round(time.time() - t0)
        print(f"  exp_002 {name}: alive={v.alive} passed_fdr={v.passed_fdr} rank_ic={v.rank_ic}")
    return out


def grid() -> dict:
    out = {}
    for name, ctx in (("corrected", None), ("quarantined", quarantine)):
        rows = None
        if ctx:
            with ctx():
                rows = measure.grid()
        else:
            rows = measure.grid()
        out[name] = [{k: (round(v, 6) if isinstance(v, float) else v) for k, v in dataclasses.asdict(r).items()}
                     for r in rows]
        print(f"  grid {name}: {len(rows)} rows")
    return out


#: exp_004_holdings_change_v2's registered spec (0076). The analysis refuses
#: unless the row is REGISTERED; it is REJECTED, so the re-measure supplies the
#: recorded hash — read, never written — and charges nothing.
EXP004_SPEC = "2b5811c1b3549ba11ee60628bfc14e47f8d0c6c7aea425c2ad0b3c169f6c30e0"


def exp004(permutations: int = 1000) -> dict:
    from src.research import holdings as h
    h.registered_hash = lambda env=None: EXP004_SPEC
    t0 = time.time()
    _sh, results, extra = h.run(permutations=permutations)
    v = h.verdict(results, extra["robustness"], extra["panel"])
    out = {"primary": [{"signal": r.signal, "cohorts": r.n_cohorts, "names": r.n_names,
                        "spread": round(r.spread_mean, 5), "ci": [round(r.ci_low, 5), round(r.ci_high, 5)],
                        "t": round(r.t, 3), "p_perm": round(r.p_perm, 4), "q": round(r.q_fdr, 4),
                        "mde": round(r.mde, 5), "clears_bound": r.clears_bound} for r in results],
           "verdict": str(getattr(v, "landing", v)), "counts": extra["counts"],
           "seconds": round(time.time() - t0)}
    for r in out["primary"]:
        print(f"  exp_004 {r['signal']}: spread {r['spread']:+.4f} q {r['q']} MDE {r['mde']:.4f}")
    return out


def exp005(reps: int = 1000) -> dict:
    """exp_005's whole CONFIRM analysis (src/scan/confirm.evaluate, pure) on the
    corrected spine, over the SAME window the registered run read (to
    2026-10-01), in a FRESH atlas directory: the shard-reuse guard checks
    dates, ids and settings but not prices, and would otherwise reuse shards
    scored on the uncorrected spine. Writes a report; records nothing."""
    import subprocess
    from datetime import date

    import yaml

    from src.common.paths import DOCS, warehouse_dir
    from src.scan import atlas, confirm, folds, panel
    cfg = yaml.safe_load((CONFIGS / "scan.yml").read_text())
    h, depth = int(cfg["signals"]["primary_horizon_sessions"]), int(cfg["signals"]["max_depth"])
    top_n = [int(x) for x in cfg["procedure_test"]["top_n"]]
    commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    t0 = time.time()
    at = atlas.Atlas(panel.load(end=date(2026, 10, 1)),
                     warehouse_dir() / "scan" / f"confirm_h{h}_d{depth}_0088", horizon=h, depth=depth)
    print(f"  panel {len(at.p.dates):,} x {len(at.p.ids):,}; grid {at.total:,}", flush=True)
    at.run(commit)
    bic, keys = at.load()
    print(f"  atlas ready ({time.time() - t0:.0f} s)", flush=True)
    fs = folds.confirm(at.p.dates)
    o = confirm.evaluate(at, bic, keys, fs, top_n, reps=reps)
    note = ("**RE-MEASURE under decision 0088 (corrected price spine), same CONFIRM window "
            "as the registered run. Not the registered result; nothing recorded in the ledger.**")
    text = confirm.render(o, "SCAN_CONFIRM_H21_REMEASURE_0088.md — exp_005 on the corrected spine", note, fs)
    (DOCS / "reports" / "SCAN_CONFIRM_H21_REMEASURE_0088.md").write_text(text)
    out = {"verdict": o.verdict, "seconds": round(time.time() - t0),
           "primary": [{"top_n": r.top_n, "hit": round(r.hit_rate, 3), "p": round(r.p_vs_null, 4),
                        "test_ic": round(r.mean_test_ic, 4)} for r in o.primary],
           "primary_q": [round(x, 4) for x in o.primary_q],
           "partial": [{"top_n": r.top_n, "hit": round(r.hit_rate, 3), "p": round(r.p_vs_null, 4),
                        "test_ic": round(r.mean_test_ic, 4)} for r in o.partial],
           "partial_q": [round(x, 4) for x in o.partial_q]}
    print(f"  exp_005 verdict {o.verdict}", flush=True)
    return out


def main() -> int:
    what = sys.argv[1] if len(sys.argv) > 1 else "exp002"
    OUT.mkdir(parents=True, exist_ok=True)
    res = {"exp002": exp002, "grid": grid, "exp004": exp004, "exp005": exp005}[what]()
    (OUT / f"{what}.json").write_text(json.dumps(res, indent=1, default=str))
    print(f"  wrote {OUT / f'{what}.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
