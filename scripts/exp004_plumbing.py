"""exp_004 plumbing check: the whole registered analysis on the REAL warehouse,
with every tested signal replaced by random noise.

WHY. holdings.run() has never executed end to end on real data — by design:
before registration it must not join the real signal to returns. exp_005's
real-data rehearsal found two defects synthetic tests missed. This runs every
join, the HORIZON/MOVED/STOPPED/CENSORED exit pricing, CHAR_MATCHED, every
robustness line and the verdict on real prices and real filings, but the
signal columns (d_fpi, d_foreign, d_mf and their holder-count twins) are
seeded random normals: nothing about the real signal-return link is read.
Decision 0035's dispersion rule in spirit — it prints counts and timings,
never a spread, a q or a verdict.

    RESEARCH_ENV=prod .venv/bin/python scripts/exp004_plumbing.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402

from src.research import holdings as h  # noqa: E402

NOISE_COLS = ("d_fpi", "d_foreign", "d_mf", "d_n_fpi", "d_n_foreign", "d_n_mf")


def main() -> int:
    t0 = time.time()
    real_signals = h.signals
    rng = np.random.default_rng(20261004)

    def noised(path=h.HOLDINGS):
        s = real_signals(path)
        counts = s.attrs["counts"]
        for c in NOISE_COLS:
            s[c] = rng.normal(size=len(s))
        s.attrs["counts"] = counts
        return s

    h.signals = noised
    h.registered_hash = lambda env=None: "PLUMBING-NOT-REGISTERED"
    sh, results, extra = h.run(permutations=20)
    v = h.verdict(results, extra["robustness"], extra["panel"])
    h.render(sh, results, extra, v)                     # exercised, never printed
    print("  plumbing OK — every stage ran on real data with noise signals")
    print(f"  {len(results)} primary tests, {len(extra['robustness'])} robustness lines, "
          f"{sum(len(r) for r in extra['robustness'].values())} robustness tests")
    for k, n in extra["counts"].items():
        print(f"    {k:<40} {n:,}" if isinstance(n, int) else f"    {k:<40} {n}")
    print(f"  {time.time() - t0:.0f} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
