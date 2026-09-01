"""corporate_actions.py — the actions the splice guard could not see.

WHY THIS EXISTS, WITH THE MEASUREMENT THAT FORCED IT.

`spine.build_adjusted` splices the raw price tail onto the adjusted seed and
guards the splice by counting SPLIT/BONUS/RIGHTS after the boundary. On
2026-09-01 that guard was found to be checking a table that ENDS 2026-06-29,
four days past the boundary, while the tail runs to 2026-08-31. A clean pass
meant "no action in four days", not "no action in the tail".

Searching the tail directly for price discontinuities >35% found 22, of which at
least 16 are textbook corporate actions — and FIFTEEN were already in the spine
before this project collected a single price. Every one reads as a -50% to -90%
return in any study built on that series.

This module fetches what the seed's table stops knowing.

INDEPENDENTLY CROSS-VALIDATED, WHICH IS WHY IT IS TRUSTED. The route below was
not adopted because it returned 200. Every split found empirically in the prices
appears in it with the same ex-date and the same ratio:

    CORDELIA    prices 1043.60 -> 104.45 (0.100)   API "Split From Rs 10 To Re 1"
    GOODLUCK    prices 1439.40 -> 490.90 (0.341)   API "Bonus 2:1"      -> 1/3
    TDPOWERSYS  prices 1534.80 -> 780.10 (0.508)   API "Split Rs 2 To Re 1"
    KRISHANA    prices  713.50 -> 151.85 (0.213)   API "Split Rs 10 To Rs 2"

Two methods that share no code and no input agreeing to three decimal places is
a much stronger warrant than either alone.

THE ROUTE IS AN ARCHIVE, NOT A ROLLING FILE. Like bhavcopy and unlike bulk.csv,
it answers for historical windows, so a missed run costs a retry rather than a
permanent hole. It does need the cookie warmup that `nsearchives` does not —
this is on `www.nseindia.com`, the host that 503s for deals history.
"""

from __future__ import annotations

import gzip
import json
import sys
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import HTTPCookieProcessor, Request, build_opener

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.common.hashing import hash_bytes  # noqa: E402
from src.common.paths import ARCHIVE  # noqa: E402

SOURCE_ID = "nse_corporate_actions"
EXCHANGE = "NSE"
REPORT_TYPE = "CORPACT"

URL = ("https://www.nseindia.com/api/corporates-corporateActions"
       "?index=equities&from_date={frm}&to_date={to}")
WARMUP = "https://www.nseindia.com/"
REFERER = "https://www.nseindia.com/companies-listing/corporate-filings-actions"

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
TIMEOUT = 30
RETRIES = 3
BACKOFF_BASE = 5
RATE_LIMIT = 2.0

#: The API caps a query's span. 90 days is comfortably inside it and keeps each
#: archived file small enough to read by eye when something looks wrong.
WINDOW_DAYS = 90

MANIFEST = ARCHIVE / "manifest.jsonl"


@dataclass(frozen=True, slots=True)
class Outcome:
    window: tuple[date, date]
    status: str
    records: int = 0
    detail: str = ""


def _opener():
    """One opener with a cookie jar. www.nseindia.com refuses an un-warmed
    session, which presents as an empty body rather than an error."""
    return build_opener(HTTPCookieProcessor(CookieJar()))


def _get(op, url: str, referer: str) -> bytes:
    last: Exception | None = None
    for attempt in range(RETRIES):
        if attempt:
            time.sleep(BACKOFF_BASE * (2 ** (attempt - 1)))
        try:
            req = Request(url, headers={
                "User-Agent": UA, "Accept": "*/*",
                "Accept-Language": "en-US,en;q=0.9", "Referer": referer,
            })
            with op.open(req, timeout=TIMEOUT) as resp:  # noqa: S310 - fixed https host
                return resp.read()
        except (HTTPError, URLError, TimeoutError) as exc:
            last = exc
    raise RuntimeError(f"all {RETRIES} attempts failed for {url}: {last}")


def windows(start: date, end: date) -> list[tuple[date, date]]:
    out, a = [], start
    while a <= end:
        b = min(a + timedelta(days=WINDOW_DAYS - 1), end)
        out.append((a, b))
        a = b + timedelta(days=1)
    return out


def archive_path(frm: date, to: date, digest: str) -> Path:
    name = f"{REPORT_TYPE}_{EXCHANGE}_{frm:%Y%m%d}_{to:%Y%m%d}_{digest[:8]}.json.gz"
    return (ARCHIVE / REPORT_TYPE / EXCHANGE
            / f"year={frm:%Y}" / f"month={frm:%m}" / name)


def record(entry: dict) -> None:
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    with MANIFEST.open("a") as fh:
        fh.write(json.dumps(entry, sort_keys=True) + "\n")


def _seen(digest: str) -> str | None:
    if not MANIFEST.exists():
        return None
    for line in MANIFEST.read_text().splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if r.get("sha256") == digest and r.get("status") in {"STORED", "DUPLICATE"}:
            return r.get("path")
    return None


def capture(op, frm: date, to: date) -> dict:
    url = URL.format(frm=f"{frm:%d-%m-%Y}", to=f"{to:%d-%m-%Y}")
    base = {
        "source_id": SOURCE_ID, "exchange": EXCHANGE, "report_type": REPORT_TYPE,
        "url": url, "window_from": frm.isoformat(), "window_to": to.isoformat(),
        "fetched_at": datetime.now(UTC).isoformat(),
    }
    try:
        body = _get(op, url, REFERER)
    except Exception as exc:  # noqa: BLE001 - the record is the deliverable
        return {**base, "status": "FAILED", "error": str(exc)}

    # An un-warmed or throttled session returns 200 with a body that is not the
    # array we asked for. Storing that as if it were data is how a silent hole
    # gets into the warehouse, so the shape is checked before anything is kept.
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return {**base, "status": "FAILED", "bytes": len(body),
                "error": "response is not JSON (session likely not warmed)"}
    if not isinstance(payload, list):
        return {**base, "status": "FAILED", "bytes": len(body),
                "error": f"expected a JSON array, got {type(payload).__name__}"}

    digest = hash_bytes(body)
    entry = {**base, "sha256": digest, "bytes": len(body), "records": len(payload)}

    if (prior := _seen(digest)) is not None:
        return {**entry, "status": "DUPLICATE", "path": prior}

    dest = archive_path(frm, to, digest)
    if dest.exists():
        return {**entry, "status": "DUPLICATE", "path": str(dest)}
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".partial")
    with gzip.open(tmp, "wb") as fh:
        fh.write(body)
    tmp.rename(dest)
    return {**entry, "status": "STORED", "path": str(dest)}


def collect(start: date, end: date | None = None) -> list[Outcome]:
    end = end or datetime.now(UTC).date()
    op = _opener()
    try:
        _get(op, WARMUP, "https://www.google.com/")
    except Exception as exc:  # noqa: BLE001
        print(f"  warmup failed (continuing, the API may still answer): {exc}")

    out = []
    for i, (a, b) in enumerate(windows(start, end)):
        if i:
            time.sleep(RATE_LIMIT)
        e = capture(op, a, b)
        record(e)
        out.append(Outcome((a, b), e["status"], e.get("records", 0),
                           e.get("error", "")))
    return out


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Archive NSE corporate actions.")
    ap.add_argument("--start", type=date.fromisoformat, required=True)
    ap.add_argument("--end", type=date.fromisoformat, default=None)
    args = ap.parse_args()

    results = collect(args.start, args.end)
    for r in results:
        flag = {"STORED": "ok   ", "DUPLICATE": "dup  ", "FAILED": "FAIL "}.get(r.status, r.status)
        print(f"  {flag} {r.window[0]} .. {r.window[1]}  {r.records:>5} records  {r.detail}"[:120])
    failed = sum(r.status == "FAILED" for r in results)
    print(f"\nCORPACT: {len(results)} window(s), {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
