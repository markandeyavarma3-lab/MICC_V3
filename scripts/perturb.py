"""perturb.py — prove a test can fail by breaking the rule it pins.

    python scripts/perturb.py <file> <tests...> -- <anchor> <replacement> [label]

Replaces `anchor` with `replacement` in `file`, runs the tests, restores the
file from a byte-exact backup, and reports which tests FAILED under the
perturbation. A test that stays green while its rule is removed proves
nothing, and this project has found that shape in its own suite five times
in three days (0071, 0073, 0074, exp_004): tests that were green and empty.

WHY A SCRIPT AND NOT THE SHELL FUNCTION IT REPLACES. The ad-hoc helper
asserted the anchor existed, raised into a traceback, and the pipeline
grepped only "FAILED" lines — so a MISSING anchor read as "no failures", i.e.
as a perturbation that passed. On 2026-09-18 that happened once with a stale
backup and once with a mis-typed anchor, and both looked like tests that
could not fail. This script:

  - refuses (exit 2) if the anchor is absent or matches more than once;
  - takes its backup AFTER the anchor check, and restores it in a finally;
  - exits 0 only if at least one test FAILED under the perturbation, 1 if
    every test stayed green — so a CI step can require the perturbation to
    bite.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def main(argv: list[str]) -> int:
    if "--" not in argv or len(argv) < 5:
        print(__doc__)
        return 2
    i = argv.index("--")
    file, tests = Path(argv[0]), argv[1:i]
    anchor, replacement = argv[i + 1], argv[i + 2]
    label = argv[i + 3] if len(argv) > i + 3 else replacement[:40]
    if not file.exists() or not tests:
        print(f"perturb: no such file {file} or no tests given"); return 2
    text = file.read_text()
    n = text.count(anchor)
    if n != 1:
        print(f"perturb: REFUSED — anchor matches {n} time(s) in {file}, must be exactly 1:\n  {anchor[:120]!r}")
        return 2
    backup = Path(tempfile.mkdtemp()) / file.name
    shutil.copy2(file, backup)
    try:
        file.write_text(text.replace(anchor, replacement))
        env = {**os.environ, "RESEARCH_ENV": os.environ.get("RESEARCH_ENV", "dev")}
        r = subprocess.run([sys.executable, "-m", "pytest", *tests, "-q", "-p", "no:cacheprovider"],
                           capture_output=True, text=True, env=env)
        failed = [ln.split(" - ")[0].removeprefix("FAILED ") for ln in r.stdout.splitlines() if ln.startswith("FAILED ")]
    finally:
        shutil.copy2(backup, file)
        restored = file.read_bytes() == backup.read_bytes()
    if not restored:
        print("perturb: RESTORE FAILED — file differs from backup")
        return 2
    print(f"--- {label}")
    if failed:
        for f in failed:
            print(f"    bites: {f}")
        return 0
    print("    NOTHING FAILED — the tests do not pin this rule")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
