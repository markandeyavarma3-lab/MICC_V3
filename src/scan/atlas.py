"""atlas.py — run every candidate, chunked, resumable, and timed first.
Plan 4 §10, Plan 3 step 6S.6, configs/scan.yml `compute`.

WHAT IS STORED, AND WHY NOT THE IC SERIES. A depth-3 grid is ~1.9M candidates;
a daily IC series each over 21 years is ~40 GB. The procedure test needs only
fold means, and the null flips signs in 21-session blocks
(procedure.NULL_BLOCK_SESSIONS) — so each candidate is stored as the SUM and
COUNT of its daily IC in each block: ~2 KB a candidate. A fold mean is then
sum over its blocks / count over its blocks, exactly the session-weighted
mean, provided the fold's windows are whole blocks (`block_folds`), and the
null's sign flips act on blocks by construction.

RESUMABLE. Candidates are enumerated in one deterministic order
(signals.combinations_of over sorted base ids); a shard holds a contiguous
range and is written atomically; a run picks up at the first missing shard.
A manifest pins what the shards were computed from — panel span, security
set, horizon, gap, depth, block, code commit — and a resume against a
different manifest is REFUSED, because mixing shards from two panels makes a
grid nobody ran.

TIMED BEFORE IT RUNS. scan.yml: "a benchmark on 1/1000th of the grid must
produce a measured projection", and a projection past max_wall_clock_days
cuts the grid by a recorded decision. `benchmark()` times a seeded random
sample, never the first chunk (the first chunk is all depth-1, the cheapest).
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from src.scan import ic as icmod
from src.scan import signals as S
from src.scan.folds import Fold, FoldSet
from src.scan.panel import Panel
from src.scan.procedure import NULL_BLOCK_SESSIONS

BLOCK = NULL_BLOCK_SESSIONS


@dataclass
class BlockIC:
    """Per-candidate IC as block sums and counts, (B x K) each. Duck-types the
    (T x K) daily array the procedure test takes: fold indices are BLOCKS."""
    sums: np.ndarray
    counts: np.ndarray

    @property
    def shape(self) -> tuple[int, int]:
        return self.sums.shape

    def mean_over(self, idx: np.ndarray) -> np.ndarray:
        n = self.counts[idx].sum(axis=0)
        with np.errstate(invalid="ignore", divide="ignore"):
            return np.where(n > 0, self.sums[idx].sum(axis=0) / n, np.nan)

    def __mul__(self, signs: np.ndarray) -> BlockIC:
        return BlockIC(self.sums * signs.reshape(-1, 1), self.counts)


def to_blocks(daily_ic: np.ndarray, block: int = BLOCK) -> tuple[np.ndarray, np.ndarray]:
    """(T,) daily IC -> (B,) sums and counts over consecutive `block`-session blocks."""
    T = len(daily_ic)
    b = np.arange(T) // block
    ok = ~np.isnan(daily_ic)
    sums = np.bincount(b[ok], weights=daily_ic[ok], minlength=b[-1] + 1)
    counts = np.bincount(b[ok], minlength=b[-1] + 1)
    return sums.astype(np.float32), counts.astype(np.int16)


def block_folds(fs: FoldSet, block: int = BLOCK) -> FoldSet:
    """A session FoldSet as whole blocks: a block belongs to a fold's training
    or test set only if every one of its sessions does. Edge blocks are
    dropped, never shared — which also widens every embargo to a whole block."""
    out = []
    for f in fs.folds:
        def whole(idx):
            b, n = np.unique(idx // block, return_counts=True)
            return b[n == block]
        tr, te = whole(f.train), whole(f.test)
        tr = np.setdiff1d(tr, te)
        out.append(Fold(f.name, tr, te))
    return FoldSet(fs.design + "_blocks", out, fs.nominal, fs.effective, fs.note)


class Atlas:
    """One grid: a panel, a horizon, a depth. Shards under `out_dir`."""

    def __init__(self, panel: Panel, out_dir: Path, horizon: int, depth: int,
                 gap: int = 1, shard_size: int = 100_000, min_names: int = 100,
                 only: list[str] | None = None):
        """`only` restricts the base signals — for tests, and for a grid cut
        the benchmark forces, which must then be recorded as a decision."""
        self.p, self.out, self.h, self.depth = panel, Path(out_dir), horizon, depth
        self.gap, self.shard_size, self.min_names = gap, shard_size, min_names
        self.ctx = S.Ctx(panel)
        base = S.base_signals()
        if only is not None:
            unknown = set(only) - {b.id for b in base}
            if unknown:
                raise ValueError(f"unknown base signal(s): {sorted(unknown)}")
            base = [b for b in base if b.id in set(only)]
        self.base = sorted(base, key=lambda s: s.id)
        self.ids = [s.id for s in self.base]
        self.total = S.combination_count(len(self.ids), depth)
        self._ranks: dict[str, np.ndarray] = {}
        fwd = icmod.forward_returns(self.ctx.r, horizon, gap)
        self.fwd = np.where(panel.universe, fwd, np.nan)

    # --- identity of the grid -------------------------------------------------
    def manifest(self, commit: str = "") -> dict:
        ids_hash = hashlib.sha256(self.p.ids.tobytes()).hexdigest()[:16]
        return {"first": str(self.p.dates[0]), "last": str(self.p.dates[-1]),
                "sessions": len(self.p.dates), "securities": int(len(self.p.ids)), "ids_hash": ids_hash,
                "horizon": self.h, "gap": self.gap, "depth": self.depth, "block": BLOCK,
                "base_signals": len(self.ids), "candidates": self.total,
                "base_ids_hash": hashlib.sha256(",".join(self.ids).encode()).hexdigest()[:16],
                "code_commit": commit}

    def _check_manifest(self, commit: str) -> None:
        self.out.mkdir(parents=True, exist_ok=True)
        m = self.out / "manifest.json"
        want = self.manifest(commit)
        if m.exists():
            have = json.loads(m.read_text())
            diff = {k for k in want if k != "code_commit" and have.get(k) != want[k]}
            if diff:
                raise RuntimeError(f"{self.out} holds shards of a different grid ({sorted(diff)}); "
                                   "refusing to mix them — use a new directory")
        else:
            m.write_text(json.dumps(want, indent=1))

    # --- computing --------------------------------------------------------------
    def ranks(self, sid: str) -> np.ndarray:
        if sid not in self._ranks:
            sig = next(s for s in self.base if s.id == sid)
            with np.errstate(all="ignore"):
                x = sig.fn(self.ctx).astype(np.float64)
            x[~np.isfinite(x)] = np.nan
            self._ranks[sid] = S.percentile_ranks(x, self.p.universe).astype(np.float32)
        return self._ranks[sid]

    def candidate(self, i: int) -> tuple[tuple[str, int], ...]:
        """The i-th candidate in the canonical order (walks the generator;
        used for sampling, not the hot loop)."""
        for k, c in enumerate(S.combinations_of(self.ids, self.depth)):
            if k == i:
                return c
        raise IndexError(i)

    def score(self, cand: tuple[tuple[str, int], ...]) -> tuple[np.ndarray, np.ndarray]:
        x = S.combine({i: self.ranks(i) for i, _ in cand}, cand)
        return to_blocks(icmod.rank_ic(x, self.fwd, self.min_names))

    def run(self, commit: str = "", limit_shards: int | None = None) -> int:
        """Compute missing shards; returns how many were written this call."""
        self._check_manifest(commit)
        n_shards = -(-self.total // self.shard_size)
        written = 0
        gen = S.combinations_of(self.ids, self.depth)
        for s in range(n_shards):
            lo, hi = s * self.shard_size, min((s + 1) * self.shard_size, self.total)
            path = self.out / f"shard_{s:05d}.npz"
            if path.exists():
                for _ in range(hi - lo):
                    next(gen)
                continue
            if limit_shards is not None and written >= limit_shards:
                break
            sums, counts, keys = [], [], []
            for _ in range(hi - lo):
                c = next(gen)
                a, b = self.score(c)
                sums.append(a)
                counts.append(b)
                keys.append("|".join(f"{'+' if sg > 0 else '-'}{i}" for i, sg in c))
            tmp = path.with_suffix(".partial.npz")
            np.savez_compressed(tmp, sums=np.stack(sums, axis=1), counts=np.stack(counts, axis=1),
                                keys=np.array(keys), lo=lo, hi=hi)
            tmp.replace(path)
            written += 1
        return written

    def load(self) -> tuple[BlockIC, list[str]]:
        shards = sorted(self.out.glob("shard_*.npz"))
        n_shards = -(-self.total // self.shard_size)
        if len(shards) != n_shards:
            raise RuntimeError(f"{len(shards)} of {n_shards} shards present; the grid is incomplete")
        parts = [np.load(f) for f in shards]
        return (BlockIC(np.concatenate([p["sums"] for p in parts], axis=1),
                        np.concatenate([p["counts"] for p in parts], axis=1)),
                [k for p in parts for k in p["keys"].tolist()])

    # --- the gate -----------------------------------------------------------------
    def benchmark(self, fraction: float = 0.001, seed: int = 20261002, max_days: float = 21.0) -> dict:
        """Time a seeded random sample of the grid and project the full run.
        Base-signal ranks are computed first and timed separately: they are a
        one-off cost, not a per-candidate one."""
        t0 = time.perf_counter()
        for i in self.ids:
            self.ranks(i)
        t_ranks = time.perf_counter() - t0
        rng = np.random.default_rng(seed)
        k = max(20, int(self.total * fraction))
        want = set(rng.choice(self.total, size=min(k, self.total), replace=False).tolist())
        sample = [c for j, c in enumerate(S.combinations_of(self.ids, self.depth)) if j in want]
        t1 = time.perf_counter()
        for c in sample:
            self.score(c)
        per = (time.perf_counter() - t1) / len(sample)
        days = (t_ranks + per * self.total) / 86400
        return {"candidates": self.total, "sampled": len(sample), "seconds_per_candidate": per,
                "rank_setup_seconds": t_ranks, "projected_days": days,
                "within_budget": days <= max_days, "budget_days": max_days}
