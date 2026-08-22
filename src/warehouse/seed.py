"""seed.py — carry the irreplaceable history into this repo, hashed. Phase 1.7.

WHAT IS CARRIED, AND WHY IT IS NOT JUST `v1_export`.

Plan 1 §3.1 carries `MICCV2/data/raw/v1_export/` and §3.2 drops
`MICCV2/data/warehouse/` as *"derived, rebuilt by new code from v1_export"*.
Measured 2026-08-21, that is not a description of work anyone can do:

    prices  7,676,618 (seed) +      72,530 (warehouse inc) = 7,749,148
    F&O    69,193,526 (seed) + 105,422,837 (warehouse fno) = 174,616,363

Both totals on the right are the Phase 1 gate figures in `configs/universe.yml`,
which carries `tolerance: 0`. Every one of the eight gate numbers resolves
against the directory marked for deletion and none against the directory marked
for carrying, because the seed was frozen on 2026-07-08 while the gate was
measured on 2026-08-16 against a live warehouse. `fo_data/` jumps from `_y=2016`
straight to `_y=2026` — nine years of F&O exist nowhere else, and NSE does not
re-serve them.

Decision 0027 resolves it: both are carried, and both are treated as immutable
seed input.

WHY COPY RATHER THAN REFERENCE. A symlink into MICCV2 would keep this repo
dependent on a directory the plan intends to eventually tarball, and would let a
change over there silently alter results over here. The copy is verified by
hash and registered in the provenance DAG, so "is our seed still the seed?" is a
query.

IDEMPOTENT. A file already present with a matching hash is skipped. The whole
carry can be re-run at any time and the second run verifies rather than repeats.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

from src.common.hashing import hash_file
from src.common.paths import SEED, SEED_INCREMENTS, predecessor_root
from src.governance import provenance as prov

PRODUCED_BY = "src.warehouse.seed:carry"


class SeedError(RuntimeError):
    """The seed cannot be carried or does not verify. Deliberately fatal."""


@dataclass(frozen=True, slots=True)
class Source:
    """One directory to carry, and where it lands."""

    #: Path relative to the predecessor repo root.
    src_rel: str
    #: Path relative to this repo, resolved by `destination`.
    logical_name: str
    #: Why this is irreplaceable, printed in the report and stored in the DAG.
    rationale: str
    is_increment: bool = False

    def source(self) -> Path:
        return predecessor_root() / self.src_rel

    def destination(self) -> Path:
        if not self.is_increment:
            return SEED
        return SEED_INCREMENTS / self.logical_name


#: The three directories decision 0027 carries. Nothing else from MICCV2 comes
#: across: `data/warehouse/` beyond these two partitions IS regenerable, and
#: `src/` is the 27k lines of strategy code the rebuild exists to drop.
SOURCES: tuple[Source, ...] = (
    Source(
        "data/raw/v1_export",
        "v1_export",
        "The V1 seed: 126 parquet files, 11.3M rows, 2005-2026. NSE does not "
        "serve twenty years of history on request.",
    ),
    Source(
        "data/warehouse/prices/stock_data_inc",
        "prices",
        "72,530 price rows for 2026-07-09..2026-08-14, absent from the seed "
        "because it was frozen on 2026-07-08. Inside the study window.",
        is_increment=True,
    ),
    Source(
        "data/warehouse/fno",
        "fno",
        "105,422,837 F&O rows. The seed's fo_data/ skips _y=2017 through "
        "_y=2025 entirely; this is the only copy of those nine years.",
        is_increment=True,
    ),
)


@dataclass
class CarryReport:
    copied: int = 0
    skipped: int = 0
    bytes_copied: int = 0
    artefacts: dict[str, str] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems

    def render(self) -> str:
        lines = [
            f"  files copied : {self.copied:,}",
            f"  files skipped: {self.skipped:,}  (already present, hash matched)",
            f"  bytes copied : {self.bytes_copied / 1e9:.2f} GB",
        ]
        for name, digest in self.artefacts.items():
            lines.append(f"  artefact     : {name:<28} {digest[:16]}")
        lines.extend(f"  PROBLEM      : {p}" for p in self.problems)
        return "\n".join(lines)


def _copy_verified(src: Path, dest: Path) -> tuple[bool, int]:
    """Copy one file and prove it arrived intact. Returns (copied, bytes).

    Skips when the destination already holds identical content. Hashing both
    sides is slower than comparing sizes and would be wasteful — except that a
    truncated or half-written copy has a plausible size and the wrong bytes, and
    this data cannot be re-fetched if we get it wrong.
    """
    src_hash = hash_file(src)
    if dest.exists() and hash_file(dest) == src_hash:
        return False, 0

    dest.parent.mkdir(parents=True, exist_ok=True)
    # Write to a temp name and rename: an interrupted carry must never leave a
    # truncated file that a later run mistakes for a complete one.
    tmp = dest.with_suffix(dest.suffix + ".partial")
    shutil.copy2(src, tmp)
    if hash_file(tmp) != src_hash:
        tmp.unlink(missing_ok=True)
        raise SeedError(f"{src} did not survive the copy — hash mismatch at {dest}")
    tmp.rename(dest)
    return True, dest.stat().st_size


def carry(dry_run: bool = False, env: str | None = None) -> CarryReport:
    """Copy every source into this repo, verify it, and register it in the DAG."""
    report = CarryReport()
    pred = predecessor_root()
    if not pred.is_dir():
        raise SeedError(
            f"the predecessor repo is not at {pred}. Set PREDECESSOR_ROOT if it "
            f"lives elsewhere. Nothing can be carried without it, and the Phase 1 "
            f"gate is unreachable without the carry."
        )

    for source in SOURCES:
        src_root = source.source()
        if not src_root.is_dir():
            report.problems.append(f"missing source: {src_root}")
            continue

        dest_root = source.destination()
        files = sorted(p for p in src_root.rglob("*") if p.is_file())
        if not files:
            report.problems.append(f"no files under {src_root}")
            continue

        for f in files:
            rel = f.relative_to(src_root)
            if dry_run:
                report.skipped += 1
                continue
            copied, n = _copy_verified(f, dest_root / rel)
            if copied:
                report.copied += 1
                report.bytes_copied += n
            else:
                report.skipped += 1

        if dry_run:
            continue

        # Register the carried directory as ONE source artefact. A partitioned
        # dataset is one logical table, so it gets one content address; see
        # provenance.hash_dataset for why the combination is order-independent.
        digest = prov.register_dataset(
            dest_root,
            artefact_type="SOURCE",
            logical_name=f"seed:{source.logical_name}",
            produced_by=PRODUCED_BY,
            pattern="**/*",
            params={
                "carried_from": str(Path(source.src_rel)),
                "decision": "0027",
                "rationale": source.rationale,
                "n_files": len(files),
            },
            env=env,
        )
        report.artefacts[source.logical_name] = digest

    return report


def verify(env: str | None = None) -> CarryReport:
    """Re-hash what is on disk and check it against the DAG. Read-only.

    Verification NEVER writes — audit defect #3 was a `dev` verification that
    shelled out and rebuilt the prod warehouse. This function reads two things
    and compares them.
    """
    report = CarryReport()
    for source in SOURCES:
        dest = source.destination()
        if not dest.is_dir():
            report.problems.append(f"not carried: {dest}")
            continue
        try:
            digest, _ = prov.hash_dataset(dest, pattern="**/*")
        except prov.ProvenanceError as exc:
            report.problems.append(str(exc))
            continue
        report.artefacts[source.logical_name] = digest

        con_hashes = prov.lineage(digest, env=env)
        if not con_hashes:
            report.problems.append(
                f"{source.logical_name} hashes to {digest[:16]} which is NOT in the "
                f"provenance graph — the carried data does not match what was "
                f"registered, or was never registered."
            )
    return report


def main() -> int:
    import sys

    dry = "--dry-run" in sys.argv
    print(f"SEED CARRY (decision 0027){' — DRY RUN' if dry else ''}")
    print(f"  from: {predecessor_root()}")
    rep = carry(dry_run=dry)
    print(rep.render())
    if not rep.ok:
        print("\nSEED CARRY: FAILED")
        return 1
    print("\nSEED CARRY: GREEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
