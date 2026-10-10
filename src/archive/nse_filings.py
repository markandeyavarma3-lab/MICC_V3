"""nse_filings.py — three NSE corporate-filing feeds for the public site.

WHY (2026-10-10). The owner asked for a broader site (docs/plan/WEBSITE_PLAN.md,
"C. market structure"). Measured that day, all three answer on the same
www.nseindia.com session the corporate-actions collector already warms:

  PLEDGE        corporate-pledgedata        a SNAPSHOT: every company's latest
                                            promoter holding and pledged share
                                            (1,546 companies)
  ANNOUNCE      corporate-announcements     a dated FEED: 4,114 announcements
                                            in the first nine days of October
  BOARDMTG      corporate-board-meetings    a dated FEED, and the one free
                                            source that names an industry
                                            (sm_indusrty) for small companies

Archived exactly like src/archive/corporate_actions.py — bytes as served,
gzipped, sha256-deduplicated, one manifest row per fetch — and parsed
separately. The rows carry no session_date: these are filings, not trading
sessions, and the digest counts sessions (the SHP lesson, 2026-09-23).

    RESEARCH_ENV=prod .venv/bin/python -m src.archive.nse_filings                # nightly: pledges + last 7 days
    RESEARCH_ENV=prod .venv/bin/python -m src.archive.nse_filings --start 2024-01-01   # backfill feeds
"""

from __future__ import annotations

import gzip
import json
import sys
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.archive import corporate_actions as ca  # noqa: E402
from src.common.hashing import hash_bytes  # noqa: E402
from src.common.paths import ARCHIVE  # noqa: E402

API = "https://www.nseindia.com/api/"
FEEDS = {
    "ANNOUNCE": ("nse_announcements", "corporate-announcements?index=equities&from_date={frm}&to_date={to}",
                 "https://www.nseindia.com/companies-listing/corporate-filings-announcements", 7),
    "BOARDMTG": ("nse_board_meetings", "corporate-board-meetings?index=equities&from_date={frm}&to_date={to}",
                 "https://www.nseindia.com/companies-listing/corporate-filings-board-meetings", 60),
}
PLEDGE = ("nse_pledges", "corporate-pledgedata?index=equities",
          "https://www.nseindia.com/companies-listing/corporate-filings-pledged-data")


def _path(report: str, stamp: str, digest: str) -> Path:
    return ARCHIVE / report / "NSE" / f"year={stamp[:4]}" / f"{report}_NSE_{stamp.replace('-', '')}_{digest[:8]}.json.gz"


def _store(op, report: str, source_id: str, url: str, referer: str, stamp: str, extra: dict) -> dict:
    base = {"source_id": source_id, "exchange": "NSE", "report_type": report, "url": url,
            "fetched_at": datetime.now(UTC).isoformat(), **extra}
    try:
        body = ca._get(op, url, referer)
    except Exception as exc:  # noqa: BLE001 - the record is the deliverable
        return {**base, "status": "FAILED", "error": str(exc)[:200]}
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return {**base, "status": "FAILED", "bytes": len(body), "error": "not JSON (session likely not warmed)"}
    rows = payload if isinstance(payload, list) else payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return {**base, "status": "FAILED", "bytes": len(body), "error": f"no row list ({type(payload).__name__})"}
    digest = hash_bytes(body)
    entry = {**base, "sha256": digest, "bytes": len(body), "records": len(rows)}
    if (prior := ca._seen(digest)) is not None:
        return {**entry, "status": "DUPLICATE", "path": prior}
    dest = _path(report, stamp, digest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".partial")
    with gzip.open(tmp, "wb") as fh:
        fh.write(body)
    tmp.rename(dest)
    return {**entry, "status": "STORED", "path": str(dest)}


def windows(start: date, end: date, days: int) -> list[tuple[date, date]]:
    out, a = [], start
    while a <= end:
        b = min(a + timedelta(days=days - 1), end)
        out.append((a, b))
        a = b + timedelta(days=1)
    return out


def collect(start: date | None = None, end: date | None = None, max_minutes: float = 30,
            only: str | None = None) -> list[dict]:
    end = end or datetime.now(UTC).date()
    start = start or end - timedelta(days=7)
    t0 = time.monotonic()
    op = ca._opener()
    try:
        ca._get(op, ca.WARMUP, "https://www.google.com/")
    except Exception as exc:  # noqa: BLE001
        print(f"  warmup failed (continuing): {exc}")
    out = []
    if only in (None, "PLEDGE"):
        sid, path, ref = PLEDGE
        e = _store(op, "PLEDGE", sid, API + path, ref, end.isoformat(), {"snapshot_of": end.isoformat()})
        ca.record(e)
        out.append(e)
    for report, (sid, path, ref, span) in FEEDS.items():
        if only not in (None, report):
            continue
        for a, b in windows(start, end, span):
            if time.monotonic() - t0 > max_minutes * 60:
                out.append({"report_type": report, "status": "STOPPED", "error": "time cap"})
                return out
            time.sleep(ca.RATE_LIMIT)
            url = API + path.format(frm=f"{a:%d-%m-%Y}", to=f"{b:%d-%m-%Y}")
            e = _store(op, report, sid, url, ref, a.isoformat(),
                       {"window_from": a.isoformat(), "window_to": b.isoformat()})
            ca.record(e)
            out.append(e)
    return out


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=date.fromisoformat, default=None)
    ap.add_argument("--max-minutes", type=float, default=30)
    ap.add_argument("--only", choices=["PLEDGE", *FEEDS], default=None, help="one feed, for a backfill")
    a = ap.parse_args()
    res = collect(a.start, max_minutes=a.max_minutes, only=a.only)
    from collections import Counter
    for report in ("PLEDGE", *FEEDS):
        rs = [r for r in res if r.get("report_type") == report]
        c = Counter(r["status"] for r in rs)
        print(f"  {report:<9} {dict(c)}  {sum(r.get('records', 0) for r in rs):,} records")
    failed = [r for r in res if r["status"] == "FAILED"]
    for r in failed[:3]:
        print(f"    FAILED {r.get('url', '')[:80]}: {r.get('error', '')[:100]}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
