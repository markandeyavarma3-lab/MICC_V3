"""calendar.py — the trading calendar, OBSERVED and never generated. Phase 1.4.

WHY GENERATED CALENDARS ARE WRONG HERE. "Weekdays minus a holiday list" is the
obvious construction and it is wrong in both directions for this market: NSE has
traded on Saturdays for muhurat and special sessions, and has closed unexpectedly
for exchange outages and national events that no static list carries. A horizon
measured in "trading sessions" against a generated calendar silently means a
different amount of market activity in different years.

So the calendar is the set of dates on which trading was actually OBSERVED in the
price spine. It cannot drift from the data because it IS the data.

WHY IT ARRIVES LATE, AND WHAT WAS BEING USED INSTEAD. Step 1.4 has been open
since 2026-08-16 and was reported complete on the strength of the reconciliation
gate matching 5,339 sessions. That number came from `COUNT(DISTINCT date)` on the
spine — which is the right answer to the gate's question and is not a calendar.
Nothing could ask "what is the next session after 2026-07-08?" until now, which
is why the clean mart could not compute an entry date.
"""

from __future__ import annotations

import bisect
from datetime import date
from functools import lru_cache

import duckdb

from src.common.paths import warehouse_dir


class CalendarError(RuntimeError):
    """The calendar cannot be built, or was asked something it cannot answer."""


@lru_cache(maxsize=2)
def sessions(env: str | None = None) -> tuple[date, ...]:
    """Every observed trading session, ascending.

    Read from the ADJUSTED spine: it is the series research uses, so the calendar
    and the returns cannot disagree about which days exist.
    """
    glob = str(warehouse_dir(env) / "price_spine_adj" / "**" / "*.parquet")
    con = duckdb.connect()
    try:
        rows = con.execute(
            f"SELECT DISTINCT CAST(date AS DATE) d FROM read_parquet('{glob}') ORDER BY d"
        ).fetchall()
    finally:
        con.close()
    if not rows:
        raise CalendarError(
            "no sessions found. Build the spine first: python -m src.warehouse.spine"
        )
    return tuple(r[0] for r in rows)


def is_session(d: date, env: str | None = None) -> bool:
    s = sessions(env)
    i = bisect.bisect_left(s, d)
    return i < len(s) and s[i] == d


def next_session(d: date, env: str | None = None) -> date | None:
    """The first session STRICTLY after `d`, or None past the end of the data.

    None rather than an extrapolated date. A deal disclosed after the last
    session we hold has no observable entry, and inventing one would fabricate
    the single most important field in the study.
    """
    s = sessions(env)
    i = bisect.bisect_right(s, d)
    return s[i] if i < len(s) else None


def session_offset(d: date, n: int, env: str | None = None) -> date | None:
    """`n` sessions after the first session on or after `d`. None if past the end.

    Horizons are counted in sessions from the calendar, never by calendar-day
    arithmetic — `configs/research.yml` timing.horizon_unit.
    """
    s = sessions(env)
    i = bisect.bisect_left(s, d)
    j = i + n
    return s[j] if 0 <= j < len(s) else None


def count_between(start: date, end: date, env: str | None = None) -> int:
    """Sessions in [start, end]. Used to check horizons against real activity."""
    s = sessions(env)
    return bisect.bisect_right(s, end) - bisect.bisect_left(s, start)


def main() -> int:
    s = sessions()
    print("TRADING CALENDAR — observed, never generated")
    print(f"  sessions   {len(s):>7,}")
    print(f"  span       {s[0]} .. {s[-1]}")
    print(f"  gate       5,339 expected   {'MATCH' if len(s) == 5339 else 'MISMATCH'}")
    weekend = [d for d in s if d.weekday() >= 5]
    print(f"  weekend sessions {len(weekend):>3}  "
          f"<- a generated weekday calendar would have missed these")
    if weekend:
        print("    " + ", ".join(str(d) for d in weekend[:5])
              + (" ..." if len(weekend) > 5 else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
