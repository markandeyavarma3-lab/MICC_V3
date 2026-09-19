"""index_tri.py — the NIFTY 500 total-return index, daily, from niftyindices.

WHY THIS EXISTS. benchmarks.yml names NIFTY500_TR as the headline market leg
and points it at a warehouse table that has never existed; the seed carries
only the PRICE index. The route was found on 2026-09-15 (`probe.py`, decision
in sources.yml: "the benchmark hole, now filled at the byte level") and 32
annual slices were archived by hand, 1995-01-01 to 2026-09-10 — and then
nothing, because a probe is not a collector. A series that stops the day it
was probed drifts one session further from usable every evening.

WHAT IT FETCHES. One POST per run for a window ending today. The window is
45 days on purpose: it overlaps the previous run by six weeks, so a fortnight
of missed evenings costs nothing, and the parser keeps one row per date
whichever slice served it. The route accepts at most one year per request;
`--start/--end` chunk a backfill into year-long windows, which is how the 32
slices were made and how they would be remade.

WHAT IT DOES NOT DO. No parsing here. The bytes land as served, the manifest
records the exact window asked for (`request_startDate`/`request_endDate`),
and `src/ingest/index_tri.py` reads them. An empty list for a window is
recorded as FAILED with the reason, not as an empty day: this host returns
[] for a window it does not serve (pre-1995), and a [] on a window that
should have 30 sessions is a change on the host, not a holiday.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.archive import probe  # noqa: E402

SOURCE_ID = "nifty500_tri"
EXCHANGE = "NSE"
REPORT_TYPE = "INDEX_TRI"
INDEX_NAME = "NIFTY 500"
URL = "https://www.niftyindices.com/BackPage/getTotalReturnIndexString"
HEADERS = {
    "Origin": "https://www.niftyindices.com",
    "Referer": "https://www.niftyindices.com/reports/historical-data",
    "X-Requested-With": "XMLHttpRequest",
    "Content-Type": "application/json; charset=UTF-8",
    "Accept": "application/json, text/javascript, */*; q=0.01",
}
#: The host serves at most one year per request; a longer window answers [].
MAX_WINDOW_DAYS = 365
#: The daily top-up window. Six weeks of overlap with the previous run.
TOPUP_DAYS = 45
#: The first session the host serves. Earlier windows return [] (probed
#: 2026-09-15: base 1000.0 on 1995-01-01).
EARLIEST = date(1995, 1, 1)


def _fmt(d: date) -> str:
    """'22-Sep-1995' — the host's own date form, month capitalised."""
    return d.strftime("%d-%b-%Y")


def body_for(start: date, end: date, index: str = INDEX_NAME) -> bytes:
    """The POST body. `cinfo` is a STRING holding a JS-object literal with
    single quotes — not nested JSON. The host parses it that way and answers
    [] to anything else, with a 200."""
    cinfo = (f"{{'name':'{index}','startDate':'{_fmt(start)}',"
             f"'endDate':'{_fmt(end)}','indexName':'{index}'}}")
    return json.dumps({"cinfo": cinfo}).encode()


def windows(start: date, end: date) -> list[tuple[date, date]]:
    """[start, end] cut into windows of at most MAX_WINDOW_DAYS, oldest first."""
    if end < start:
        return []
    out: list[tuple[date, date]] = []
    lo = start
    while lo <= end:
        hi = min(lo + timedelta(days=MAX_WINDOW_DAYS - 1), end)
        out.append((lo, hi))
        lo = hi + timedelta(days=1)
    return out


def fetch_window(start: date, end: date, dry_run: bool = False) -> dict:
    """One request, one manifest row. The session date is the window's END:
    the file is a slice ending there, and that is what the parser dedupes on."""
    return probe.probe(
        source_id=SOURCE_ID, exchange=EXCHANGE, report_type=REPORT_TYPE, url=URL,
        session=end, validate=probe.json_nonempty_list(min_items=1), suffix=".json.gz",
        headers=HEADERS, data=body_for(start, end), dry_run=dry_run,
        extra={"request": "POST cinfo", "request_startDate": _fmt(start),
               "request_endDate": _fmt(end)},
    )


def collect(start: date | None = None, end: date | None = None,
            today: date | None = None, dry_run: bool = False) -> list[dict]:
    today = today or date.today()
    end = end or today
    start = start or (end - timedelta(days=TOPUP_DAYS))
    start = max(start, EARLIEST)
    out = []
    for lo, hi in windows(start, end):
        out.append(fetch_window(lo, hi, dry_run=dry_run))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--start", type=date.fromisoformat, default=None,
                    help="backfill from this date (chunked a year at a time)")
    ap.add_argument("--end", type=date.fromisoformat, default=None)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    results = collect(a.start, a.end, dry_run=a.dry_run)
    failed = 0
    for r in results:
        mark = r["status"]
        detail = r.get("error", "") if mark == "FAILED" else f"{r.get('bytes', 0):,} B"
        print(f"  {mark:<9} {r['request_startDate']} -> {r['request_endDate']}  {detail}")
        failed += mark == "FAILED"
    print(f"INDEX TRI: {len(results)} window(s), {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
