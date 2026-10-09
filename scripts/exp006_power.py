"""exp_006 preliminary power: how many FORWARD months a frozen factor-neutral
selection needs before its mean IC can be told from zero.

WHY. exp_005's partial (factor-neutral) procedure passed 10 of 11 CONFIRM years
(q 0.009) and could not count: the ladder put the primary first (0085). 2016+
is spent, so the only honest test of "the factor-neutral residual of a wide
search persists" is on sessions nobody has seen: freeze the selection on
everything to date, then score it on what arrives after registration.

WHAT THIS READS. The CONFIRM atlas (2005-01-03 .. 2026-10-01, the grid exp_005
ran), the partial IC net of exp_005's two attribution factors, the top-N sets
selected on ALL of it, and each set's per-block IC series. It prints the
series' DISPERSION only — SD, lag-1 autocorrelation, the serial inflation and
the number of forward blocks the design needs. Never a mean: the in-sample
mean of a set selected on the same blocks is selection, not information, and
the out-of-sample effect size is the one exp_005 already recorded (test IC
~+0.029). Decision 0035's rule. Unregistered and uncharged.

    RESEARCH_ENV=prod .venv/bin/python scripts/exp006_power.py
"""

from __future__ import annotations

import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402
import yaml  # noqa: E402

from src.common.paths import CONFIGS, warehouse_dir  # noqa: E402
from src.scan import atlas, confirm, panel  # noqa: E402

#: exp_005's recorded out-of-sample partial test IC (top 1 / 10 / 100), 0085.
RECORDED_TEST_IC = {1: 0.0267, 10: 0.0290, 100: 0.0296}
ATLAS_END = date(2026, 10, 1)            # the CONFIRM grid's last session
Z_ALPHA, Z_POWER = 1.645, 0.842          # one-sided 5%, 80% power
BLOCKS_PER_YEAR = 252 / 21


def series_dispersion(x: np.ndarray) -> tuple[float, float, float]:
    """(SD, lag-1 autocorrelation, variance inflation for the mean) of a
    per-block series; the inflation is the AR(1) long-run factor (1+r)/(1-r),
    floored at 1 so negative autocorrelation never shrinks the requirement."""
    x = x[np.isfinite(x)]
    sd = float(np.std(x, ddof=1))
    r = float(np.corrcoef(x[:-1], x[1:])[0, 1]) if len(x) > 2 else 0.0
    return sd, r, max(1.0, (1 + r) / (1 - r))


def blocks_needed(sd: float, infl: float, effect: float) -> float:
    return ((Z_ALPHA + Z_POWER) * sd / effect) ** 2 * infl


def main() -> int:
    t0 = time.time()
    cfg = yaml.safe_load((CONFIGS / "scan.yml").read_text())
    h, depth = int(cfg["signals"]["primary_horizon_sessions"]), int(cfg["signals"]["max_depth"])
    top_n = [int(x) for x in cfg["procedure_test"]["top_n"]]
    at = atlas.Atlas(panel.load(end=ATLAS_END), warehouse_dir() / "scan" / f"confirm_h{h}_d{depth}",
                     horizon=h, depth=depth)
    at._check_manifest("")                # the same grid exp_005 ran, or refuse
    bic = at.partial_all(list(confirm.ATTRIBUTION_FACTORS))
    n_blocks = bic.shape[0]
    every = np.arange(n_blocks)
    mean_all = bic.mean_over(every)       # used ONLY to rank and sign; never printed
    print(f"  partial atlas: {n_blocks} blocks x {bic.shape[1]:,} candidates ({time.time() - t0:.0f} s)")
    print("\n| top N | blocks | SD of block IC | lag-1 r | inflation | effect (exp_005 test IC) "
          "| blocks needed | years needed |")
    print("|---:|---:|---:|---:|---:|---:|---:|---:|")
    for n in top_n:
        sel = np.argpartition(-np.abs(np.nan_to_num(mean_all)), n - 1)[:n]
        # Only the selected columns: the full B x K matrix is ~4 GB at float64.
        cnt = bic.counts[:, sel]
        blk = np.where(cnt > 0, bic.sums[:, sel] / np.maximum(cnt, 1), np.nan)
        signed = blk * np.sign(mean_all[sel])
        s = np.nanmean(signed, axis=1)
        sd, r, infl = series_dispersion(s)
        need = blocks_needed(sd, infl, RECORDED_TEST_IC[n])
        print(f"| {n} | {np.isfinite(s).sum()} | {sd:.4f} | {r:+.2f} | {infl:.2f} | "
              f"{RECORDED_TEST_IC[n]:.4f} | {need:.0f} | {need / BLOCKS_PER_YEAR:.1f} |")
    print(f"\n  {time.time() - t0:.0f} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
