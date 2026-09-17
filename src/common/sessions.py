"""sessions.py — which session NSE's rolling endpoints are serving RIGHT NOW.

THE QUESTION THIS ANSWERS, AND WHO WAS ANSWERING IT WRONG.

On 2026-09-17 at 08:37 IST the deal fetch failed on a DNS error. Three things
then told the operator, on three channels, that data was at risk:

  stopgap.py     "This session's bytes may be permanently lost. Investigate today."
  stage_alert    "COLLECTION: ... recoverable only until the file turns over ... Re-run now"
  runreport      "COLLECTION FAILED: exit ... Re-run: /collect"

Nothing was at risk. At 08:37 the endpoint was serving the 2026-09-16 file —
NSE does not publish a session's deals until ~19:00 IST that evening — and
2026-09-16 was already held from the previous night's run. The morning slot
exists to CATCH UP a missed evening; on a morning after a clean evening it
fetches a duplicate, and a failed duplicate fetch loses nothing.

health.py made the same error in a quieter way: it counted sessions stale up to
TODAY, so every source read "1 session(s) stale" every morning of every
trading day, for a session whose file did not yet exist.

The fix is one shared answer to "what should the endpoint be serving now",
used by all four. It is a stdlib approximation on purpose: the observed
calendar in `src/common/calendar.py` is DuckDB-backed and ends at the last
price held, which is always BEFORE the sessions this question is about.

THE APPROXIMATION, STATED. A session's rolling file is expected from
PUBLISH_HOUR_IST on its own date; before that hour the endpoint serves the
previous session. Weekends are skipped; holidays are not known ahead and are
treated as trading days, which over-expects by one session on a holiday
evening. That is the direction health.py already accepts (see
`_weekday_sessions_between`): it can produce a spurious "1 stale" for one
evening, never a hidden loss.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

#: NSE publishes bulk/block deals and the FII/DII figure around 19:00 IST.
#: Decision 0060 set the evening collection slot at 20:30 for exactly this
#: reason; the hour below is when "today's file should exist" becomes true.
PUBLISH_HOUR_IST = 20


def previous_weekday(d: date) -> date:
    d -= timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def expected_session(now: datetime | None = None) -> date:
    """The session whose file the rolling endpoints should be serving now.

    Before PUBLISH_HOUR_IST on a weekday: the previous weekday's session.
    From PUBLISH_HOUR_IST on a weekday: today's.
    On a weekend: the Friday's.
    """
    now = (now or datetime.now(UTC)).astimezone(IST)
    today = now.date()
    if today.weekday() >= 5 or now.hour < PUBLISH_HOUR_IST:
        return previous_weekday(today)
    return today


def exposure(newest_held: date | None, now: datetime | None = None) -> tuple[bool, str]:
    """(at_risk, sentence) for one rolling source.

    A source whose newest held session is at or past the expected one has
    nothing on the endpoint it does not already hold. One behind is at risk
    and still recoverable — the endpoint serves the expected session until the
    next one publishes. Two or more behind means the older ones are already
    gone; only the newest is still on the endpoint.
    """
    exp = expected_session(now)
    if newest_held is None:
        return True, f"nothing held yet; the endpoint is serving {exp} — fetch now"
    if newest_held >= exp:
        return False, (f"newest held {newest_held} is what the endpoint is serving; "
                       f"nothing at risk, the next slot retries")
    return True, (f"newest held {newest_held}; the endpoint is serving {exp}, which is "
                  f"NOT held — recoverable until the next session publishes "
                  f"(~{PUBLISH_HOUR_IST - 1}:00 IST). Fetch now")
