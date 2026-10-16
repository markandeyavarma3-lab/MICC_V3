"""bse_shp.py — the shareholding-pattern XBRL from before NSE's window, from BSE.

WHY (2026-10-16). NSE's shareholding master lists filings from 2021-09-30
only (src/archive/shp.py, measured 2026-09-17: the floor is the endpoint's
window, not listing age). So the project's holdings history is ~20 quarters,
and the mutual-fund holding-change question waits on time (0086: 1.12x short,
about 2028).

The predecessor's seed (`shp_filing.parquet`, carried under 0027) indexes
149,620 BSE shareholding filings, 2016 onward for ~3,600 companies a year,
each with its BROADCAST time and the URL of its original XBRL on BSE's static
host. Measured 2026-10-16: BSE still serves those files, in the same
`in-bse-shp` taxonomy NSE's carry, with the mutual-fund and foreign-portfolio
categories and the named holders inside. The seed's own category table holds
only the top-level splits; the detail was never parsed.

THIS FILE ARCHIVES, IT DOES NOT PARSE — like shp.py. Targets: the seed's
CURRENT filings with a quarter-end before 2021-09-30 (NSE covers the rest)
for companies in security_master: 36,993 files, 2,112 companies. A resumable
sweep with its own manifest; a file is fetched once; the breaker is for being
refused or cut off, not for a single missing file.

    RESEARCH_ENV=prod .venv/bin/python -m src.archive.bse_shp --max-files 3000 --max-minutes 120
"""

from __future__ import annotations

import gzip
import hashlib
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.common.paths import ARCHIVE, SEED, research_db  # noqa: E402

ROOT_DIR = ARCHIVE / "SHP_BSE"
MANIFEST = ROOT_DIR / "manifest.jsonl"
NSE_WINDOW_START = "2021-09-30"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/129.0 Safari/537.36")
RATE_LIMIT = 1.2
BREAKER = 8


def record(entry: dict, manifest: Path | None = None) -> None:
    manifest = manifest or MANIFEST
    manifest.parent.mkdir(parents=True, exist_ok=True)
    with manifest.open("a") as fh:
        fh.write(json.dumps(entry, sort_keys=True) + "\n")


def done(manifest: Path | None = None) -> set[str]:
    """filing_ids already STORED or permanently MISSING (a 404 is not retried)."""
    manifest = manifest or MANIFEST
    out: set[str] = set()
    if manifest.exists():
        for ln in manifest.read_text().splitlines():
            try:
                r = json.loads(ln)
            except json.JSONDecodeError:
                continue
            if r.get("status") in ("STORED", "MISSING"):
                out.add(r["filing_id"])
    return out


def targets(env: str | None = None) -> list[dict]:
    """The seed's current pre-NSE-window filings for known companies, newest
    quarter first (the most useful quarters land first if a run is cut short)."""
    import duckdb
    con = duckdb.connect(str(research_db(env)), read_only=True)
    try:
        rows = con.execute(f"""
            SELECT filing_id, isin, scrip_code, quarter_end_date, broadcast_datetime, source_url
            FROM read_parquet('{SEED / 'shp_filing.parquet'}')
            WHERE quarter_end_date < '{NSE_WINDOW_START}' AND is_current_version = 1
              AND source_url LIKE 'https://www.bseindia.com/%'
              AND isin IN (SELECT isin FROM security_master)
            ORDER BY quarter_end_date DESC, isin""").fetchall()
    finally:
        con.close()
    cols = ("filing_id", "isin", "scrip_code", "quarter_end", "broadcast", "url")
    return [dict(zip(cols, r, strict=True)) for r in rows]


def _get(url: str) -> bytes:
    req = Request(url, headers={"User-Agent": UA, "Referer": "https://www.bseindia.com/"})
    with urlopen(req, timeout=60) as r:  # noqa: S310 - fixed https host
        return r.read()


def sweep(max_files: int = 3000, max_minutes: float = 120) -> dict:
    t0 = time.monotonic()
    have = done()
    st = {"files": 0, "missing": 0, "failed": 0, "skipped": 0, "stopped": ""}
    streak = 0
    for t in targets():
        if t["filing_id"] in have:
            st["skipped"] += 1
            continue
        if st["files"] >= max_files:
            st["stopped"] = "file budget"
            break
        if time.monotonic() - t0 > max_minutes * 60:
            st["stopped"] = "time cap"
            break
        time.sleep(RATE_LIMIT)
        base = {k: t[k] for k in ("filing_id", "isin", "scrip_code", "quarter_end", "broadcast", "url")}
        base["fetched_at"] = datetime.now(UTC).isoformat()
        try:
            body = _get(t["url"])
            if b"in-bse-shp" not in body[:2000]:
                raise ValueError(f"not a shareholding XBRL ({len(body)} bytes)")
            digest = hashlib.sha256(body).hexdigest()
            dest = ROOT_DIR / f"year={t['quarter_end'][:4]}" / f"{t['isin']}_{t['quarter_end']}_{digest[:8]}.xml.gz"
            dest.parent.mkdir(parents=True, exist_ok=True)
            if not dest.exists():
                tmp = dest.with_suffix(".partial")
                tmp.write_bytes(gzip.compress(body))
                tmp.rename(dest)
            record({**base, "status": "STORED", "sha256": digest, "bytes": len(body), "path": str(dest)})
            st["files"] += 1
            streak = 0
        except HTTPError as e:
            if e.code == 404:
                record({**base, "status": "MISSING", "error": "HTTP 404"})
                st["missing"] += 1
                continue
            record({**base, "status": "FAILED", "error": f"HTTP {e.code}"})
            st["failed"] += 1
            streak += 1
        except Exception as e:  # noqa: BLE001 - recorded; the breaker counts it
            record({**base, "status": "FAILED", "error": str(e)[:200]})
            st["failed"] += 1
            streak += 1
        if streak >= BREAKER:
            st["stopped"] = f"{streak} consecutive failures"
            break
    return st


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-files", type=int, default=3000)
    ap.add_argument("--max-minutes", type=float, default=120)
    a = ap.parse_args()
    st = sweep(a.max_files, a.max_minutes)
    print(f"  BSE SHP: {st['files']:,} stored, {st['missing']} missing (404), {st['failed']} failed, "
          f"{st['skipped']:,} already held{'; stopped: ' + st['stopped'] if st['stopped'] else ''}; "
          f"{len(done()):,} of {len(targets()):,} done")
    return 0 if st["files"] or not st["failed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
