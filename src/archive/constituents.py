"""constituents.py — which stocks are in which NSE index, today, every day.

WHY THIS SOURCE, AND WHY IT STARTS NOW. `sector_history` has 0 rows and
`char_panel` declares industry MISSING for that reason. The exp_004 draft
names index inclusion as an APPLICABLE, NOT CONTROLLED confound — a stock
entering an index gets passive buying for a non-informational reason — and
says the constituents are "one snapshot". They are: probed 2026-09-18, there is
NO dated history route. `nsearchives .../ind_nifty500list_31032026.csv` is a
404; `niftyindices.com/Index_Constituents/ind_nifty500list_31-Mar-2026.csv`
answers 200 with a 78,919-byte HTML error page for EVERY date asked — a 200
that lies, caught by reading the body.

So history accrues forward only, from the day archiving starts, exactly as
`fii_dii_cash` does. Every day not archived is a day sector_history will
never have. Six lists, one fetch each, sha256-deduped: on an ordinary day all
six are DUPLICATE and cost six requests; on a rebalance day the changed list
is STORED, and the archive becomes the change log for free.

THE SIX LISTS ARE THE SIZE BUCKETS. NIFTY 500 = NIFTY 50 + Next 50 + Midcap
150 + Smallcap 250; Microcap 250 sits below. Archiving the parts and the
whole gives point-in-time size-bucket membership without deriving it.

Same manifest, same layout, same host as the index closes and the bhavcopy.
The 2026-09-15 proof used source id `nifty500_constituents` for the 500 list;
that id is kept, and the other five get their own so each is one series.
"""

from __future__ import annotations

import gzip
import sys
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.common.bounded import bounded  # noqa: E402
from src.common.hashing import hash_bytes  # noqa: E402
from src.common.paths import ARCHIVE  # noqa: E402
from src.archive.prices import _manifest_rows, record  # noqa: E402

EXCHANGE = "NSE"
REPORT_TYPE = "INDEX_CONSTITUENTS"
BASE = "https://nsearchives.nseindia.com/content/indices/"

#: (source_id, file). The 500's id is the one the 2026-09-15 proof used.
LISTS: tuple[tuple[str, str], ...] = (
    ("nifty500_constituents", "ind_nifty500list.csv"),
    ("nifty50_constituents", "ind_nifty50list.csv"),
    ("niftynext50_constituents", "ind_niftynext50list.csv"),
    ("niftymidcap150_constituents", "ind_niftymidcap150list.csv"),
    ("niftysmallcap250_constituents", "ind_niftysmallcap250list.csv"),
    ("niftymicrocap250_constituents", "ind_niftymicrocap250_list.csv"),
)

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
TIMEOUT = 30
DEADLINE = TIMEOUT + 15
RETRIES = 3
BACKOFF_BASE = 5
RATE_LIMIT = 2.0


@dataclass(frozen=True, slots=True)
class Outcome:
    source_id: str
    status: str
    rows: int = 0
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
        except Exception as exc:  # noqa: BLE001 - retried, then reported
            last = exc
    raise RuntimeError(f"all {RETRIES} attempts failed for {url}: {last}")


def looks_like_a_list(body: bytes) -> int:
    """Row count if the body is the constituents CSV, else 0.

    A 200 with an HTML error page is what niftyindices serves for a missing
    date; the archive host could do the same. The header is the check: the
    real file starts `Company Name,Industry,Symbol,Series,ISIN Code`.
    """
    try:
        lines = body.decode("utf-8", "replace").splitlines()
    except Exception:  # noqa: BLE001
        return 0
    if not lines or not lines[0].startswith("Company Name,Industry,Symbol"):
        return 0
    return sum(1 for ln in lines[1:] if ln.strip())


def archive_path(source_id: str, today: date, digest: str) -> Path:
    name = f"{REPORT_TYPE}_{EXCHANGE}_{source_id}_{today:%Y%m%d}_{digest[:8]}.csv.gz"
    return ARCHIVE / REPORT_TYPE / EXCHANGE / f"year={today:%Y}" / f"month={today:%m}" / name


def capture(source_id: str, filename: str, today: date | None = None) -> dict:
    today = today or datetime.now(UTC).date()
    url = BASE + filename
    base = {"source_id": source_id, "exchange": EXCHANGE, "report_type": REPORT_TYPE,
            "url": url, "session_date": today.isoformat(),
            "fetched_at": datetime.now(UTC).isoformat()}
    try:
        body = _fetch(url)
    except Exception as exc:  # noqa: BLE001 - the message is the deliverable
        return {**base, "status": "FAILED", "error": str(exc)}
    n = looks_like_a_list(body)
    if not n:
        return {**base, "status": "FAILED", "bytes": len(body),
                "error": "not a constituents CSV (header mismatch — an HTML error page served as 200?)"}
    digest = hash_bytes(body)
    entry = {**base, "sha256": digest, "bytes": len(body), "rows": n}
    for r in _manifest_rows():
        if r.get("source_id") == source_id and r.get("sha256") == digest \
                and r.get("status") in {"STORED", "DUPLICATE"}:
            return {**entry, "status": "DUPLICATE", "path": r.get("path", ""),
                    "note": "list unchanged since it was last stored"}
    dest = archive_path(source_id, today, digest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".partial")
    with gzip.open(tmp, "wb") as fh:
        fh.write(body)
    tmp.rename(dest)
    return {**entry, "status": "STORED", "path": str(dest)}


def collect(today: date | None = None) -> list[Outcome]:
    out: list[Outcome] = []
    for i, (sid, fn) in enumerate(LISTS):
        if i:
            time.sleep(RATE_LIMIT)
        e = capture(sid, fn, today)
        record(e)
        out.append(Outcome(sid, e["status"], e.get("rows", 0), e.get("error") or e.get("note", "")))
    return out


def main() -> int:
    results = collect()
    for r in results:
        flag = {"STORED": "ok   ", "DUPLICATE": "dup  ", "FAILED": "FAIL "}.get(r.status, r.status)
        print(f"  {flag} {r.source_id:<32} {r.rows:>4} rows  {r.detail}"[:120])
    failed = sum(r.status == "FAILED" for r in results)
    changed = sum(r.status == "STORED" for r in results)
    print(f"\nCONSTITUENTS: {len(results)} list(s), {changed} changed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
