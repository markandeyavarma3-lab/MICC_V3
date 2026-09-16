"""stage_alert.py — tell somebody a STAGE failed. Decision 0070.

WHY THIS EXISTS AND WHY IT IS LATE.

`health.py` answers "is the DATA stale?" It has answered it well: every gap in
the archive since 2026-09-03 has been reported. It does not answer "did the
PIPELINE run?", and nothing else did either.

The cost, measured: `src.research.charmatch` raised a foreign-key error on every
scheduled run from 2026-09-11 to 2026-09-16. Twenty consecutive failures. The
only signal was one line — "COLLECT: one or more stages FAILED" — written to
`logs/launchd_collect.err`, a file with no reader. The characteristic panel that
0055 had just unfrozen refroze, and CHAR_MATCHED quality degraded for five days
while the collector reported success on every feed it fetched.

The mart's foreign-key failure before it ran the same way for five days, and
767 collected deals never reached it.

Both were LOUD in a log and SILENT everywhere a person looks. That is this
project's standing pattern — the signal existed and nothing carried it — and the
fix is the same each time: carry it to where somebody is.

WHAT THIS DELIBERATELY DOES NOT DO. It does not add a channel. It reuses
`health.notify_desktop` and `health.notify_email`, which are already configured,
already tested, and already fail soft when credentials are absent. A second
notification path would be a second thing to configure and a second thing to go
quietly missing.
"""

from __future__ import annotations

from src.monitor import health

#: Stages whose failure means data was not collected, as opposed to data that
#: was collected but not processed. Both matter; this one is worse, because the
#: three rolling NSE feeds cannot be re-fetched after the file turns over.
COLLECTION_STAGES = frozenset({
    "exit", "prices", "bhavcopy", "corpact", "derivatives", "insider",
})


def compose(stages: list[str], log: str) -> str:
    """The message. Empty string when nothing failed — an alert that fires on
    success is an alert that gets filtered."""
    if not stages:
        return ""
    lost = sorted(s for s in stages if s in COLLECTION_STAGES)
    other = sorted(s for s in stages if s not in COLLECTION_STAGES)
    lines = [f"{len(stages)} stage(s) failed: {', '.join(sorted(stages))}", ""]
    if lost:
        lines += [
            f"COLLECTION: {', '.join(lost)}",
            "  Data may not have been fetched. nse_bulk_deals, nse_block_deals",
            "  and fii_dii_cash are ROLLING endpoints — a session missed here is",
            "  recoverable only until the file turns over, around 19:00 IST the",
            "  next trading day. Re-run now if this was the evening slot:",
            "    cd ~/Workspace/institutional-research && ./scripts/collect_daily.sh",
            "",
        ]
    if other:
        lines += [
            f"PROCESSING: {', '.join(other)}",
            "  Data was fetched but a downstream stage did not finish. Nothing is",
            "  lost; the next run retries. If it repeats, the stage is broken —",
            "  charpanel failed twenty times in a row in September before anyone",
            "  looked.",
            "",
        ]
    lines.append(f"Log: {log}")
    return "\n".join(lines)


def send(stages: list[str], log: str) -> str:
    """Alert on failed stages. NEVER RAISES.

    This runs as the last act of a collector that has already failed. An
    exception here would replace a useful message with a stack trace in a file
    nobody reads, which is the failure it exists to prevent.
    """
    body = compose(stages, log)
    if not body:
        return "clean run; nothing sent"
    subject = f"institutional-research: {len(stages)} stage(s) FAILED"
    out = []
    for name, fn, args in (("desktop", health.notify_desktop, (subject, body)),
                           ("email", health.notify_email, (subject, body))):
        try:
            out.append(f"{name}={fn(*args)}")
        except Exception as exc:  # noqa: BLE001 - the message is the deliverable
            out.append(f"{name}=ERROR {type(exc).__name__}")
    return "; ".join(out)


def main() -> int:
    import sys

    if len(sys.argv) < 2:
        print("usage: stage_alert.py <log-path> <stage> [stage ...]")
        return 2
    log, stages = sys.argv[1], [s for s in sys.argv[2:] if s]
    print(f"  stage alert: {send(stages, log)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
