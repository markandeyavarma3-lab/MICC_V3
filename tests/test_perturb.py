"""The perturbation harness itself, which had no tests until it was wrong.

`scripts/perturb.py` exists because this project found five green-and-empty
tests in three days: tests that passed with the rule they pinned removed. The
harness answers "would this test notice?" — so a harness that answers "no"
when the truth is "yes, loudly" is the same defect one level up, and on
2026-09-19 it did exactly that on the first real use after it was written.

Run as a SUBPROCESS, not imported: the thing being tested is the script's
verdict and exit code, and the script edits a file on disk and restores it.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

PERTURB = Path(__file__).resolve().parents[1] / "scripts" / "perturb.py"


def _run(target: Path, test_file: Path, anchor: str, replacement: str):
    return subprocess.run(
        [sys.executable, str(PERTURB), str(target), str(test_file), "--", anchor, replacement, "lbl"],
        capture_output=True, text=True, cwd=str(test_file.parent))


def _module(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "subject.py"
    p.write_text(body)
    return p


def test_a_test_that_fails_under_the_perturbation_is_reported_as_a_bite(tmp_path):
    target = _module(tmp_path, "def answer():\n    return 42\n")
    t = tmp_path / "test_subject.py"
    t.write_text("from subject import answer\n\n\ndef test_it():\n    assert answer() == 42\n")
    r = _run(target, t, "return 42", "return 43")
    assert r.returncode == 0
    assert "bites:" in r.stdout
    assert target.read_text() == "def answer():\n    return 42\n", "the file must be restored"


def test_a_fixture_that_raises_is_a_bite_and_not_a_silent_pass(tmp_path):
    """THE BUG THIS FILE WAS WRITTEN FOR. pytest prints "ERROR" — not
    "FAILED" — when a test cannot run at all, which is what happens when a
    module-scoped fixture raises under the perturbation. Every test in the
    file errors, the suite is as red as it gets, and the harness used to read
    only "FAILED " lines and report that the rule was unpinned.

    Found on the benchmark panel: removing NIFTY500_TR from `build()` made the
    fixture raise BenchmarkError and perturb said "NOTHING FAILED"."""
    target = _module(tmp_path, "def build():\n    return ['a', 'b']\n")
    t = tmp_path / "test_subject.py"
    t.write_text(
        "import pytest\nfrom subject import build\n\n\n"
        "@pytest.fixture(scope='module')\n"
        "def panel():\n"
        "    out = build()\n"
        "    if len(out) != 2:\n"
        "        raise RuntimeError('a panel that drops a series silently is the bug')\n"
        "    return out\n\n\n"
        "def test_one(panel):\n    assert panel[0] == 'a'\n\n\n"
        "def test_two(panel):\n    assert panel[1] == 'b'\n")
    r = _run(target, t, "['a', 'b']", "['a']")
    assert r.returncode == 0, f"a raising fixture must count as a bite:\n{r.stdout}"
    assert "(error)" in r.stdout, "an ERROR bite should say so, not masquerade as a failure"


def test_a_rule_nothing_pins_is_reported_as_unpinned(tmp_path):
    """The verdict that makes the harness worth running: green under the
    perturbation, exit 1, said plainly."""
    target = _module(tmp_path, "def answer():\n    return 42\n")
    t = tmp_path / "test_subject.py"
    t.write_text("from subject import answer\n\n\ndef test_it():\n    assert answer() > 0\n")
    r = _run(target, t, "return 42", "return 43")
    assert r.returncode == 1
    assert "NOTHING FAILED" in r.stdout


def test_a_missing_anchor_refuses_rather_than_reading_as_green(tmp_path):
    """A mis-typed anchor changes nothing, so every test passes, so the run
    looks exactly like a rule nothing pins. Two of those on 2026-09-18 are why
    the script replaced the shell helper."""
    target = _module(tmp_path, "def answer():\n    return 42\n")
    t = tmp_path / "test_subject.py"
    t.write_text("def test_it():\n    assert True\n")
    r = _run(target, t, "return 4200", "return 43")
    assert r.returncode == 2
    assert target.read_text() == "def answer():\n    return 42\n"
