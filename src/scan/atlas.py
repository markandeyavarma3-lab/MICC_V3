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
from pathlib import Path

import numpy as np

from src.scan import fastic
from src.scan import ic as icmod
from src.scan import signals as S
from src.scan.folds import Fold, FoldSet
from src.scan.panel import Panel
from src.scan.procedure import NULL_BLOCK_SESSIONS

BLOCK = NULL_BLOCK_SESSIONS


class BlockIC:
    """Per-candidate IC as block sums and counts, (B x K) each. Duck-types the
    (T x K) daily array the procedure test takes: fold indices are BLOCKS.

    A fold mean is a sum over a few CONTIGUOUS runs of blocks (a sequential
    fold's training set is one run, a CPCV training set at most three), so it
    is read off cumulative sums in O(runs x K) — at 1.9M candidates the direct
    sum over ~100 blocks per fold made the 200-rep null take hours. The count
    cumsum is shared by every sign-flipped copy the null makes; only the sums
    change sign."""

    def __init__(self, sums: np.ndarray, counts: np.ndarray, _cn: np.ndarray | None = None):
        self.sums, self.counts = sums, counts
        self._cs: np.ndarray | None = None
        self._cn = _cn

    @property
    def shape(self) -> tuple[int, int]:
        return self.sums.shape

    def _cum(self) -> tuple[np.ndarray, np.ndarray]:
        if self._cs is None:
            z = np.zeros((1, self.sums.shape[1]), dtype=np.float32)
            self._cs = np.concatenate([z, np.cumsum(self.sums, axis=0, dtype=np.float32)])
        if self._cn is None:
            z = np.zeros((1, self.counts.shape[1]), dtype=np.int32)
            self._cn = np.concatenate([z, np.cumsum(self.counts, axis=0, dtype=np.int32)])
        return self._cs, self._cn

    def mean_over(self, idx: np.ndarray) -> np.ndarray:
        cs, cn = self._cum()
        idx = np.unique(idx)
        if not len(idx):
            return np.full(self.sums.shape[1], np.nan)
        breaks = np.flatnonzero(np.diff(idx) != 1)
        starts = np.r_[idx[0], idx[breaks + 1]]
        stops = np.r_[idx[breaks], idx[-1]] + 1
        tot = np.zeros(self.sums.shape[1], dtype=np.float64)
        n = np.zeros(self.sums.shape[1], dtype=np.int64)
        for a, b in zip(starts, stops, strict=True):
            tot += cs[b] - cs[a]
            n += cn[b] - cn[a]
        with np.errstate(invalid="ignore", divide="ignore"):
            return np.where(n > 0, tot / n, np.nan)

    def __mul__(self, signs: np.ndarray) -> BlockIC:
        self._cum()
        return BlockIC(self.sums * signs.reshape(-1, 1).astype(np.float32), self.counts, _cn=self._cn)


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
    """One grid: a panel, a horizon, a depth. Shards under `out_dir`.

    Scoring goes through src/scan/fastic.py (decision 0084): base-signal ranks
    and their per-date cross-products are built ONCE (`prepare`), and each
    shard's candidates are scored in vectorised batches from them."""

    BATCH = 5_000

    def __init__(self, panel: Panel, out_dir: Path, horizon: int, depth: int,
                 gap: int = 1, shard_size: int = 100_000, min_names: int = 100,
                 only: list[str] | None = None):
        """`only` restricts the base signals — for tests, and for a grid cut
        the benchmark forces, which must then be recorded as a decision."""
        keep = panel.universe.any(axis=0)
        # Only names that are ever in the universe can be scored; signals on
        # the rest would be computed and thrown away.
        self.p = Panel(panel.dates, panel.ids[keep], *(getattr(panel, f)[:, keep] for f in
                       ("open", "high", "low", "close", "volume", "universe", "deal_buy", "deal_sell")))
        self.out, self.h, self.depth = Path(out_dir), horizon, depth
        self.gap, self.shard_size, self.min_names = gap, shard_size, min_names
        base = S.base_signals()
        if only is not None:
            unknown = set(only) - {b.id for b in base}
            if unknown:
                raise ValueError(f"unknown base signal(s): {sorted(unknown)}")
            base = [b for b in base if b.id in set(only)]
        self.base = sorted(base, key=lambda s: s.id)
        self.ids = [s.id for s in self.base]
        self.pos = {i: k for k, i in enumerate(self.ids)}
        self.total = S.combination_count(len(self.ids), depth)
        self._mo: fastic.Moments | None = None

    # --- identity of the grid -------------------------------------------------
    def manifest(self, commit: str = "") -> dict:
        ids_hash = hashlib.sha256(self.p.ids.tobytes()).hexdigest()[:16]
        return {"first": str(self.p.dates[0]), "last": str(self.p.dates[-1]),
                "sessions": len(self.p.dates), "securities": int(len(self.p.ids)), "ids_hash": ids_hash,
                "horizon": self.h, "gap": self.gap, "depth": self.depth, "block": BLOCK,
                "base_signals": len(self.ids), "candidates": self.total,
                "base_ids_hash": hashlib.sha256(",".join(self.ids).encode()).hexdigest()[:16],
                "statistic": "fastic: common cross-section J_t, rank-composite IC (0084)",
                "min_names": self.min_names, "code_commit": commit}

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
    def prepare(self) -> fastic.Moments:
        """Every base signal, reduced to universe slots, then the moments."""
        if self._mo is None:
            ctx = S.Ctx(self.p)
            slots = fastic._universe_slots(self.p.universe)
            fwd = fastic.compress(icmod.forward_returns(ctx.r, self.h, self.gap), slots)
            stack = np.empty((len(self.base), len(self.p.dates), slots.shape[1]), dtype=np.float32)
            for k, sig in enumerate(self.base):
                with np.errstate(all="ignore"):
                    x = sig.fn(ctx).astype(np.float64)
                x[~np.isfinite(x)] = np.nan
                stack[k] = fastic.compress(x, slots)
                ctx._cache.clear()      # ~78 MB a rolling array; holding all of them would not fit
            self._mo = fastic.moments(stack, fwd, self.min_names)
        return self._mo

    def score_many(self, cands: list[tuple[tuple[str, int], ...]]) -> tuple[np.ndarray, np.ndarray]:
        """(nblocks, B) block sums and counts for `cands`, in the given order."""
        mo = self.prepare()
        sums, counts = [], []
        by_depth: dict[int, list[int]] = {}
        for j, c in enumerate(cands):
            by_depth.setdefault(len(c), []).append(j)
        out_s = [None] * len(cands)
        out_c = [None] * len(cands)
        for d, js in by_depth.items():
            for lo in range(0, len(js), self.BATCH):
                part = js[lo:lo + self.BATCH]
                idx = np.array([[self.pos[i] for i, _ in cands[j]] for j in part], dtype=np.int64).reshape(-1, d)
                sg = np.array([[s for _, s in cands[j]] for j in part], dtype=np.float64).reshape(-1, d)
                bs, bc = fastic.block_sums(fastic.batch_ic(mo, idx, sg), BLOCK)
                for k, j in enumerate(part):
                    out_s[j], out_c[j] = bs[:, k], bc[:, k]
        sums = np.stack(out_s, axis=1)
        counts = np.stack(out_c, axis=1)
        return sums, counts

    def run(self, commit: str = "", limit_shards: int | None = None) -> int:
        """Compute missing shards; returns how many were written this call."""
        self._check_manifest(commit)
        n_shards = -(-self.total // self.shard_size)
        written = 0
        gen = S.combinations_of(self.ids, self.depth)
        for s in range(n_shards):
            lo, hi = s * self.shard_size, min((s + 1) * self.shard_size, self.total)
            path = self.out / f"shard_{s:05d}.npz"
            cands = [next(gen) for _ in range(hi - lo)]
            if path.exists():
                continue
            if limit_shards is not None and written >= limit_shards:
                break
            sums, counts = self.score_many(cands)
            keys = ["|".join(f"{'+' if sg > 0 else '-'}{i}" for i, sg in c) for c in cands]
            tmp = path.with_suffix(".partial.npz")
            np.savez_compressed(tmp, sums=sums, counts=counts, keys=np.array(keys), lo=lo, hi=hi)
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
        """Time the one-off preparation and a seeded random sample of the grid
        (all depths, in proportion), and project the full run."""
        t0 = time.perf_counter()
        self.prepare()
        t_prep = time.perf_counter() - t0
        rng = np.random.default_rng(seed)
        k = max(20, int(self.total * fraction))
        want = set(rng.choice(self.total, size=min(k, self.total), replace=False).tolist())
        sample = [c for j, c in enumerate(S.combinations_of(self.ids, self.depth)) if j in want]
        t1 = time.perf_counter()
        self.score_many(sample)
        per = (time.perf_counter() - t1) / len(sample)
        days = (t_prep + per * self.total) / 86400
        return {"candidates": self.total, "sampled": len(sample), "seconds_per_candidate": per,
                "rank_setup_seconds": t_prep, "projected_days": days,
                "within_budget": days <= max_days, "budget_days": max_days}
