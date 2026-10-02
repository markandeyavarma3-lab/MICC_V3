"""exp_005: the registered Track S run, or its rehearsal on exploration data.

    RESEARCH_ENV=prod .venv/bin/python scripts/scan_confirm.py --rehearse-explore
        The whole registered analysis (src/scan/confirm.py) on 2005-2015 with
        yearly test windows 2010-2015. Exploration: free, reads no 2016 data,
        writes a report and records nothing in the ledger.

    RESEARCH_ENV=prod .venv/bin/python scripts/scan_confirm.py
        The registered CONFIRM run on 2016+. Refuses unless exp_005 is
        REGISTERED; records CONFIRM in procedure_result; run once.
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
from src.scan import atlas, confirm, folds, panel, procedure  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rehearse-explore", action="store_true")
    ap.add_argument("--reps", type=int, default=confirm.NULL_REPS)
    a = ap.parse_args()
    cfg = yaml.safe_load((CONFIGS / "scan.yml").read_text())
    h, depth = int(cfg["signals"]["primary_horizon_sessions"]), int(cfg["signals"]["max_depth"])
    top_n = [int(x) for x in cfg["procedure_test"]["top_n"]]
    commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    t0 = time.time()

    if a.rehearse_explore:
        end = date.fromisoformat(yaml.safe_load((CONFIGS / "split.yml").read_text())
                                 ["scan"]["temporal"]["explore_end"])
        p = panel.load(end=end)
        at = atlas.Atlas(p, warehouse_dir() / "scan" / f"explore_h{h}_d{depth}", horizon=h, depth=depth)
        fs = folds.sequential(at.p.dates, date(2005, 1, 1), date(2010, 1, 1), 1, 1, 21)
        title, regime, sh = f"SCAN_REHEARSAL_EXPLORE_H{h}.md — exp_005's analysis on EXPLORATION data", None, None
        note = ("**EXPLORE (2005-2015), yearly test windows 2010-2015: the registered analysis rehearsed on "
                "data it is free to read. Not a finding; nothing recorded in the ledger.**")
    else:
        sh = confirm.registered_hash()
        p = panel.load()
        at = atlas.Atlas(p, warehouse_dir() / "scan" / f"confirm_h{h}_d{depth}", horizon=h, depth=depth)
        fs = folds.confirm(at.p.dates)
        title, regime = f"SCAN_CONFIRM_H{h}.md — exp_005, the registered run", "CONFIRM"
        note = f"**CONFIRM (2016+), spec_hash `{sh[:12]}`, commit `{commit[:12]}`. Run once.**"

    print(f"  panel {len(at.p.dates):,} x {len(at.p.ids):,}; grid {at.total:,}; folds {fs.note}", flush=True)
    at.run(commit)
    bic, keys = at.load()
    print(f"  atlas ready ({time.time() - t0:.0f} s)", flush=True)
    o = confirm.evaluate(at, bic, keys, fs, top_n, reps=a.reps)
    text = confirm.render(o, title, note, fs)
    name = title.split(" ")[0]
    (DOCS / "reports" / name).write_text(text)
    if regime == "CONFIRM":
        run_id = procedure.record(o.primary, o.pbo, at.manifest(commit), "CONFIRM", at.total, commit,
                                  experiment_id=confirm.EXPERIMENT_ID, keys=keys,
                                  fold_names=[f.name for f in fs.folds])
        print(f"  recorded CONFIRM run_id {run_id}", flush=True)
    print(text, flush=True)
    print(f"  wrote docs/reports/{name}  ({time.time() - t0:.0f} s)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
