"""publication.py — when was a disclosure actually observable? Plan 1 §7.1.

**`available_from` is the field the whole study rests on**, and until now nothing
in this project or its predecessor had ever measured it.

WHY IT DECIDES EVERYTHING. An event study measures what happened *after*
information became public. Assume publication is earlier than it was and the
study trades on information nobody had — a look-ahead that manufactures an effect
out of nothing. Assume it is later and real signal is discarded. Plan 1 §7.1 is
explicit that this is *"established empirically by recording the observed
publication time of each report over several weeks — never assumed"*, and
`sources.yml` carries `publish_time_ist: "~19:00"` with
`publish_time_verified: false` against every source.

HOW THE STOPGAP MAKES IT MEASURABLE, BY ACCIDENT OF A GOOD DESIGN.

The collector polls three times a session and dedupes on SHA-256, so the manifest
records not only when a session's file first appeared but also **every earlier
poll that asked and got something else**. That brackets publication:

    last poll returning a DIFFERENT session   <  publication  <=  first poll returning THIS session

Both ends are observations, not assumptions. The interval is only as tight as the
polling schedule — currently 20:00, 22:30 and 08:00 IST, so a session first seen
at 22:30 is bounded to a two-and-a-half-hour window.

WHAT THIS CAN AND CANNOT ESTABLISH. It measures publication **going forward
only**. For the 2006-2026 history no equivalent record exists and none can be
reconstructed, so those rows keep the conservative bound — entry at the next
session's open — and carry `confidence='LOW'`. This is a gap that closes at one
session per day and never retroactively.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from src.common.paths import ARCHIVE

#: NSE publishes on IST and the manifest records UTC.
IST = timedelta(hours=5, minutes=30)

MANIFEST = ARCHIVE / "manifest.jsonl"


@dataclass(frozen=True, slots=True)
class Bound:
    """An observed bracket on one session's publication time."""

    source_id: str
    session_date: str
    #: Latest poll that asked and got a DIFFERENT session. None if the very first
    #: poll for this source already carried it, which leaves publication unbounded
    #: below and is honestly reported as such.
    last_absent_ist: datetime | None
    #: Earliest poll that returned this session.
    first_present_ist: datetime

    @property
    def is_bounded(self) -> bool:
        return self.last_absent_ist is not None

    @property
    def width_hours(self) -> float | None:
        if self.last_absent_ist is None:
            return None
        return (self.first_present_ist - self.last_absent_ist).total_seconds() / 3600

    def render(self) -> str:
        seen = self.first_present_ist.strftime("%d %b %H:%M")
        if not self.is_bounded:
            return (f"  {self.session_date}  {self.source_id:<16} "
                    f"<= {seen} IST   (unbounded below: no earlier poll)")
        after = self.last_absent_ist.strftime("%d %b %H:%M")  # type: ignore[union-attr]
        return (f"  {self.session_date}  {self.source_id:<16} "
                f"({after}, {seen}] IST   window {self.width_hours:.1f}h")


def _read_manifest(path: Path | None = None) -> list[dict]:
    p = path or MANIFEST
    if not p.exists():
        return []
    out = []
    for line in p.read_text().splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


def _ist(raw: str) -> datetime:
    return datetime.fromisoformat(raw).astimezone(UTC) + IST


def bounds(path: Path | None = None) -> list[Bound]:
    """Bracket publication time for every session the archive has observed.

    Only polls that actually reached the source count. A FAILED fetch tells us
    nothing about whether the file existed — treating it as evidence of absence
    would bias every bound earlier, which is the dangerous direction.
    """
    records = [r for r in _read_manifest(path)
               if r.get("status") in {"STORED", "DUPLICATE", "EMPTY_DAY"}
               and r.get("session_date") and r.get("fetched_at")]

    by_source: dict[str, list[dict]] = {}
    for r in records:
        by_source.setdefault(r["source_id"], []).append(r)

    out: list[Bound] = []
    for source_id, rows in by_source.items():
        rows.sort(key=lambda r: r["fetched_at"])
        for session in sorted({r["session_date"] for r in rows}):
            present = [r for r in rows if r["session_date"] == session]
            first = _ist(present[0]["fetched_at"])
            # The latest poll BEFORE that which returned a different session.
            earlier_other = [
                _ist(r["fetched_at"]) for r in rows
                if r["session_date"] != session and _ist(r["fetched_at"]) < first
            ]
            out.append(Bound(source_id, session,
                             max(earlier_other) if earlier_other else None, first))
    return sorted(out, key=lambda b: (b.session_date, b.source_id))


def summary(bs: list[Bound]) -> dict:
    bounded = [b for b in bs if b.is_bounded]
    return {
        "sessions_observed": len(bs),
        "bounded": len(bs and bounded),
        "tightest_hours": min((b.width_hours for b in bounded), default=None),
        "latest_observation_ist": max((b.first_present_ist for b in bs), default=None),
        "earliest_upper_bound_hour": min(
            (b.first_present_ist.hour + b.first_present_ist.minute / 60 for b in bs),
            default=None),
    }


def main() -> int:
    bs = bounds()
    print("PUBLICATION TIME — measured, not assumed (Plan 1 §7.1)")
    print("  sources.yml currently asserts ~19:00 IST with publish_time_verified: false\n")
    if not bs:
        print("  no observations yet — the collector must run across a session boundary")
        return 0
    for b in bs:
        print(b.render())

    s = summary(bs)
    print(f"\n  sessions observed : {s['sessions_observed']}")
    print(f"  with a lower bound: {s['bounded']}")
    if s["tightest_hours"] is not None:
        print(f"  tightest bracket  : {s['tightest_hours']:.1f} hours")
    if s["earliest_upper_bound_hour"] is not None:
        h = s["earliest_upper_bound_hour"]
        print(f"  earliest confirmed observation: {int(h):02d}:{int((h % 1) * 60):02d} IST")
    print("\n  NOT YET SUFFICIENT to set available_from. The bracket is only as tight")
    print("  as the polling schedule, and history before 2026-08-17 has no record at")
    print("  all — those rows keep the conservative bound and confidence='LOW'.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
