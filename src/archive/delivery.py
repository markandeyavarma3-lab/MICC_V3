"""delivery.py — NSE's security-wise delivery position, every session since 2006.

WHY (2026-10-16). The price spine holds open/high/low/close/volume; it does not
say how much of a day's volume was DELIVERED rather than squared off intraday —
the standard Indian measure of how much of the trading was real position-
taking. NSE publishes it per session in the MTO file on its static archive
host. Measured 2026-10-16: served from 2006-01-03 to the latest session (the
newer sec_bhavdata_full carries the same two columns but only from 2020).

  archives/equities/mto/MTO_DDMMYYYY.DAT
    Record Type 20: Sr No, Name of Security, series, Quantity Traded,
    Deliverable Quantity (gross across client level), % Deliverable

Archived as served (gzipped, one manifest row per session, its own manifest
like the results and fund archives) and parsed to
collected/delivery/delivery.parquet. A session without a file (a holiday the
spine does not hold, or a 404) is recorded MISSING and not retried.

    RESEARCH_ENV=prod .venv/bin/python -m src.archive.delivery --max-minutes 120     # backfill / nightly
"""

from __future__ import annotations

import gzip
import hashlib
import json
import sys
import time
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.common.paths import ARCHIVE, COLLECTED, warehouse_dir  # noqa: E402

ROOT_DIR = ARCHIVE / "DELIVERY"
MANIFEST = ROOT_DIR / "manifest.jsonl"
OUT = COLLECTED / "delivery" / "delivery.parquet"
URL = "https://nsearchives.nseindia.com/archives/equities/mto/MTO_{d:%d%m%Y}.DAT"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36"
FIRST = date(2006, 1, 2)
RATE_LIMIT = 0.8
BREAKER = 8


def record(entry: dict, manifest: Path | None = None) -> None:
    manifest = manifest or MANIFEST
    manifest.parent.mkdir(parents=True, exist_ok=True)
    with manifest.open("a") as fh:
        fh.write(json.dumps(entry, sort_keys=True) + "\n")


def done(manifest: Path | None = None) -> set[str]:
    manifest = manifest or MANIFEST
    out: set[str] = set()
    if manifest.exists():
        for ln in manifest.read_text().splitlines():
            try:
                r = json.loads(ln)
            except json.JSONDecodeError:
                continue
            if r.get("status") in ("STORED", "MISSING"):
                out.add(r["session"])
    return out


def sessions(env: str | None = None) -> list[date]:
    """The sessions the price spine holds, newest first (a cut-short run fills
    the recent years first)."""
    import duckdb
    spine = str(warehouse_dir(env) / "price_spine" / "**" / "*.parquet")
    con = duckdb.connect()
    try:
        return [r[0] for r in con.execute(
            f"SELECT DISTINCT CAST(date AS DATE) d FROM read_parquet('{spine}', hive_partitioning=true) "
            f"WHERE CAST(date AS DATE) >= DATE '{FIRST}' ORDER BY 1 DESC").fetchall()]
    finally:
        con.close()


def parse(text: str) -> list[tuple]:
    """MTO body -> (symbol, series, traded_qty, deliverable_qty, deliverable_pct). Pure."""
    out = []
    for ln in text.splitlines():
        p = [x.strip() for x in ln.split(",")]
        if len(p) >= 7 and p[0] == "20":
            try:
                out.append((p[2].upper(), p[3].upper(), float(p[4]), float(p[5]), float(p[6])))
            except ValueError:
                continue
    return out


def sweep(max_minutes: float = 120) -> dict:
    t0 = time.monotonic()
    have = done()
    st = {"stored": 0, "missing": 0, "failed": 0, "stopped": ""}
    streak = 0
    for d in sessions():
        if d.isoformat() in have:
            continue
        if time.monotonic() - t0 > max_minutes * 60:
            st["stopped"] = "time cap"
            break
        time.sleep(RATE_LIMIT)
        url = URL.format(d=d)
        base = {"session": d.isoformat(), "url": url, "fetched_at": datetime.now(UTC).isoformat()}
        try:
            with urlopen(Request(url, headers={"User-Agent": UA}), timeout=60) as r:  # noqa: S310
                body = r.read()
            if b"Delivery Position" not in body[:300]:
                raise ValueError(f"not a delivery file ({len(body)} bytes)")
            digest = hashlib.sha256(body).hexdigest()
            dest = ROOT_DIR / f"year={d.year}" / f"MTO_{d:%Y%m%d}_{digest[:8]}.DAT.gz"
            dest.parent.mkdir(parents=True, exist_ok=True)
            if not dest.exists():
                tmp = dest.with_suffix(".partial")
                tmp.write_bytes(gzip.compress(body))
                tmp.rename(dest)
            record({**base, "status": "STORED", "sha256": digest, "bytes": len(body), "path": str(dest),
                    "rows": len(parse(body.decode("latin-1")))})
            st["stored"] += 1
            streak = 0
        except HTTPError as e:
            if e.code == 404:
                record({**base, "status": "MISSING", "error": "HTTP 404"})
                st["missing"] += 1
                continue
            record({**base, "status": "FAILED", "error": f"HTTP {e.code}"})
            st["failed"] += 1
            streak += 1
        except Exception as e:  # noqa: BLE001
            record({**base, "status": "FAILED", "error": str(e)[:200]})
            st["failed"] += 1
            streak += 1
        if streak >= BREAKER:
            st["stopped"] = f"{streak} consecutive failures"
            break
    return st


def ingest() -> int:
    """Every stored file -> collected/delivery/delivery.parquet (one row per session, symbol, series)."""
    import duckdb
    rows = []
    for ln in MANIFEST.read_text().splitlines() if MANIFEST.exists() else []:
        r = json.loads(ln)
        if r.get("status") != "STORED":
            continue
        try:
            text = gzip.decompress(Path(r["path"]).read_bytes()).decode("latin-1")
        except OSError:
            continue
        rows.extend((r["session"], *x) for x in parse(text))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    try:
        con.execute("CREATE TABLE t (date VARCHAR, symbol VARCHAR, series VARCHAR, traded_qty DOUBLE,"
                    " deliverable_qty DOUBLE, deliverable_pct DOUBLE)")
        con.executemany("INSERT INTO t VALUES (?,?,?,?,?,?)", rows)
        tmp = OUT.with_suffix(".parquet.partial")
        con.execute(f"COPY (SELECT DISTINCT * FROM t ORDER BY date, symbol, series) TO '{tmp}' (FORMAT PARQUET)")
        tmp.replace(OUT)
    finally:
        con.close()
    return len(rows)


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-minutes", type=float, default=120)
    a = ap.parse_args()
    st = sweep(a.max_minutes)
    n = ingest()
    print(f"  DELIVERY: {st['stored']} sessions stored, {st['missing']} missing, {st['failed']} failed"
          f"{'; stopped: ' + st['stopped'] if st['stopped'] else ''}; {len(done())} of {len(sessions())} sessions "
          f"held; {n:,} rows -> {OUT.name}")
    return 0 if st["stored"] or not st["failed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
