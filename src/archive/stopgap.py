"""stopgap.py — capture today's raw bytes before they are gone. Nothing else.

WHY THIS EXISTS, AND WHY IT IS DELIBERATELY STUPID.

`nsearchives.nseindia.com/content/equities/bulk.csv` is a ROLLING CURRENT-DAY
file. It serves today and only today. The historical route
(`/api/historical/bulk-deals`) answers 503. Measured 2026-08-16, see
docs/plan/FEASIBILITY_2026-08-16.md.

Therefore: every trading session not fetched is lost permanently. Not
"inconvenient to recover" — gone. 2026-07-09 onward is already a hole because no
collector has ever existed in this project or its predecessor.

The real collector needs an archive layer, ingestion_status, holiday handling,
retry policy, symbol resolution and DB landing. That is one to two days of work.
This file is the thing that runs TONIGHT so those two days cost nothing.

So it does exactly four things and refuses to grow:

    1. fetch the bytes
    2. sha256 them
    3. write them once, gzipped, never overwriting
    4. append one honest line to a manifest, including failures

It does NOT parse into a schema, touch a database, resolve symbols, or classify
participants. The bytes are the deliverable. Everything else can be rebuilt from
them later, at leisure, as many times as we get it wrong.

The one exception to "no parsing" is reading the Date column off the first data
row. That is not a convenience: on a Saturday this endpoint still serves FRIDAY's
file, and archiving Friday's content under Saturday's date would silently
manufacture a duplicate session. The file names itself; we do not name it.
"""

from __future__ import annotations

import gzip
import json
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.common.hashing import hash_bytes  # noqa: E402
from src.common.paths import ARCHIVE  # noqa: E402

# Matches configs/sources.yml http:. A bare curl with no User-Agent is rejected by
# NSE in ~0.2s, which looks exactly like a DNS failure. The predecessor
# misdiagnosed that as "intermittent DNS" for days.
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
TIMEOUT = 30
RETRIES = 3
BACKOFF_BASE = 5
RATE_LIMIT = 2.0

MANIFEST = ARCHIVE / "manifest.jsonl"

#: A legitimately empty day, not a failure. block.csv returns this body on days
#: with no block deals. Being able to tell "no deals" from "fetch broke" is the
#: entire difference between an honest ingestion log and a guess — and its
#: absence is how the predecessor lost a Friday without noticing.
EMPTY_SENTINEL = "NO RECORDS"


@dataclass(frozen=True, slots=True)
class Source:
    id: str
    exchange: str
    report_type: str
    url: str
    kind: str  # "csv" | "json"
    required: bool  # a failure here makes the whole run exit non-zero


SOURCES: tuple[Source, ...] = (
    Source(
        "nse_bulk_deals", "NSE", "BULK",
        "https://nsearchives.nseindia.com/content/equities/bulk.csv", "csv", True,
    ),
    Source(
        "nse_block_deals", "NSE", "BLOCK",
        "https://nsearchives.nseindia.com/content/equities/block.csv", "csv", True,
    ),
    Source(
        "fii_dii_cash", "NSE", "FII_DII",
        "https://www.nseindia.com/api/fiidiiTradeReact", "json", False,
    ),
)


def _fetch(url: str, referer: str = "https://www.nseindia.com/") -> bytes:
    """GET with retry and backoff. Returns raw bytes or raises."""
    last: Exception | None = None
    for attempt in range(RETRIES):
        if attempt:
            time.sleep(BACKOFF_BASE * (2 ** (attempt - 1)))
        try:
            req = Request(
                url,
                headers={
                    "User-Agent": UA,
                    "Accept": "*/*",
                    "Accept-Language": "en-US,en;q=0.9",
                    "Referer": referer,
                },
            )
            with urlopen(req, timeout=TIMEOUT) as resp:  # noqa: S310 - fixed https hosts
                return resp.read()
        except (HTTPError, URLError, TimeoutError) as exc:
            last = exc
    raise RuntimeError(f"all {RETRIES} attempts failed for {url}: {last}")


def session_date(body: bytes, kind: str) -> str | None:
    """The session the FILE claims to cover, parsed from its own first data row.

    Returns an ISO date, or None if the file is empty or undated. Never falls back
    to today's date: a wrong session label is worse than a missing one, because it
    survives into the warehouse looking like fact.
    """
    text = body.decode("utf-8", errors="replace")

    if kind == "json":
        # /api/fiidiiTradeReact returns [{"date": "17-Aug-2026", ...}, ...]. Same
        # rolling-snapshot problem as the CSVs, so it gets the same treatment.
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, list) or not payload:
            return None
        raw = str(payload[0].get("date", "")).strip()
        for fmt in ("%d-%b-%Y", "%d-%B-%Y"):
            try:
                return datetime.strptime(raw, fmt).date().isoformat()
            except ValueError:
                continue
        return None

    lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(lines) < 2 or EMPTY_SENTINEL in text.upper():
        return None
    first_field = lines[1].split(",")[0].strip().strip('"')
    try:
        return datetime.strptime(first_field, "%d-%b-%Y").date().isoformat()
    except ValueError:
        return None


def archive_path(src: Source, session: str | None, digest: str, fetched: datetime) -> Path:
    """raw/archive/{report_type}/{exchange}/year=/month=/{name}. Per sources.yml.

    Partitioned on the SESSION date when the file declares one, else on the fetch
    date with an explicit `undated_` prefix so the distinction is visible in `ls`
    rather than buried in the manifest.
    """
    stamp = session or fetched.date().isoformat()
    y, m = stamp[:4], stamp[5:7]
    prefix = "" if session else "undated_"
    ext = "json" if src.kind == "json" else "csv"
    name = f"{prefix}{src.report_type}_{src.exchange}_{stamp.replace('-', '')}_{digest[:8]}.{ext}.gz"
    return ARCHIVE / src.report_type / src.exchange / f"year={y}" / f"month={m}" / name


def already_have(digest: str) -> Path | None:
    """Dedupe on sha256, per sources.yml `dedupe_on`.

    Not a micro-optimisation. On a weekend or holiday this endpoint keeps serving
    the LAST trading day's file, so an unguarded daily cron would archive Friday
    three times and a naive downstream count would report three sessions.
    """
    if not MANIFEST.exists():
        return None
    for line in MANIFEST.read_text().splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        if rec.get("sha256") == digest and rec.get("status") in {"STORED", "DUPLICATE", "EMPTY_DAY"}:
            return Path(rec["path"]) if rec.get("path") else None
    return None


def record(entry: dict) -> None:
    """Append one line to the manifest. Failures are recorded, not swallowed."""
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    with MANIFEST.open("a") as fh:
        fh.write(json.dumps(entry, sort_keys=True) + "\n")


def capture(src: Source) -> dict:
    fetched = datetime.now(UTC)
    base = {
        "source_id": src.id,
        "exchange": src.exchange,
        "report_type": src.report_type,
        "url": src.url,
        "fetched_at": fetched.isoformat(),
    }

    try:
        body = _fetch(src.url)
    except Exception as exc:  # noqa: BLE001 - the message is the deliverable
        return {**base, "status": "FAILED", "error": str(exc)}

    digest = hash_bytes(body)
    session = session_date(body, src.kind)
    text = body.decode("utf-8", errors="replace")
    is_empty = EMPTY_SENTINEL in text[:4096].upper()

    entry = {
        **base,
        "sha256": digest,
        "bytes": len(body),
        "session_date": session,
        "rows": max(0, len(text.splitlines()) - 1) if src.kind == "csv" and not is_empty else 0,
    }
    if is_empty:
        # Stored anyway. An empty day is evidence that we asked and the answer was
        # "none", which is a different fact from never having asked.
        entry["status"] = "EMPTY_DAY"

    prior = already_have(digest)
    if prior is not None:
        return {**entry, "status": "DUPLICATE", "path": str(prior),
                "note": "identical bytes already archived; endpoint served a stale file"}

    dest = archive_path(src, session, digest, fetched)
    if dest.exists():
        return {**entry, "status": "DUPLICATE", "path": str(dest)}

    dest.parent.mkdir(parents=True, exist_ok=True)
    # Write to a temp name then rename: an interrupted run must never leave a
    # truncated file that looks archived. Raw files are never overwritten.
    tmp = dest.with_suffix(dest.suffix + ".partial")
    with gzip.open(tmp, "wb") as fh:
        fh.write(body)
    tmp.rename(dest)

    return {**entry, "status": entry.get("status", "STORED"), "path": str(dest)}


def main() -> int:
    # Warm the session for cookies before hitting the API host. The archive host
    # does not need this; /api/ does.
    try:
        _fetch("https://www.nseindia.com/", referer="https://www.google.com/")
    except Exception as exc:  # noqa: BLE001
        print(f"  warmup failed (continuing, archive host may not need it): {exc}")

    results = []
    for src in SOURCES:
        entry = capture(src)
        record(entry)
        results.append((src, entry))
        status = entry["status"]
        detail = (
            entry["error"][:80]
            if status == "FAILED"
            else f"session={entry.get('session_date')} rows={entry.get('rows')} "
                 f"sha={entry.get('sha256', '')[:8]}"
        )
        print(f"  {status:<10} {src.id:<18} {detail}")
        time.sleep(RATE_LIMIT)

    failed = [s.id for s, e in results if e["status"] == "FAILED" and s.required]
    if failed:
        print(f"\nREQUIRED SOURCE FAILED: {', '.join(failed)}")
        print("This session's bytes may be permanently lost. Investigate today.")
        return 1
    print(f"\nmanifest: {MANIFEST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
