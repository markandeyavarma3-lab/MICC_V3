"""results.py — every listed company's quarterly financial results, as XBRL.

WHY (2026-10-10). Part B of the site plan (docs/plan/WEBSITE_PLAN.md):
revenue, profit, EPS and margins per company per quarter. NSE serves them per
symbol on two routes, measured that day:

  corporates-financial-results  the pre-2025 filings (TCS: 162 rows, newest
                                for the quarter to 2024-12-31)
  integrated-filing-results     2025 onward, after SEBI's integrated filing
                                (TCS: the quarter to 2026-09-30, filed 08-Oct)

Each row points at an XBRL file on nsearchives. One company is ~40 quarters x
standalone/consolidated, so the whole history is ~100,000 files: far more than
a night allows. This is a RESUMABLE SWEEP like src/archive/shp.py — listings
first, then the newest QUARTERS quarter-ends per company (consolidated when
filed, else standalone; the latest revision), within a per-run budget and a
wall-clock cap — and it never fetches a file twice.

ITS OWN MANIFEST (ARCHIVE/RESULTS/manifest.jsonl). Tens of thousands of rows
in the main manifest would sit in front of the health check and the digest,
which count sessions; these are filings (the SHP lesson, 2026-09-23).

    RESEARCH_ENV=prod .venv/bin/python -m src.archive.results --max-files 2500 --max-minutes 120
"""

from __future__ import annotations

import gzip
import hashlib
import json
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.archive import corporate_actions as ca  # noqa: E402
from src.common.paths import ARCHIVE  # noqa: E402

ROOT_DIR = ARCHIVE / "RESULTS"
MANIFEST = ROOT_DIR / "manifest.jsonl"
API = "https://www.nseindia.com/api/"
OLD = "corporates-financial-results?index=equities&symbol={sym}&period=Quarterly"
NEW = "integrated-filing-results?index=equities&symbol={sym}"
REFERER = "https://www.nseindia.com/companies-listing/corporate-integrated-filing"
QUARTERS = 8
LISTING_FRESH_DAYS = 20
RATE_LIMIT = 1.5
BREAKER = 6


def record(entry: dict, manifest: Path | None = None) -> None:
    manifest = manifest or MANIFEST
    manifest.parent.mkdir(parents=True, exist_ok=True)
    with manifest.open("a") as fh:
        fh.write(json.dumps(entry, sort_keys=True) + "\n")


def state(manifest: Path | None = None) -> tuple[dict[str, str], set[str]]:
    """(symbol -> last listing fetch time, urls already STORED)."""
    manifest = manifest or MANIFEST
    listed: dict[str, str] = {}
    stored: set[str] = set()
    if manifest.exists():
        for ln in manifest.read_text().splitlines():
            try:
                r = json.loads(ln)
            except json.JSONDecodeError:
                continue
            if r.get("kind") == "listing" and r.get("status") == "STORED":
                listed[r["symbol"]] = max(listed.get(r["symbol"], ""), r["fetched_at"])
            elif r.get("kind") == "xbrl" and r.get("status") == "STORED":
                stored.add(r["url"])
    return listed, stored


def _d(s: str | None) -> str | None:
    for fmt in ("%d-%b-%Y", "%d-%b-%Y %H:%M:%S", "%d-%B-%Y"):
        try:
            return datetime.strptime((s or "").strip().title(), fmt).date().isoformat()
        except ValueError:
            continue
    return None


def targets(old_rows: list[dict], new_rows: list[dict], quarters: int = QUARTERS) -> list[dict]:
    """The filings to fetch: per quarter-end, the latest consolidated filing
    if there is one, else the latest standalone; the newest `quarters`
    quarter-ends. Pure, so the choice is testable."""
    cand: list[dict] = []
    for r in old_rows:
        qe, bd = _d(r.get("toDate")), r.get("broadCastDate") or ""
        if qe and r.get("xbrl") and r.get("period", "Quarterly") == "Quarterly":
            cand.append({"qe": qe, "cons": r.get("consolidated") == "Consolidated", "url": r["xbrl"],
                         "filed": _d(bd.split(" ")[0]) or "", "route": "old"})
    for r in new_rows:
        qe, bd = _d(r.get("qe_Date")), r.get("broadcast_Date") or ""
        if qe and r.get("xbrl") and "Financial" in (r.get("type") or "Financial"):
            cand.append({"qe": qe, "cons": r.get("consolidated") == "Consolidated", "url": r["xbrl"],
                         "filed": _d(bd.split(" ")[0]) or "", "route": "new"})
    best: dict[str, dict] = {}
    for c in cand:
        b = best.get(c["qe"])
        if b is None or (c["cons"], c["filed"]) > (b["cons"], b["filed"]):
            best[c["qe"]] = c
    return [best[q] for q in sorted(best, reverse=True)[:quarters]]


def _rows(body: bytes) -> list[dict]:
    d = json.loads(body)
    rows = d if isinstance(d, list) else d.get("data") if isinstance(d, dict) else None
    if not isinstance(rows, list):
        raise ValueError(f"no row list ({type(d).__name__})")
    return rows


def _save(kind: str, name: str, body: bytes) -> Path:
    digest = hashlib.sha256(body).hexdigest()
    dest = ROOT_DIR / kind / f"{name}_{digest[:8]}.gz"
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists():
        tmp = dest.with_suffix(".partial")
        tmp.write_bytes(gzip.compress(body))
        tmp.rename(dest)
    return dest


def sweep(symbols: list[str], max_files: int = 2500, max_minutes: float = 120,
          quarters: int = QUARTERS) -> dict:
    t0 = time.monotonic()
    listed, stored = state()
    fresh = (datetime.now(UTC) - timedelta(days=LISTING_FRESH_DAYS)).isoformat()
    # Never-listed companies first, then the stalest listing.
    order = sorted(symbols, key=lambda s: listed.get(s, ""))
    op = ca._opener()
    st = {"symbols": 0, "listings": 0, "files": 0, "failed": 0, "stopped": ""}
    streak = 0
    for sym in order:
        if time.monotonic() - t0 > max_minutes * 60:
            st["stopped"] = "time cap"
            break
        if st["files"] >= max_files:
            st["stopped"] = "file budget"
            break
        st["symbols"] += 1
        lists: dict[str, list] = {"old": [], "new": []}
        if listed.get(sym, "") < fresh:
            for route, path in (("old", OLD), ("new", NEW)):
                time.sleep(RATE_LIMIT)
                url = API + path.format(sym=sym)
                base = {"kind": "listing", "symbol": sym, "route": route, "url": url,
                        "fetched_at": datetime.now(UTC).isoformat()}
                try:
                    body = ca._get(op, url, REFERER)
                    lists[route] = _rows(body)
                    dest = _save("listings", f"{sym}_{route}", body)
                    record({**base, "status": "STORED", "rows": len(lists[route]), "path": str(dest)})
                    st["listings"] += 1
                    streak = 0
                except Exception as e:  # noqa: BLE001 - recorded, and the breaker counts it
                    record({**base, "status": "FAILED", "error": str(e)[:200]})
                    st["failed"] += 1
                    streak += 1
        else:
            lists = latest_listings(sym)
        if streak >= BREAKER:
            st["stopped"] = f"{streak} consecutive failures"
            break
        for t in targets(lists["old"], lists["new"], quarters):
            if t["url"] in stored or st["files"] >= max_files:
                continue
            time.sleep(RATE_LIMIT)
            base = {"kind": "xbrl", "symbol": sym, "qe": t["qe"], "consolidated": t["cons"], "route": t["route"],
                    "filed": t["filed"], "url": t["url"], "fetched_at": datetime.now(UTC).isoformat()}
            try:
                body = ca._get(op, t["url"], REFERER)
                if b"<" not in body[:200]:
                    raise ValueError("not XML")
                dest = _save(f"xbrl/year={t['qe'][:4]}", f"{sym}_{t['qe']}_{'C' if t['cons'] else 'S'}", body)
                record({**base, "status": "STORED", "bytes": len(body), "path": str(dest)})
                stored.add(t["url"])
                st["files"] += 1
                streak = 0
            except Exception as e:  # noqa: BLE001
                record({**base, "status": "FAILED", "error": str(e)[:200]})
                st["failed"] += 1
                streak += 1
                if streak >= BREAKER:
                    st["stopped"] = f"{streak} consecutive failures"
                    return st
    return st


def latest_listings(sym: str) -> dict[str, list]:
    """The newest archived listing per route for one symbol."""
    out: dict[str, list] = {"old": [], "new": []}
    for route in out:
        fs = sorted((ROOT_DIR / "listings").glob(f"{sym}_{route}_*.gz"), key=lambda p: p.stat().st_mtime)
        if fs:
            try:
                out[route] = _rows(gzip.decompress(fs[-1].read_bytes()))
            except (OSError, ValueError):
                pass
    return out


def main() -> int:
    import argparse

    from src.archive.shp import universe
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-files", type=int, default=2500)
    ap.add_argument("--max-minutes", type=float, default=120)
    ap.add_argument("--quarters", type=int, default=QUARTERS)
    ap.add_argument("--symbols", default="")
    a = ap.parse_args()
    syms = [s.strip().upper() for s in a.symbols.split(",") if s.strip()] or universe()
    st = sweep(syms, a.max_files, a.max_minutes, a.quarters)
    _, stored = state()
    print(f"  RESULTS: {st['symbols']:,} symbols, {st['listings']:,} listings, {st['files']:,} XBRL stored, "
          f"{st['failed']:,} failed{'; stopped: ' + st['stopped'] if st['stopped'] else ''}; {len(stored):,} held in all")
    return 0 if not st["failed"] or st["files"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
