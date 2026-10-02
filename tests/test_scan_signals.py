"""Track S2's base signals (Plan 3 step 6S.5).

Pinned: no signal reads past the close of its own session; every signal has a
written mechanism; counts are computed, never written down; and the panel
loads neither exp_004's signal nor the insider data."""

from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pytest

from src.scan import signals as S
from src.scan.panel import Panel

pytestmark = pytest.mark.unit
ROOT = Path(__file__).resolve().parents[1]


def _panel(T=700, N=60, seed=0):
    rng = np.random.default_rng(seed)
    d, dates = date(2010, 1, 4), []
    while len(dates) < T:
        if d.weekday() < 5:
            dates.append(d)
        d += timedelta(days=1)
    close = (100 * np.exp(np.cumsum(rng.normal(0, 0.02, (T, N)), axis=0))).astype(np.float32)
    open_ = (close * np.exp(rng.normal(0, 0.005, (T, N)))).astype(np.float32)
    high = (np.maximum(open_, close) * 1.01).astype(np.float32)
    low = (np.minimum(open_, close) * 0.99).astype(np.float32)
    vol = rng.integers(1_000, 100_000, (T, N)).astype(np.float32)
    buy = np.where(rng.random((T, N)) < 0.02, rng.random((T, N)) * 1e7, 0).astype(np.float32)
    sell = np.where(rng.random((T, N)) < 0.02, rng.random((T, N)) * 1e7, 0).astype(np.float32)
    return Panel(dates, np.arange(N), open_, high, low, close, vol, np.ones((T, N), bool), buy, sell)


def test_no_signal_reads_past_its_own_close():
    """Scramble every price, volume and deal after session `cut`; every value
    on or before `cut` must be unchanged, for every base signal."""
    p = _panel()
    cut = 550
    q = _panel(seed=1)
    for f in ("open", "high", "low", "close", "volume", "deal_buy", "deal_sell"):
        a = getattr(p, f).copy()
        a[cut + 1:] = getattr(q, f)[cut + 1:]
        setattr(q, f, a)
    c1, c2 = S.Ctx(p), S.Ctx(q)
    leaks = []
    for s in S.base_signals():
        x, y = s.fn(c1)[: cut + 1], s.fn(c2)[: cut + 1]
        if not np.allclose(x, y, equal_nan=True, rtol=1e-6, atol=1e-9):
            leaks.append(s.id)
    assert not leaks, f"read future data: {leaks}"


def test_every_signal_has_a_written_mechanism_from_a_declared_family():
    import yaml

    from src.common.paths import CONFIGS
    declared = {f["id"] for f in yaml.safe_load((CONFIGS / "scan.yml").read_text())["signals"]["families"]}
    for s in S.base_signals():
        assert s.family in declared, s.id
        assert len(s.mechanism) > 40 and s.note, s.id


def test_every_signal_produces_values_on_a_long_enough_panel():
    c = S.Ctx(_panel())
    empty = [s.id for s in S.base_signals() if np.isnan(s.fn(c)[-1]).all()]
    assert not empty, f"all-NaN on the last session: {empty}"


def test_the_combination_count_is_the_enumeration():
    ids = [f"s{i}" for i in range(7)]
    for d in (1, 2, 3):
        assert S.combination_count(len(ids), d) == sum(1 for _ in S.combinations_of(ids, d))


def test_no_count_is_written_down_in_the_scan_package():
    n = len(S.base_signals())
    counts = {S.combination_count(n, d) for d in (1, 2, 3)}
    for f in (ROOT / "src" / "scan").glob("*.py"):
        nums = {int(x.replace(",", "").replace("_", "")) for x in re.findall(r"\b\d[\d,_]{2,}\b", f.read_text())}
        assert not (nums & counts), f"{f.name} hard-codes a realised count"


def test_ranks_are_taken_inside_the_universe_only():
    x = np.arange(12, dtype=float).reshape(2, 6)
    uni = np.array([[True] * 4 + [False] * 2] * 2)
    r = S.percentile_ranks(x, uni)
    assert np.isnan(r[:, 4:]).all() and np.allclose(r[0, :4], [0.25, 0.5, 0.75, 1.0])


def test_the_panel_never_loads_exp004s_signal_or_insider_data():
    src = (ROOT / "src" / "scan" / "panel.py").read_text()
    sql = " ".join(re.findall(r'"""(.*?)"""', src, re.S)[1:])     # every SQL string, not the docstring
    assert "shp" not in sql.lower() and "insider" not in sql.lower()
