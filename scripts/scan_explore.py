"""Track S's exploration run: the full grid and the procedure test on
2005-2015 only (split.yml scan.temporal: explore is free to mine).

The result is recorded as EXPLORE in governance `procedure_result` (write-once)
and is NOT a finding: it informs the CONFIRM registration, which tests 2016+
once. No 2016 data is read — the panel ends at explore_end and the last
forward windows that would reach into 2016 carry no IC (decision 0084).

    RESEARCH_ENV=prod .venv/bin/python scripts/scan_explore.py [--horizon 21] [--reps 200]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import yaml  # noqa: E402

from src.common.paths import CONFIGS, DOCS, warehouse_dir  # noqa: E402
from src.scan import atlas, folds, panel, procedure  # noqa: E402


def main() -> int:
    cfg = yaml.safe_load((CONFIGS / "scan.yml").read_text())
    ap = argparse.ArgumentParser()
    ap.add_argument("--horizon", type=int, default=int(cfg["signals"]["primary_horizon_sessions"]))
    ap.add_argument("--depth", type=int, default=int(cfg["signals"]["max_depth"]))
    ap.add_argument("--reps", type=int, default=200)
    a = ap.parse_args()
    explore_end = date.fromisoformat(yaml.safe_load((CONFIGS / "split.yml").read_text())
                                     ["scan"]["temporal"]["explore_end"])
    top_n = [int(x) for x in cfg["procedure_test"]["top_n"]]
    commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()

    t0 = time.time()
    p = panel.load(end=explore_end)
    out = warehouse_dir() / "scan" / f"explore_h{a.horizon}_d{a.depth}"
    at = atlas.Atlas(p, out, horizon=a.horizon, depth=a.depth)
    print(f"  panel {len(at.p.dates):,} sessions x {len(at.p.ids):,} names; grid {at.total:,} candidates", flush=True)
    wrote = at.run(commit)
    print(f"  atlas: {wrote} shard(s) written ({time.time() - t0:.0f} s)", flush=True)
    bic, keys = at.load()

    fs = folds.from_config(at.p.dates, end=explore_end)
    seq, cp = atlas.block_folds(fs["sequential"]), atlas.block_folds(fs["cpcv"])
    print(f"  folds: {seq.note}; {cp.note}", flush=True)
    results, pbo = procedure.run(bic, seq, cp, top_n, reps=a.reps)
    print(f"  procedure + null: {time.time() - t0:.0f} s", flush=True)
    run_id = procedure.record(results, pbo, at.manifest(commit), "EXPLORE", at.total, commit,
                              keys=keys, fold_names=[f.name for f in seq.folds])

    L = [f"# SCAN_EXPLORE_H{a.horizon}.md — Track S procedure test, EXPLORATION ONLY",
         "",
         f"**Regime EXPLORE (2005-2015; split.yml scan.temporal). Not a finding.** run_id `{run_id}`, "
         f"commit `{commit[:12]}`. Recorded write-once in governance `procedure_result`. "
         "It informs the CONFIRM registration, which tests 2016+ once.",
         "",
         f"- grid: {at.total:,} candidates — {len(at.ids)} base signals to depth {a.depth} "
         f"(signed rank composites, decision 0084), forward horizon {a.horizon} sessions after a one-session gap",
         f"- panel: {at.p.dates[0]} .. {at.p.dates[-1]}, {len(at.p.ids):,} names ever in the point-in-time top 500",
         f"- folds: {seq.note}",
         f"- null: block sign flips, {a.reps} reps (procedure.null_hit_rates)",
         f"- PBO over {cp.nominal} CPCV paths: **{pbo:.2f}**",
         "",
         "| top N | folds | effective | hit rate | null mean | p vs null | train IC | test IC | degradation | rank decay |",
         "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for r in results:
        L.append(f"| {r.top_n} | {r.folds} | {r.effective_folds:.1f} | **{r.hit_rate:.2f}** | "
                 f"{r.null_hit_rates.mean():.2f} | {r.p_vs_null:.3f} | {r.mean_train_ic:+.4f} | "
                 f"{r.mean_test_ic:+.4f} | {r.degradation:+.4f} | {r.rank_decay:+.3f} |")
    L += ["", "Per-fold test IC of the selected set (sequential folds, training sign):", ""]
    L += [f"- top {r.top_n}: " + ", ".join(f"{f.name} {x:+.4f}" for f, x in zip(seq.folds, r.per_fold_test_ic, strict=False))
          for r in results]
    rep = DOCS / "reports" / f"SCAN_EXPLORE_H{a.horizon}.md"
    rep.write_text("\n".join(L) + "\n")
    print("\n".join(L), flush=True)
    print(f"\n  wrote {rep}  ({time.time() - t0:.0f} s total)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
