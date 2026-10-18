"""The one read of exp_007 (registered 2026-10-18, decision 0091, spec ddddb17f).

Guards, all before any mean is computed:
  - exp_007 is REGISTERED with the spec hash the owner approved;
  - the event list re-derived now hashes to the spec's event_set_sha256;
  - no study_result row exists for it (the read happens once).
Then: the primary statistic (63 sessions, CHAR_MATCHED, resignation_study.decide),
every reported-only figure the spec lists, one study_result row, the family's
one trial charged, and the registry status advanced with the reason.

    RESEARCH_ENV=prod .venv/bin/python scripts/read_exp007.py           # guards only
    RESEARCH_ENV=prod .venv/bin/python scripts/read_exp007.py --read    # the read
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.common.paths import DOCS, governance_db  # noqa: E402
from src.governance import registration as reg  # noqa: E402
from src.research import costs, families, power  # noqa: E402
from src.research import resignation_study as S  # noqa: E402

SPEC_HASH = "ddddb17fa518b4a545e417f399db1c56dfe3f549a39f13ae1211f3768c146ebf"
REPORT = DOCS / "reports" / "EXP007_RESULT.md"
SEBI_CIRCULAR = "2019-10-18"
# study_result.verdict admits PASS / FAIL / UNDERPOWERED; the study's own verdict rides in input_hashes.
TABLE_VERDICT = {"DRIFT_CONFIRMED": "PASS", "SIGNIFICANT_BUT_SMALL": "FAIL", "NO_DRIFT": "FAIL",
                 "UNDERPOWERED": "UNDERPOWERED"}


def guards(con: sqlite3.Connection) -> tuple[dict, list]:
    row = con.execute("SELECT status, spec_hash, configuration_json FROM experiment_registry WHERE experiment_id = ?",
                      (S.EXPERIMENT_ID,)).fetchone()
    if not row:
        raise SystemExit(f"  REFUSED: {S.EXPERIMENT_ID} is not registered")
    status, sh, cfg = row
    if status != "REGISTERED" or sh != SPEC_HASH:
        raise SystemExit(f"  REFUSED: status {status}, spec {sh[:12]} — expected REGISTERED, {SPEC_HASH[:12]}")
    if con.execute("SELECT 1 FROM study_result WHERE experiment_id = ?", (S.EXPERIMENT_ID,)).fetchone():
        raise SystemExit("  REFUSED: a result is already recorded; the read happens once")
    spec_extra = json.loads(cfg)[reg.EXTRA_KEY]
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import register_exp007 as R
    evs = R.frozen_events()
    got = hashlib.sha256(json.dumps([[e.date, e.isin, e.role] for e in evs], separators=(",", ":")).encode()).hexdigest()
    if got != spec_extra["event_set_sha256"]:
        raise SystemExit(f"  REFUSED: the events re-derived now hash to {got[:12]}, the spec froze "
                         f"{spec_extra['event_set_sha256'][:12]}")
    return spec_extra, evs


def summary(df, col: str, months: float) -> dict:
    x = df.dropna(subset=[col])
    coh = power.cohort_collapse(x["tdate"], x[col], freq="M")
    if len(coh) < 3:
        return {"events": len(x), "cohorts": len(coh)}
    infl, _ = power.serial_inflation(coh, label_periods=max(1, round(months)))
    t = float(coh.mean()) / (float(coh.std(ddof=1)) / len(coh) ** 0.5 * infl ** 0.5)
    return {"events": len(x), "cohorts": len(coh), "mean": float(coh.mean()), "t": t}


def _pct(x) -> str:
    return "—" if x is None else f"{x:+.2%}"


def _num(x) -> str:
    return "—" if x is None else f"{x:+.2f}"


def reported_figures(df63, df21, res: dict) -> dict:
    out: dict = {"primary_benchmark_rungs":
                 df63["level_CHAR_MATCHED"].value_counts(normalize=True).round(3).to_dict()}
    for b in S.BENCHES:
        out[f"63s {b}"] = summary(df63, f"ab_{b}", 3.0)
        out[f"21s {b}"] = summary(df21, f"ab_{b}", 1.0)
    for role, g in df63.groupby("role"):
        out[f"63s CHAR_MATCHED {role}"] = summary(g, "ab_CHAR_MATCHED", 3.0)
    cut = pd.Timestamp(SEBI_CIRCULAR)
    out["63s CHAR_MATCHED before the SEBI auditor circular"] = summary(df63[df63["tdate"] < cut], "ab_CHAR_MATCHED", 3.0)
    out["63s CHAR_MATCHED after the SEBI auditor circular"] = summary(df63[df63["tdate"] >= cut], "ab_CHAR_MATCHED", 3.0)
    rt = sorted(costs.round_trip_bps(1e6, d.date(), "NSE") for d in df63["tdate"].dropna())
    med = rt[len(rt) // 2] / 1e4 if rt else None
    mean = res.get("mean_cohort")
    out["short_book"] = {"median_cost": med,
                         "short_net": (-mean - med) if mean is not None and med is not None else None}
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--read", action="store_true")
    a = ap.parse_args()
    con = sqlite3.connect(str(governance_db(None)))
    try:
        spec, evs = guards(con)
        print(f"  guards passed: REGISTERED, spec {SPEC_HASH[:12]}, {len(evs):,} events hash to the frozen list")
        if not a.read:
            print("  GUARDS ONLY: nothing read. --read for the one read.")
            return 0
        df63 = S.abnormal(None, evs, S.PRIMARY_SESSIONS)
        df21 = S.abnormal(None, evs, 21)
        for d in (df63, df21):
            d["tdate"] = pd.to_datetime(d["tdate"])
        res = S.decide(df63["tdate"], df63["ab_CHAR_MATCHED"])
        verdict = res["verdict"]
        # The trial happened the moment the mean was computed: charge it before anything else.
        families.commit_charge(S.FAMILY, trials_added=1, experiment_id=S.EXPERIMENT_ID,
                               description=f"exp_007 primary: 1 test (governance resignations, 63s, CHAR_MATCHED); {verdict}")
        reported = reported_figures(df63, df21, res)
        commit = reg.head()
        now = datetime.now(UTC).isoformat()
        status = "VALIDATED" if verdict == "DRIFT_CONFIRMED" else "REJECTED"
        mean, t = res.get("mean_cohort"), res.get("t")
        n_events = int(df63["ab_CHAR_MATCHED"].notna().sum())
        raw_p = None if t is None else 0.5 * math.erfc(-t / math.sqrt(2))  # one-sided, lower tail
        reason = (f"{verdict} (read {now[:10]}, spec {SPEC_HASH[:8]}): mean monthly-cohort CHAR_MATCHED abnormal "
                  f"return over 63 sessions {_pct(mean)}, t {_num(t)} (bar t <= {S.T_BAR}, mean <= "
                  f"{S.EFFECT_FLOOR:.2%}), {res.get('cohorts')} cohorts, {res.get('events')} events. "
                  "docs/reports/EXP007_RESULT.md")
        with con:  # the result row and the status advance land together or not at all
            con.execute("""INSERT INTO study_result (experiment_id, stratum, stratum_type, horizon_months, benchmark_id,
                n_events, n_independent, mean_return, median_return, hit_rate, raw_p_value, corrected_p_value,
                correction_method, n_tests_in_family, bootstrap_ci_low, bootstrap_ci_high, verdict, input_hashes,
                code_commit, computed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (S.EXPERIMENT_ID, "GOVERNANCE (pooled)", "primary", 3, "CHAR_MATCHED", n_events,
                 res.get("cohorts"), mean, None, None, raw_p, raw_p,
                 "single test; one-sided t with Bartlett serial inflation (0033)", 1, None, None, TABLE_VERDICT[verdict],
                 json.dumps({"study_verdict": verdict, "spec_hash": SPEC_HASH, "event_set_sha256": spec["event_set_sha256"], "t": t,
                             "inflation": res.get("inflation"), "lag": res.get("lag")}), commit, now))
            con.execute("UPDATE experiment_registry SET status = ?, decision_reason = ? WHERE experiment_id = ?",
                        (status, reason, S.EXPERIMENT_ID))
    finally:
        con.close()
    lines = [f"# exp_007 — the one read: **{verdict}**", "",
             f"Read {now[:16]} UTC at commit {commit[:7]}; spec {SPEC_HASH[:12]}; event list {spec['event_set_sha256'][:12]}.",
             "", "## Primary (tested)", "",
             "Governance resignations pooled (auditor, independent director, CEO/MD, CFO), 63 sessions from the open "
             "after the filing, against CHAR_MATCHED; monthly cohorts; one-sided t with Bartlett inflation.", "",
             "| events | cohorts | mean cohort abnormal | t | inflation | bar | verdict |", "|---:|---:|---:|---:|---:|---|---|",
             f"| {res.get('events')} | {res.get('cohorts')} | {_pct(mean)} | {_num(t)} | {res.get("inflation") or 0:.2f} | "
             f"t <= {S.T_BAR} and mean <= {S.EFFECT_FLOOR:.2%} | **{verdict}** |", "",
             f"Registry status advanced to **{status}**; one trial charged to {S.FAMILY}.", "",
             "## Reported, never tested", "",
             "None of these is a test; none can change the verdict above.", "",
             "| figure | events | cohorts | mean | t |", "|---|---:|---:|---:|---:|"]
    for k, v in reported.items():
        if isinstance(v, dict) and "cohorts" in v:
            lines.append(f"| {k} | {v['events']} | {v['cohorts']} | {_pct(v.get('mean'))} | {_num(v.get('t'))} |")
    sb = reported["short_book"]
    lines += ["", f"CHAR_MATCHED rungs used: {reported['primary_benchmark_rungs']}", "",
              "Short book (reported): statutory round trip at the headline brokerage on Rs 10 lakh per name, "
              f"market impact and borrow EXCLUDED — median cost {_pct(sb['median_cost'])}; a short's mean "
              f"after that cost {_pct(sb['short_net'])}."]
    REPORT.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
