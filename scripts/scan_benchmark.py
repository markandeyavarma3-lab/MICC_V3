"""Track S's compute gate: time 1/1000 of the grid before any full run.
Plan 4 §10, configs/scan.yml `compute`.

EXPLORE DATA ONLY (2005-2015, split.yml scan.temporal), and TIMING ONLY: the
sampled candidates are scored to be timed, and their ICs are discarded. The
projection is for the full explore grid; a CONFIRM grid spans ~2x the
sessions and is projected at that ratio.

    RESEARCH_ENV=prod .venv/bin/python scripts/scan_benchmark.py [--depth 3]
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import yaml  # noqa: E402

from src.common.paths import CONFIGS  # noqa: E402
from src.scan import atlas, panel  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--depth", type=int, default=3)
    a = ap.parse_args()
    cfg = yaml.safe_load((CONFIGS / "scan.yml").read_text())
    budget = float(cfg["compute"]["max_wall_clock_days"])
    frac = float(cfg["compute"]["benchmark_fraction"])
    h = int(cfg["signals"]["primary_horizon_sessions"])
    explore_end = date.fromisoformat(yaml.safe_load((CONFIGS / "split.yml").read_text())
                                     ["scan"]["temporal"]["explore_end"])
    p = panel.load(end=explore_end)
    print(f"  panel: {len(p.dates):,} sessions x {len(p.ids):,} securities "
          f"({p.dates[0]} .. {p.dates[-1]}); universe mean {p.universe.sum(axis=1).mean():.0f} names/session")
    at = atlas.Atlas(p, Path(tempfile.mkdtemp()), horizon=h, depth=a.depth)
    b = at.benchmark(fraction=frac, max_days=budget)
    confirm_ratio = 2.0
    print(f"  grid: {b['candidates']:,} candidates at depth {a.depth}; sampled {b['sampled']:,}")
    print(f"  base-signal ranks: {b['rank_setup_seconds']:.0f} s (once)")
    print(f"  per candidate: {b['seconds_per_candidate'] * 1000:.1f} ms")
    print(f"  projected: explore {b['projected_days']:.2f} days, confirm ~{b['projected_days'] * confirm_ratio:.2f} days "
          f"(budget {budget:.0f}) -> {'WITHIN' if b['projected_days'] * confirm_ratio <= budget else 'OVER'} budget")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
