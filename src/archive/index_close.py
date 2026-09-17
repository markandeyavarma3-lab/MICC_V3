"""index_close.py — every NSE index's daily close, as a dated archive.

WHY THIS SOURCE. `benchmarks.yml` names the NIFTY 500 as the market leg and
CHAR_MATCHED as the primary; sector benchmarks are "Phase 3". The one file NSE
publishes daily with EVERY index in it — NIFTY 50, Next 50, 500, every sector
and thematic index, with P/E, P/B and dividend yield — is
`ind_close_all_DDMMYYYY.csv` on the static archive host. Four sessions of it
were archived on 2026-09-15 by `probe.py` as a proof; this is the collector.

A DATED ARCHIVE, SO IT BACKFILLS. Measured 2026-09-18 by bisection: 2021-10-15
answers 404, 2021-10-18 answers 200, and every date tried after that answers
200. So the archive reaches back to **2021-10-18** and a missed run costs a
retry, not a session — the same property `prices.py` has and `stopgap.py`
never will. Asking for anything earlier is a guaranteed 404 and is refused
here rather than logged as a mystery.

THE LABEL COMES FROM THE URL AND IS VERIFIED AGAINST THE FILE. The CSV's
`Index Date` column is DD-MM-YYYY; a file that declares a different date than
the one requested is refused, the way `prices.py` refuses a wrong TradDt.

Same manifest, same layout, same statuses as prices.py: STORED, DUPLICATE,
NO_SESSION (404 on a past weekday: holiday), PENDING (404 on today: not yet
published), FAILED. The source id `nse_index_close_all` and report type
`INDEX_CLOSE` are the ones the 2026-09-15 proof already used, so the series
stays one series in the manifest.
"""

from __future__ import annotations

import gzip
import sys
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.common.bounded import bounded  # noqa: E402
from src.common.hashing import hash_bytes  # noqa: E402
from src.common.paths import ARCHIVE  # noqa: E402
from src.archive.prices import _manifest_rows, record  # noqa: E402

SOURCE_ID = "nse_index_close_all"
EXCHANGE = "NSE"
REPORT_TYPE = "INDEX_CLOSE"
URL = "https://nsearchives.nseindia.com/content/indices/ind_close_all_{dmy}.csv"

#: Measured 2026-09-18: 2021-10-15 -> 404, 2021-10-18 -> 200.
EARLIEST = date(2021, 10, 18)

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
TIMEOUT = 30
DEADLINE = TIMEOUT + 15
RETRIES = 3
BACKOFF_BASE = 5
RATE_LIMIT = 2.0
#: 40 is the daily-run size, like prices.py. A backfill passes --max explicitly.
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
            req = Request(url, headers={"User-Agent": UA, "Accept": "*/*",
                                        "Referer": "https://www.nseindia.com/"})
            def _get(req=req) -> bytes:
                with urlopen(req, timeout=TIMEOUT) as resp:  # noqa: S310 - fixed https host
                    return resp.read()
            return bounded(_get, DEADLINE, what=url)
        except HTTPError as exc:
            if exc.code == 404:
                raise  # a holiday or an unpublished session; retrying cannot help
            last = exc
        except (URLError, TimeoutError) as exc:
            last = exc
    raise RuntimeError(f"all {RETRIES} attempts failed for {url}: {last}")


def declared_date(body: bytes) -> str | None:
    """The `Index Date` the file itself declares (DD-MM-YYYY -> ISO), from its
    first data row. Used to VERIFY, never to label."""
    try:
        lines = body.decode("utf-8", "replace").splitlines()
        header = [h.strip() for h in lines[0].split(",")]
        row = lines[1].split(",")
        i = header.index("Index Date")
        d, m, y = row[i].strip().split("-")
        return f"{y}-{m}-{d}"
    except (IndexError, ValueError):
        return None


def archive_path(session: date, digest: str) -> Path:
    name = f"{REPORT_TYPE}_{EXCHANGE}_{session:%Y%m%d}_{digest[:8]}.csv.gz"
    return ARCHIVE / REPORT_TYPE / EXCHANGE / f"year={session:%Y}" / f"month={session:%m}" / name


def settled_sessions() -> set[str]:
    return {r["session_date"][:10] for r in _manifest_rows()
            if r.get("source_id") == SOURCE_ID and r.get("session_date")
            and r.get("status") in {"STORED", "DUPLICATE", "NO_SESSION"}}


def missing(start: date, end: date) -> list[date]:
    if start < EARLIEST:
        start = EARLIEST
    done = settled_sessions()
    out, d = [], start
    while d <= end:
        if d.weekday() < 5 and d.isoformat() not in done:
            out.append(d)
        d += timedelta(days=1)
    return out


def capture(session: date, today: date | None = None) -> dict:
    today = today or datetime.now(UTC).date()
    url = URL.format(dmy=f"{session:%d%m%Y}")
    base = {"source_id": SOURCE_ID, "exchange": EXCHANGE, "report_type": REPORT_TYPE,
            "url": url, "session_date": session.isoformat(),
            "fetched_at": datetime.now(UTC).isoformat()}
    try:
        body = _fetch(url)
    except HTTPError as exc:
        if exc.code == 404:
            if session < today:
                return {**base, "status": "NO_SESSION", "note": "404 on a past date: holiday or no session"}
            return {**base, "status": "PENDING", "note": "404 on today; not yet published, will retry"}
        return {**base, "status": "FAILED", "error": f"HTTP {exc.code}"}
    except Exception as exc:  # noqa: BLE001 - the message is the deliverable
        return {**base, "status": "FAILED", "error": str(exc)}

    declared = declared_date(body)
    if declared is None:
        return {**base, "status": "FAILED", "bytes": len(body),
                "error": "payload is not a CSV with an Index Date column"}
    if declared != session.isoformat():
        return {**base, "status": "FAILED", "bytes": len(body),
                "error": f"served Index Date {declared}, requested {session.isoformat()}"}

    digest = hash_bytes(body)
    entry = {**base, "sha256": digest, "bytes": len(body)}
    for r in _manifest_rows():
        if r.get("sha256") == digest and r.get("status") in {"STORED", "DUPLICATE"}:
            return {**entry, "status": "DUPLICATE", "path": r.get("path", "")}
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
    out: list[Outcome] = []
    for i, session in enumerate(missing(start, end)[:max_per_run]):
        if i:
            time.sleep(RATE_LIMIT)
        entry = capture(session, today=today)
        record(entry)
        out.append(Outcome(session, entry["status"], entry.get("error") or entry.get("note", "")))
    return out


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Archive NSE all-index daily closes for missing sessions.")
    ap.add_argument("--start", type=date.fromisoformat, default=None)
    ap.add_argument("--end", type=date.fromisoformat, default=None)
    ap.add_argument("--max", type=int, default=DEFAULT_MAX_PER_RUN, dest="max_per_run")
    args = ap.parse_args()

    results = collect(args.start, args.end, args.max_per_run)
    if not results:
        print("INDEX CLOSE ARCHIVE: nothing missing")
        return 0
    counts: dict[str, int] = {}
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1
        if r.status in {"FAILED", "PENDING"}:
            print(f"  {r.status:<8} {r.session}  {r.detail}"[:120])
    print("INDEX CLOSE ARCHIVE: " + "  ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    remaining = len(missing(results[-1].session + timedelta(days=1), args.end or datetime.now(UTC).date()))
    if remaining:
        print(f"  {remaining} session(s) still missing — run again to continue")
    return 1 if counts.get("FAILED") else 0


if __name__ == "__main__":
    raise SystemExit(main())
