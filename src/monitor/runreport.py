"""runreport.py — what THIS run just did, in one screen. Decision 0071.

THE QUESTION NOTHING ANSWERED. 0070 built two reports and neither covers a run:

  stage_alert.py  fires only on FAILURE, and names stages without detail.
  digest.py       is a daily standing state — "is anything rotting" — and reads
                  the log for the last few runs in two-line summaries.

Between them there was no answer to "the collector just ran; what did it get?"
A clean run produced NO output at all anywhere a person looks, which sounds
efficient and is the problem: an operator who only ever hears from a system
when it breaks cannot tell a healthy silence from a dead scheduler. Both of
this project's real losses looked exactly like silence.

WHY IT READS A TSV AND NOT THE LOG. digest.py parses `stage=code` lines out of
the collector's prose log, which works and is fragile — it already had to grow a
dedupe because a stage echoed twice read as two failures. The collector now
writes `logs/last_run.tsv` as a side effect of the same `note` call that prints
that line, so timing and exit codes arrive as data instead of being recovered
from formatting.

The manifest supplies the other half. Every archived fetch records `fetched_at`
in UTC, so "what did this run collect" is exactly "which manifest rows were
written after the run started" — no bookkeeping, no second source of truth.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from src.common.paths import ARCHIVE, LOGS
from src.monitor import backup_state, health
#: Imported rather than re-derived: these are the stages whose failure costs
#: data instead of costing a retry, and two lists that must agree would not.
from src.monitor.stage_alert import COLLECTION_STAGES

RUN_TSV = LOGS / "last_run.tsv"
IST = ZoneInfo("Asia/Kolkata")

#: Statuses that mean the bytes are on disk. EMPTY_DAY is a holiday or a quiet
#: window that was positively confirmed, which is a RESULT, not a miss — 0066
#: made empty days dated precisely so they stop reading as gaps.
HELD = {"STORED", "DUPLICATE", "EMPTY_DAY"}


@dataclass(frozen=True)
class Stage:
    name: str
    code: int
    seconds: int

    @property
    def ok(self) -> bool:
        return self.code == 0


@dataclass(frozen=True)
class Run:
    started: datetime | None
    stages: list[Stage]

    @property
    def failed(self) -> list[Stage]:
        return [s for s in self.stages if not s.ok]

    @property
    def elapsed(self) -> int:
        return sum(s.seconds for s in self.stages)


def read_run(path: Path | None = None) -> Run:
    """Parse the collector's per-stage record. Tolerates a truncated file.

    RESOLVED AT CALL TIME, NOT IN THE SIGNATURE. `path: Path = RUN_TSV` binds
    the constant when the module is imported, so the module-level name stops
    being the single source of truth the moment anything reassigns it — and the
    first thing to notice was a test that pointed RUN_TSV at a fixture and got
    the real file back.

    A run that DIED mid-stage leaves a partial TSV, and that partial file is the
    most valuable one there is — it names the stage that never returned. Parsing
    strictly and raising would throw it away.
    """
    path = path or RUN_TSV
    if not path.exists():
        return Run(None, [])
    started: datetime | None = None
    stages: list[Stage] = []
    for line in path.read_text(errors="ignore").splitlines():
        if line.startswith("# started "):
            try:
                started = datetime.fromisoformat(line[len("# started "):].strip())
            except ValueError:
                started = None
            continue
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        try:
            stages.append(Stage(parts[0], int(parts[1]), int(parts[2])))
        except ValueError:
            continue
    return Run(started, stages)


def collected_since(since: datetime | None) -> list[dict]:
    """Manifest rows written after `since`. Empty list when `since` is None —
    "everything ever archived" is not a useful answer to "what did this run do"."""
    man = ARCHIVE / "manifest.jsonl"
    if since is None or not man.exists():
        return []
    out = []
    for line in man.read_text(errors="ignore").splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
            at = datetime.fromisoformat(r["fetched_at"])
        except (json.JSONDecodeError, KeyError, ValueError):
            continue
        if at >= since:
            out.append(r)
    return out


def _hms(seconds: int) -> str:
    m, s = divmod(max(seconds, 0), 60)
    return f"{m}m {s:02d}s" if m else f"{s}s"


def _size(n: int) -> str:
    if n >= 1_048_576:
        return f"{n / 1_048_576:.1f} MB"
    return f"{n / 1024:.0f} KB" if n >= 1024 else f"{n} B"


def render(run: Run | None = None) -> str:
    run = run if run is not None else read_run()
    when = (run.started.astimezone(IST).strftime("%Y-%m-%d %H:%M IST")
            if run.started else "unknown start")
    out: list[str] = []

    if not run.stages:
        return (f"COLLECT RUN — {when}\n\n"
                "  No stage record found. The run died before its first stage,\n"
                f"  or {RUN_TSV.name} was never written. Check logs/launchd_collect.err.")

    bad = run.failed
    verdict = "ALL CLEAN" if not bad else f"FAILED — {len(bad)} stage(s)"
    out += [f"COLLECT RUN — {when}",
            f"  {verdict}   {len(run.stages)} stages in {_hms(run.elapsed)}", ""]

    if bad:
        # The distinction that decides whether the operator acts NOW or later,
        # stated before the detail rather than after it.
        lost = [s.name for s in bad if s.name in COLLECTION_STAGES]
        proc = [s.name for s in bad if s.name not in COLLECTION_STAGES]
        if lost:
            out += [f"  COLLECTION FAILED: {', '.join(lost)}",
                    "    Rolling NSE feeds are recoverable only until the file",
                    "    turns over (~19:00 IST next session). Re-run: /collect", ""]
        if proc:
            out += [f"  PROCESSING FAILED: {', '.join(proc)}",
                    "    Bytes are on disk; the next run retries. Act if it repeats.", ""]

    out.append("STAGES")
    for s in run.stages:
        mark = "ok  " if s.ok else "FAIL"
        code = "" if s.ok else f"  exit {s.code}"
        out.append(f"  {mark}  {s.name:<16}{_hms(s.seconds):>8}{code}")
    out.append("")

    out.append("COLLECTED THIS RUN")
    rows = collected_since(run.started)
    if not rows:
        out.append("  nothing new — every feed already held what it served")
    else:
        by_source: dict[str, list[dict]] = {}
        for r in rows:
            by_source.setdefault(r.get("source_id", "?"), []).append(r)
        for sid, rs in sorted(by_source.items()):
            held = [r for r in rs if r.get("status") in HELD]
            new = [r for r in held if r.get("status") == "STORED"]
            failed = [r for r in rs if r.get("status") == "FAILED"]
            bits = []
            if new:
                bits.append(f"{len(new)} NEW ({_size(sum(r.get('bytes', 0) for r in new))})")
            if len(held) - len(new):
                bits.append(f"{len(held) - len(new)} already held")
            if failed:
                bits.append(f"{len(failed)} FAILED")
            out.append(f"  {sid:<22} {', '.join(bits) or 'no result'}")
            # The error text, not just the count. A FAILED row whose reason is
            # "EMPTY ENVELOPE" is a different morning from one whose reason is
            # a DNS failure, and the count alone cannot tell them apart.
            for r in failed[:2]:
                out.append(f"    ! {str(r.get('error', 'no reason recorded'))[:96]}")
    out.append("")

    out.append("STALENESS NOW")
    try:
        for r in health.read():
            last = r.last_session.isoformat() if r.last_session else "never"
            extra = f", {len(r.open_gaps)} MISSING" if r.open_gaps else ""
            mark = "STALE " if r.alerting else "ok    "
            out.append(f"  {mark}{r.source_id:<22} last {last}"
                       f"  {r.sessions_stale} session(s) stale{extra}")
    except Exception as exc:  # noqa: BLE001 - one broken section must not kill the report
        out.append(f"  unavailable: {type(exc).__name__}")
    try:
        b = backup_state.read()
        flag = 'AT RISK' if b.alerting else 'ok    '
        out.append(f"  {flag:<6}{'backup':<22} {b.summary}")
    except Exception as exc:  # noqa: BLE001
        out.append(f"  backup unavailable: {type(exc).__name__}")

    out += ["", "/digest for standing state   /help for commands"]
    return "\n".join(out)


def main() -> int:
    import sys

    text = render()
    print(text)
    if "--telegram" in sys.argv:
        from src.monitor import telegram
        # ONLY on failure when asked to be quiet. A per-run message is welcome;
        # two a day forever is how a channel gets muted, and a muted channel is
        # the email leg again.
        if "--only-if-failed" in sys.argv and not read_run().failed:
            print("  telegram: clean run, suppressed (--only-if-failed)")
            return 0
        print("  " + telegram.send(text))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
