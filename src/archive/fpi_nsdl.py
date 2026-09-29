"""fpi_nsdl.py — daily FPI flows from NSDL, back to December 1998.

WHY THIS SOURCE. The only FII/DII cash series this project had was NSE's
`fiidiiTradeReact`, which serves today's figure and nothing else: 68 rows
inherited from V1 (June-July 2026) and whatever was collected since August.
NSDL — the depository that holds FPI securities — publishes its own series
("Daily Trends in FPI Investments") on the FPI Monitor site, and its archive
page serves ANY past month on request. Probed 2026-09-29: the first reporting
date is 31-Dec-1998, and every month from January 1999 answers.

WHAT ONE REQUEST RETURNS. The archive is an ASP.NET form: a date goes into
the hidden field `hdnDate` and the page posts back (`__doPostBack('btnSubmit1')`)
with every reporting day of that date's month up to the date. Two tables:

  1. investment  — per day and per category (Equity, the Debt limits, Hybrid,
     Mutual Funds, AIFs; 1999-2009 only Equity and Debt), split by route
     (stock exchange / primary market & others / sub-total from ~2009), with
     gross purchases, gross sales and net investment in Rs crore and US$
     million, and the day's exchange rate.
  2. derivatives — per day and product (index/stock futures and options, later
     interest-rate, currency and commodity): contracts and value bought, sold,
     and open interest at the end of the day.

The page, not a parse of it, is archived: raw bytes first, as everywhere in
this project, so the parser can be rewritten against what NSDL actually
served. `src/ingest/fpi_nsdl.py` reads them.

POINT IN TIME — READ BEFORE USING THIS IN A STUDY. NSDL's "reporting date" is
the day custodians REPORT the trades, which the page's own note says is the
day after the stock exchanges' provisional T-day figure. A flow reported on D
was not public before D, and describes trading on or before D-1. A study must
enter no earlier than the session after the reporting date.

ROBOTS. fpi.nsdl.co.in serves no robots.txt (it redirects to the site); the
parent nsdl.co.in allows everything except a few query patterns not used
here. One month per request, three seconds apart.
"""

from __future__ import annotations

import gzip
import re
import sys
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.archive.prices import _manifest_rows, record  # noqa: E402
from src.common.bounded import bounded  # noqa: E402
from src.common.hashing import hash_bytes  # noqa: E402
from src.common.paths import ARCHIVE  # noqa: E402

SOURCE_ID = "nsdl_fpi_daily"
EXCHANGE = "NSDL"
REPORT_TYPE = "FPI_DAILY"
URL = "https://www.fpi.nsdl.co.in/web/Reports/Archive.aspx"
#: The first reporting date NSDL serves (probed 2026-09-29: December 1998
#: answers with 31-Dec-1998 alone; September 1998 and earlier answer empty).
EARLIEST_MONTH = date(1998, 12, 1)
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
TIMEOUT = 30
DEADLINE = TIMEOUT + 15
RETRIES = 3
BACKOFF_BASE = 5
RATE_LIMIT = 3.0
#: The whole history is ~335 months; one invocation may take all of it.
DEFAULT_MAX_PER_RUN = 400
#: Wall clock: a run still going after this is not going to finish politely.
MAX_MINUTES = 60

_DECLARED = re.compile(r"Daily Trends in FPI Investments\s+up\s*to\s+(\d{2}-[A-Za-z]{3}-\d{4})", re.I)
_DAY = re.compile(r"\b\d{2}-[A-Za-z]{3}-\d{4}\b")


@dataclass(frozen=True, slots=True)
class Outcome:
    month: date
    status: str
    detail: str = ""


def month_end(m: date) -> date:
    nxt = (m.replace(day=28) + timedelta(days=4)).replace(day=1)
    return nxt - timedelta(days=1)


def months(start: date, end: date) -> list[date]:
    """First-of-month dates from `start`'s month to `end`'s month, inclusive."""
    out, m = [], start.replace(day=1)
    while m <= end.replace(day=1):
        out.append(m)
        m = (m.replace(day=28) + timedelta(days=4)).replace(day=1)
    return out


def request_date(m: date, today: date) -> date:
    """The date asked for: the month's last day, or today inside the current month."""
    return min(month_end(m), today)


def _hidden(html: str) -> dict[str, str]:
    return {m.group(1): m.group(2) for m in re.finditer(
        r'<input type="hidden" name="([^"]+)" id="[^"]*" value="([^"]*)"', html)}


def _fetch(asked: date) -> bytes:
    """GET the form (fresh view state and cookies), then post back the date."""
    last: Exception | None = None
    for attempt in range(RETRIES):
        if attempt:
            time.sleep(BACKOFF_BASE * (2 ** (attempt - 1)))
        try:
            op = build_opener(HTTPCookieProcessor(CookieJar()))

            def _go() -> bytes:
                hdr = {"User-Agent": UA, "Referer": URL}
                with op.open(Request(URL, headers=hdr), timeout=TIMEOUT) as r:  # noqa: S310
                    form = _hidden(r.read().decode("utf-8", "replace"))
                form.update(__EVENTTARGET="btnSubmit1", __EVENTARGUMENT="",
                            hdnDate=asked.strftime("%d-%b-%Y"))
                with op.open(Request(URL, data=urlencode(form).encode(), headers=hdr),  # noqa: S310
                             timeout=TIMEOUT) as r:
                    return r.read()
            return bounded(_go, DEADLINE * 2, what=f"nsdl {asked}")
        except Exception as exc:  # noqa: BLE001 - retried, then reported
            last = exc
    raise RuntimeError(f"all {RETRIES} attempts failed for {asked}: {last}")


def verify(body: bytes, asked: date) -> str | None:
    """None if the page is the month asked for; otherwise why not."""
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body.decode("utf-8", "replace")))
    m = _DECLARED.search(text)
    if not m:
        return "no 'Daily Trends in FPI Investments up to' header — not the report page"
    declared = datetime.strptime(m.group(1), "%d-%b-%Y").date()
    if declared != asked:
        return f"page says up to {declared}, asked for {asked}"
    days = {datetime.strptime(d, "%d-%b-%Y").date() for d in _DAY.findall(text[m.end():])}
    days = {d for d in days if d.year == asked.year and d.month == asked.month}
    if not days:
        return "the page carries no reporting day in the month asked for"
    return None


def archive_path(asked: date, digest: str) -> Path:
    name = f"{REPORT_TYPE}_{EXCHANGE}_{asked:%Y%m%d}_{digest[:8]}.html.gz"
    return ARCHIVE / REPORT_TYPE / EXCHANGE / f"year={asked:%Y}" / f"month={asked:%m}" / name


def settled_months() -> set[str]:
    """Months held AS A WHOLE: a stored page whose date is the month's last day."""
    out = set()
    for r in _manifest_rows():
        if r.get("source_id") == SOURCE_ID and r.get("status") in {"STORED", "DUPLICATE"}:
            d = date.fromisoformat(r["session_date"][:10])
            if d == month_end(d):
                out.add(d.strftime("%Y-%m"))
    return out


def wanted(today: date, start: date | None = None) -> list[date]:
    """Months to fetch: every month not held whole, plus — always — the current
    and the previous month, which NSDL may still be filling in or revising."""
    start = max(start or EARLIEST_MONTH, EARLIEST_MONTH)
    done = settled_months()
    recent = {today.replace(day=1), (today.replace(day=1) - timedelta(days=1)).replace(day=1)}
    return [m for m in months(start, today) if m.strftime("%Y-%m") not in done or m in recent]


def capture(m: date, today: date) -> dict:
    asked = request_date(m, today)
    base = {"source_id": SOURCE_ID, "exchange": EXCHANGE, "report_type": REPORT_TYPE,
            "url": URL, "request": f"POST hdnDate={asked:%d-%b-%Y}",
            "session_date": asked.isoformat(), "fetched_at": datetime.now(UTC).isoformat()}
    try:
        body = _fetch(asked)
    except Exception as exc:  # noqa: BLE001 - the record is the deliverable
        return {**base, "status": "FAILED", "error": str(exc)[:200]}
    why = verify(body, asked)
    if why:
        return {**base, "status": "FAILED", "bytes": len(body), "error": why}
    digest = hash_bytes(body)
    entry = {**base, "sha256": digest, "bytes": len(body)}
    dest = archive_path(asked, digest)
    if dest.exists():
        return {**entry, "status": "DUPLICATE", "path": str(dest)}
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".partial")
    with gzip.open(tmp, "wb") as fh:
        fh.write(body)
    tmp.rename(dest)
    return {**entry, "status": "STORED", "path": str(dest)}


def collect(start: date | None = None, max_per_run: int = DEFAULT_MAX_PER_RUN,
            max_minutes: float = MAX_MINUTES, today: date | None = None) -> list[Outcome]:
    today = today or datetime.now(UTC).date()
    deadline = time.monotonic() + max_minutes * 60
    out: list[Outcome] = []
    for i, m in enumerate(wanted(today, start)[:max_per_run]):
        if time.monotonic() >= deadline:
            out.append(Outcome(m, "STOPPED", f"wall clock: {max_minutes:g} min reached after {i} month(s)"))
            break
        if i:
            time.sleep(RATE_LIMIT)
        e = capture(m, today)
        record(e)
        out.append(Outcome(m, e["status"], e.get("error", "")))
    return out


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Archive NSDL daily FPI flows, month by month.")
    ap.add_argument("--start", type=date.fromisoformat, default=None,
                    help="first month to consider (default: December 1998)")
    ap.add_argument("--max", type=int, default=DEFAULT_MAX_PER_RUN, dest="max_per_run")
    ap.add_argument("--max-minutes", type=float, default=MAX_MINUTES)
    a = ap.parse_args()
    results = collect(a.start, a.max_per_run, a.max_minutes)
    tally: dict[str, int] = {}
    for r in results:
        tally[r.status] = tally.get(r.status, 0) + 1
        if r.status == "FAILED":
            print(f"  FAILED  {r.month:%Y-%m}  {r.detail[:110]}")
    print(f"NSDL FPI: {len(results)} month(s) {tally}")
    return 1 if tally.get("FAILED") else 0


if __name__ == "__main__":
    raise SystemExit(main())
