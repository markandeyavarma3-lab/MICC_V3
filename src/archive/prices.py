"""prices.py — the daily price feed, without which two weeks of deals are unusable.

WHY THIS EXISTS.

The collector has archived bulk and block deals since 2026-08-17. Every one of
them is INELIGIBLE, because eligibility needs a next-session price and the price
spine ends 2026-08-14 — it came from the MICCV2 export and nothing has extended
it since. Measured on `institutional_deals_clean`: of 611 live-collected rows,
469 fail on "no next session in the data" and 142 on uncovered symbols. The
deals are archived, correct, and worthless until prices arrive.

HOW THIS DIFFERS FROM stopgap.py, WHICH IS THE WHOLE DESIGN.

`stopgap.py` fetches ROLLING CURRENT-DAY files. bulk.csv serves today and only
today, the historical route answers 503, and a session not fetched by tomorrow
is gone forever. That urgency is why it refuses to do anything but store bytes.

Bhavcopy is the opposite: a DATED ARCHIVE. Measured 2026-09-01:

    BhavCopy_NSE_CM_0_0_0_20260828_F_0000.csv.zip   200, 202,201 bytes
    all 11 sessions 2026-08-17..08-31                200
    2024-01-02                                        200
    2023-01-02 and the whole of 2023                  404

So the earliest re-fetchable session is in the week of **2024-01-01**, and
nothing between there and today is at risk. This module can therefore BACKFILL,
which stopgap.py can never do, and a missed run costs a retry rather than a
session. It also means 2024-01-01 onward is the only stretch of the spine that
could ever be rebuilt without the MICCV2 export; 2005-2023 remains single-copy.

WHY THE FILE'S OWN DATE IS CHECKED AGAINST THE ONE REQUESTED.

stopgap.py has to read the session date off the first data row, because a
rolling endpoint on a Saturday still serves Friday and archiving it under
Saturday would manufacture a session. Here the date is in the URL, so the
in-file `TradDt` is not needed to LABEL the file — it is used to VERIFY it.
Asking for one date and being served another is silent corruption of exactly
the kind the identity layer cannot repair later.
"""

from __future__ import annotations

import gzip
import io
import json
import sys
import time
import zipfile
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.common.hashing import hash_bytes  # noqa: E402
from src.common.paths import ARCHIVE  # noqa: E402

SOURCE_ID = "nse_bhavcopy"
EXCHANGE = "NSE"
REPORT_TYPE = "PRICE"

URL = ("https://nsearchives.nseindia.com/content/cm/"
       "BhavCopy_NSE_CM_0_0_0_{ymd}_F_0000.csv.zip")

#: Measured 2026-09-01 by binary search: the whole of 2023 answers 404, the week
#: of 2024-01-01 answers 200. Asking for anything earlier is a guaranteed 404,
#: and a collector that hammers a known-absent range is indistinguishable from a
#: broken one in the logs.
EARLIEST = date(2024, 1, 1)

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
TIMEOUT = 30
RETRIES = 3
BACKOFF_BASE = 5
RATE_LIMIT = 2.0

MANIFEST = ARCHIVE / "manifest.jsonl"

#: How many sessions one run will fetch. A first run has a year of backfill to
#: do and should not open 400 connections in a burst; the daily runs that follow
#: have one session each. Raise it deliberately for a catch-up, do not remove it.
DEFAULT_MAX_PER_RUN = 40


@dataclass(frozen=True, slots=True)
class Outcome:
    session: date
    status: str
    detail: str = ""


def _fetch(url: str) -> bytes:
    last: Exception | None = None
    for attempt in range(RETRIES):
        if attempt:
            time.sleep(BACKOFF_BASE * (2 ** (attempt - 1)))
        try:
            req = Request(url, headers={
                "User-Agent": UA,
                "Accept": "*/*",
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": "https://www.nseindia.com/",
            })
            with urlopen(req, timeout=TIMEOUT) as resp:  # noqa: S310 - fixed https host
                return resp.read()
        except HTTPError as exc:
            if exc.code == 404:
                raise  # a holiday or an unpublished session; retrying cannot help
            last = exc
        except (URLError, TimeoutError) as exc:
            last = exc
    raise RuntimeError(f"all {RETRIES} attempts failed for {url}: {last}")


def declared_date(body: bytes) -> str | None:
    """The TradDt the archive itself declares, read from inside the zip.

    Used to VERIFY, never to label — the label comes from the URL. Returns None
    if the payload cannot be read as the expected zip-of-one-csv, which is
    itself a reason to refuse the file.
    """
    try:
        with zipfile.ZipFile(io.BytesIO(body)) as z:
            names = [n for n in z.namelist() if n.lower().endswith(".csv")]
            if len(names) != 1:
                return None
            with z.open(names[0]) as fh:
                header = fh.readline().decode("utf-8", "replace").strip().split(",")
                row = fh.readline().decode("utf-8", "replace").strip().split(",")
    except (zipfile.BadZipFile, OSError, IndexError):
        return None
    if "TradDt" not in header or len(row) <= header.index("TradDt"):
        return None
    return row[header.index("TradDt")].strip() or None


def archive_path(session: date, digest: str) -> Path:
    """Same layout as stopgap.py, per sources.yml `layout`.

    Gzipped even though the payload is already a zip. The extra compression buys
    nothing and is accepted on purpose: every archived file in this project is
    `.gz`, the backup and status counts glob for it, and one convention that is
    slightly wasteful beats two that are each perfectly efficient.
    """
    name = (f"{REPORT_TYPE}_{EXCHANGE}_{session:%Y%m%d}_{digest[:8]}.csv.zip.gz")
    return (ARCHIVE / REPORT_TYPE / EXCHANGE
            / f"year={session:%Y}" / f"month={session:%m}" / name)


def _manifest_rows() -> list[dict]:
    if not MANIFEST.exists():
        return []
    out = []
    for line in MANIFEST.read_text().splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def settled_sessions() -> set[str]:
    """Sessions this module never needs to ask about again.

    STORED/DUPLICATE  the bytes are held.
    NO_SESSION        a 404 on a date already in the past: a holiday, or a day
                      NSE simply did not trade. Recording it is what stops the
                      collector re-probing every holiday since 2024 on every run.

    PENDING and FAILED are deliberately absent: those must be retried.
    """
    return {
        r["session_date"] for r in _manifest_rows()
        if r.get("source_id") == SOURCE_ID
        and r.get("session_date")
        and r.get("status") in {"STORED", "DUPLICATE", "NO_SESSION"}
    }


def missing(start: date, end: date) -> list[date]:
    """Weekday sessions in [start, end] with nothing settled against them.

    Weekends are excluded outright rather than probed. Indian exchange holidays
    are NOT hardcoded — a holiday calendar in a config file is a claim that goes
    stale, and the 404 that discovers one is recorded as NO_SESSION and never
    repeated. The observed calendar earns itself.
    """
    if start < EARLIEST:
        start = EARLIEST
    done = settled_sessions()
    out, d = [], start
    while d <= end:
        if d.weekday() < 5 and d.isoformat() not in done:
            out.append(d)
        d += timedelta(days=1)
    return out


def record(entry: dict) -> None:
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    with MANIFEST.open("a") as fh:
        fh.write(json.dumps(entry, sort_keys=True) + "\n")


def capture(session: date, today: date | None = None) -> dict:
    """Fetch, verify and archive one session. Never raises; the record is the
    deliverable, failures included."""
    today = today or datetime.now(UTC).date()
    url = URL.format(ymd=f"{session:%Y%m%d}")
    base = {
        "source_id": SOURCE_ID, "exchange": EXCHANGE, "report_type": REPORT_TYPE,
        "url": url, "session_date": session.isoformat(),
        "fetched_at": datetime.now(UTC).isoformat(),
    }

    try:
        body = _fetch(url)
    except HTTPError as exc:
        if exc.code == 404:
            # A 404 on a PAST date is a settled fact: NSE did not trade, or never
            # published. A 404 on TODAY is a race with publication (~18:30 IST),
            # so it must stay retryable or the evening run would permanently
            # write off every session the morning run asked for too early.
            if session < today:
                return {**base, "status": "NO_SESSION",
                        "note": "404 on a past date: holiday or no session"}
            return {**base, "status": "PENDING",
                    "note": "404 on today; not yet published, will retry"}
        return {**base, "status": "FAILED", "error": f"HTTP {exc.code}"}
    except Exception as exc:  # noqa: BLE001 - the message is the deliverable
        return {**base, "status": "FAILED", "error": str(exc)}

    declared = declared_date(body)
    if declared is None:
        return {**base, "status": "FAILED", "bytes": len(body),
                "error": "payload is not a readable zip-of-one-csv with TradDt"}
    if declared != session.isoformat():
        # Served a different session than requested. stopgap.py cannot detect
        # this class of error at all; here it is cheap, so it is refused.
        return {**base, "status": "FAILED", "bytes": len(body),
                "error": f"served TradDt {declared}, requested {session.isoformat()}"}

    digest = hash_bytes(body)
    entry = {**base, "sha256": digest, "bytes": len(body)}

    for r in _manifest_rows():
        if r.get("sha256") == digest and r.get("status") in {"STORED", "DUPLICATE"}:
            return {**entry, "status": "DUPLICATE", "path": r.get("path", ""),
                    "note": "identical bytes already archived"}

    dest = archive_path(session, digest)
    if dest.exists():
        return {**entry, "status": "DUPLICATE", "path": str(dest)}

    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".partial")
    with gzip.open(tmp, "wb") as fh:
        fh.write(body)
    tmp.rename(dest)
    return {**entry, "status": "STORED", "path": str(dest)}


def collect(start: date | None = None, end: date | None = None,
            max_per_run: int = DEFAULT_MAX_PER_RUN) -> list[Outcome]:
    today = datetime.now(UTC).date()
    end = end or today
    if start is None:
        settled = settled_sessions()
        start = (max(date.fromisoformat(s) for s in settled) + timedelta(days=1)
                 if settled else EARLIEST)

    todo = missing(start, end)[:max_per_run]
    out: list[Outcome] = []
    for i, session in enumerate(todo):
        if i:
            time.sleep(RATE_LIMIT)
        entry = capture(session, today=today)
        record(entry)
        out.append(Outcome(session, entry["status"],
                           entry.get("error") or entry.get("note", "")))
    return out


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Archive NSE bhavcopy for missing sessions.")
    ap.add_argument("--start", type=date.fromisoformat, default=None,
                    help="first session (default: the day after the newest settled one)")
    ap.add_argument("--end", type=date.fromisoformat, default=None)
    ap.add_argument("--max", type=int, default=DEFAULT_MAX_PER_RUN, dest="max_per_run")
    args = ap.parse_args()

    results = collect(args.start, args.end, args.max_per_run)
    if not results:
        print("PRICE ARCHIVE: nothing missing")
        return 0

    counts: dict[str, int] = {}
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1
        flag = {"STORED": "ok   ", "DUPLICATE": "dup  ",
                "NO_SESSION": "none ", "PENDING": "wait ",
                "FAILED": "FAIL "}.get(r.status, r.status)
        print(f"  {flag} {r.session}  {r.detail}"[:120])

    print("\nPRICE ARCHIVE: " + "  ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    remaining = len(missing(results[-1].session + timedelta(days=1),
                            args.end or datetime.now(UTC).date()))
    if remaining:
        print(f"  {remaining} session(s) still missing — run again to continue")
    return 1 if counts.get("FAILED") else 0


if __name__ == "__main__":
    raise SystemExit(main())
