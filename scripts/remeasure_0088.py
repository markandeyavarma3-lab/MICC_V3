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


def main() -> int:
    what = sys.argv[1] if len(sys.argv) > 1 else "exp002"
    OUT.mkdir(parents=True, exist_ok=True)
    res = {"exp002": exp002, "grid": grid}[what]()
    (OUT / f"{what}.json").write_text(json.dumps(res, indent=1, default=str))
    print(f"  wrote {OUT / f'{what}.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
