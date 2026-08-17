"""split.py — the exploration / selection / confirmation partition.

Implements configs/split.yml. Read that file first; it carries the reasoning and
the measurements. This module is the mechanism, and it exists so the partition is
enforced by code rather than remembered by a person.

THE ONE IDEA. Exploration should be free. On 2026-08-16 an unregistered search of
~100 cells moved the trial counter from 68 to 171, and under a single-pool regime
that raises every future bar permanently. Charging full price for looking is how
a discipline framework ends up suppressing the research it was built to protect.
So a fixed slice of the universe is designated a sandbox where looking costs
nothing, and the rest is spent deliberately.

THREE STRATA, because finding a hypothesis and choosing among candidates are
different expenditures. MICCV2's champion was not mined into existence; it was
SELECTED from a factory, and the selection was never charged for. Full-sample
Sharpe 1.52, trailing-24m 0.11.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Final, Literal

import yaml

from src.common.paths import CONFIGS

Stratum = Literal["EXPLORE", "SELECT", "CONFIRM"]
KeyKind = Literal["ISIN", "SYM"]

BUCKETS: Final[int] = 1000
CONFIG_PATH: Final[Path] = CONFIGS / "split.yml"


class SplitViolation(RuntimeError):
    """Raised when CONFIRM data is touched outside a registered experiment.

    Deliberately fatal. A guard that warns is a guard that gets ignored, and the
    whole point of the partition is that it cannot be spent by accident.
    """


class SplitConfigError(RuntimeError):
    """The spec is internally inconsistent. Raised at load, never at use."""


@lru_cache(maxsize=1)
def spec() -> dict:
    """The frozen split specification. Validated on first load."""
    cfg = yaml.safe_load(CONFIG_PATH.read_text())

    ranges = cfg["assignment"]["ranges"]
    covered = sorted((lo, hi) for lo, hi in ranges.values())
    cursor = 0
    for lo, hi in covered:
        if lo != cursor:
            raise SplitConfigError(
                f"assignment ranges are not contiguous: expected next range to "
                f"start at {cursor}, got {lo}. A gap means some names are "
                f"assigned to no stratum and vanish silently."
            )
        cursor = hi
    if cursor != cfg["assignment"]["buckets"]:
        raise SplitConfigError(
            f"assignment ranges cover [0,{cursor}) but buckets is "
            f"{cfg['assignment']['buckets']}."
        )

    total = sum(s["fraction"] for s in cfg["strata"].values())
    if abs(total - 1.0) > 1e-9:
        raise SplitConfigError(f"stratum fractions sum to {total}, not 1.0")

    # The declared fractions must match the ranges that actually do the work.
    # Two sources of truth for the same number is how documentation drifts, and
    # here the drift would be silent and statistical.
    for name, (lo, hi) in ranges.items():
        declared = cfg["strata"][name]["fraction"]
        implied = (hi - lo) / cfg["assignment"]["buckets"]
        if abs(declared - implied) > 1e-9:
            raise SplitConfigError(
                f"{name}: strata.fraction={declared} disagrees with "
                f"assignment.ranges {[lo, hi]} which implies {implied}."
            )
    return cfg


# --- keys --------------------------------------------------------------------


def split_key(symbol: str, isin: str | None = None) -> tuple[str, KeyKind]:
    """The identifier this name is partitioned by. ISIN when we have it.

    MEASURED 2026-08-17: 276 ISINs in the seed carry more than one symbol, 459 of
    those symbols appear in deal data, and they account for 26,046 deal rows —
    11.04% of all bulk and block rows. CADILAHC became ZYDUSLIFE; PRISMCEM became
    PRSMJOHNSN. Keyed on the symbol, each of those companies would sit in one
    stratum under its old name and another under its new one, contaminating the
    confirmation set by construction with nothing in the output looking wrong.

    The fallback is safe in the specific sense that matters: an unmapped symbol is
    one we cannot demonstrate ever renamed. The hazard lives entirely in the names
    we CAN resolve, and those always use the ISIN.
    """
    if isin and str(isin).strip() and str(isin).strip().lower() != "nan":
        return str(isin).strip().upper(), "ISIN"
    return f"SYM:{str(symbol).strip().upper()}", "SYM"


def bucket(key: str) -> int:
    """Deterministic bucket in [0, BUCKETS).

    Hash, not a seeded shuffle. A seeded shuffle over a symbol list reassigns
    every name whenever the list changes — and it changes with every listing and
    delisting. Hashing depends only on the identifier, so a new IPO self-assigns
    and no existing name ever moves. It also needs no stored seed and no stored
    membership list: the partition is recomputable from the identifier alone.
    """
    return int(hashlib.sha256(key.encode()).hexdigest()[:8], 16) % BUCKETS


def assign(symbol: str, isin: str | None = None) -> tuple[Stratum, KeyKind, int]:
    """Assign one name. Returns (stratum, key_kind, bucket)."""
    key, kind = split_key(symbol, isin)
    b = bucket(key)
    for name, (lo, hi) in spec()["assignment"]["ranges"].items():
        if lo <= b < hi:
            return name, kind, b  # type: ignore[return-value]
    raise SplitConfigError(f"bucket {b} fell outside every range — spec is broken")


# --- universe exclusions -----------------------------------------------------


def _glob_to_re(pattern: str) -> re.Pattern[str]:
    return re.compile("^" + re.escape(pattern).replace(r"\*", ".*") + "$", re.I)


def excluded(symbol: str) -> str | None:
    """The reason this symbol is out of the universe, or None.

    Found while measuring the split rather than by design: 160 of the 1,098
    unresolvable deal symbols end in -RE. Those are rights entitlements — they
    trade for a few days and expire. They have no continuing price series, so an
    "event" on one has no forward return to measure, only noise.
    """
    for rule in spec().get("exclusions", []):
        if _glob_to_re(rule["pattern"]).match(str(symbol).strip()):
            return rule["reason"]
    return None


# --- the honest sample size --------------------------------------------------


def effective_sample_size(n: int, mean_pairwise_corr: float) -> float:
    """n_eff under the standard design effect: n / (1 + (n-1) * rho).

    THIS IS THE NUMBER EVERY MDE IN THIS PROJECT CURRENTLY IGNORES.

    A name split reduces leakage between strata; it does not create independence.
    Equities move together through sector and market beta, so 2,100 confirmation
    names are nothing like 2,100 independent observations. At rho = 0.20 they are
    worth about five. At rho = 0.02 they are worth about fifty.

    Every MDE computed so far treats names as independent and is therefore
    OPTIMISTIC — possibly by a large factor. Reported alongside power, not in a
    footnote.
    """
    if n <= 1:
        return float(n)
    rho = max(0.0, float(mean_pairwise_corr))
    return n / (1.0 + (n - 1) * rho)


# --- enforcement -------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Access:
    """A single recorded touch of a stratum."""

    stratum: Stratum
    experiment_id: str | None
    purpose: str


class ConfirmationGuard:
    """Refuses reads of CONFIRM outside a registered experiment.

    Without enforcement the partition is a comment. That is precisely the failure
    this repo is built to prevent, and it would be a particularly embarrassing
    place to commit it.

    EXPLORE is unguarded on purpose. Being able to look freely is the feature.
    """

    def __init__(self, registered_experiment: str | None = None) -> None:
        self._experiment = registered_experiment
        self._log: list[Access] = []

    def check(self, stratum: Stratum, purpose: str) -> None:
        if stratum == "EXPLORE":
            self._log.append(Access(stratum, self._experiment, purpose))
            return

        if self._experiment is None:
            raise SplitViolation(
                f"Refusing to read {stratum} without a registered experiment.\n"
                f"  purpose: {purpose}\n"
                f"{stratum} is spent, not browsed. Register the experiment and "
                f"freeze its spec first:\n"
                f"    ConfirmationGuard(registered_experiment='exp_00N_...')\n"
                f"If you only want to look, use EXPLORE — that is what it is for "
                f"and it costs nothing."
            )

        if stratum == "CONFIRM":
            prior = sum(1 for a in self._log if a.stratum == "CONFIRM")
            cap = spec()["enforcement"]["max_confirm_touches_per_experiment"]
            if prior >= cap:
                raise SplitViolation(
                    f"{self._experiment} has already read CONFIRM {prior} time(s); "
                    f"the cap is {cap}.\n"
                    f"  attempted purpose: {purpose}\n"
                    f"A stratum read a hundred times by a hundred 'single' tests "
                    f"is a single-pool regime wearing a costume."
                )
        self._log.append(Access(stratum, self._experiment, purpose))

    @property
    def accesses(self) -> tuple[Access, ...]:
        return tuple(self._log)
