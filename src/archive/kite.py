"""kite.py — daily candles from Zerodha Kite Connect, for a one-month audit.

WHY (2026-10-09). The owner holds 500 Kite Connect credits: one month of the
paid plan, which carries historical candles. Not enough for a standing source;
enough for two one-off jobs: an independent check of `price_spine_adj`
against a second vendor (src/research/price_audit.py), and the full-series gap
2026-06-26 .. August that no full bhavcopy covers (listing_history.py).

WHAT IT CANNOT DO. Kite serves only instruments that trade today: no delisted
company has history here, so nothing from Kite may enter a study panel — that
would be survivorship bias by construction. It carries no deal files.

CREDENTIALS. Never in the repo (it is public), never in a log, never in chat:
    ~/.micc_kite        KITE_API_KEY=... / KITE_API_SECRET=...   mode 600, the owner writes it
    ~/.micc_kite_token  today's access token, written by scripts/kite_login.py, mode 600
A Kite access token expires daily; a run with yesterday's token refuses rather
than failing 2,000 requests one by one.

STORAGE. Raw responses, gzipped, under data/raw/archive/KITE (git-ignored;
Kite's terms are personal use, no redistribution), with their OWN manifest:
the main manifest feeds health, the digest and the run report, and SHP rows
there were once miscounted as sessions.

    RESEARCH_ENV=prod .venv/bin/python -m src.archive.kite --max-minutes 50
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import os
import stat
import sys
import time
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.common.paths import ARCHIVE  # noqa: E402

API = "https://api.kite.trade"
LOGIN = "https://kite.zerodha.com/connect/login?v=3&api_key={key}"
CRED = Path.home() / ".micc_kite"
TOKEN = Path.home() / ".micc_kite_token"
ROOT_DIR = ARCHIVE / "KITE"
MANIFEST = ROOT_DIR / "manifest.jsonl"
IST = timezone(timedelta(hours=5, minutes=30))

#: Kite's historical endpoint: 3 requests/second; a "day" request spans at
#: most 2,000 days. Kept under both.
MIN_GAP_S = 0.4
DAY_SPAN = 1900
START = date(2005, 1, 1)
#: Equity series only. Kite lists ~10,200 NSE "EQ"-type instruments and more
#: than half are government securities (SG state loans, GS, TB T-bills, GB)
#: and bond series — measured 2026-10-09, after the first 459 pulls were
#: mostly state loans.
SERIES = frozenset({"EQ", "BE", "BZ", "SM", "ST"})
TIMEOUT = 30


class KiteAuthError(RuntimeError):
    """Missing, unreadable or stale credentials. Never carries a secret."""


def _private(path: Path) -> None:
    """Refuse a credential file anyone else can read."""
    if path.stat().st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise KiteAuthError(f"{path} is readable by others; run: chmod 600 {path}")


def creds(path: Path = CRED) -> tuple[str, str]:
    if not path.exists():
        raise KiteAuthError(f"{path} not found (KITE_API_KEY=..., KITE_API_SECRET=...; chmod 600)")
    _private(path)
    kv = dict(ln.split("=", 1) for ln in path.read_text().splitlines() if "=" in ln)
    key, secret = kv.get("KITE_API_KEY", "").strip(), kv.get("KITE_API_SECRET", "").strip()
    if not key or not secret:
        raise KiteAuthError(f"{path} lacks KITE_API_KEY or KITE_API_SECRET")
    return key, secret


def today_ist() -> date:
    return datetime.now(IST).date()


def access_token(path: Path = TOKEN, today: date | None = None) -> str:
    if not path.exists():
        raise KiteAuthError("no access token; run: .venv/bin/python scripts/kite_login.py")
    _private(path)
    d = json.loads(path.read_text())
    if d.get("date") != (today or today_ist()).isoformat():
        raise KiteAuthError(f"the access token is from {d.get('date')}; Kite tokens expire daily — "
                            "run: .venv/bin/python scripts/kite_login.py")
    return d["access_token"]


def checksum(key: str, request_token: str, secret: str) -> str:
    """Kite's session checksum: sha256(api_key + request_token + api_secret)."""
    return hashlib.sha256((key + request_token + secret).encode()).hexdigest()


def write_token(access: str, path: Path = TOKEN, today: date | None = None) -> None:
    """Written with mode 600 from the first byte, never world-readable."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        json.dump({"access_token": access, "date": (today or today_ist()).isoformat()}, fh)
    os.chmod(path, 0o600)


class Client:
    def __init__(self, key: str, access: str, opener=urlopen):
        self._auth = f"token {key}:{access}"
        self._open = opener
        self._last = 0.0

    def get(self, path: str, params: dict | None = None, retries: int = 4) -> bytes:
        url = f"{API}{path}" + (f"?{urlencode(params)}" if params else "")
        last: Exception | None = None
        for attempt in range(retries):
            wait = MIN_GAP_S - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            try:
                req = Request(url, headers={"X-Kite-Version": "3", "Authorization": self._auth})
                with self._open(req, timeout=TIMEOUT) as r:
                    return r.read()
            except HTTPError as e:
                if e.code in (401, 403):
                    raise KiteAuthError(f"Kite refused the token (HTTP {e.code}); log in again") from None
                last = e
                if e.code not in (429, 500, 502, 503, 504):
                    break
            except (URLError, TimeoutError) as e:
                last = e
            time.sleep(2 ** attempt)
        # The URL carries no secret (auth is a header), so it is safe to name.
        raise RuntimeError(f"{path}: {type(last).__name__}: {str(last)[:120]}")


def instruments(c: Client) -> tuple[bytes, list[dict]]:
    """NSE cash instruments (EQ type, every series suffix: -BE, -BZ ...)."""
    body = c.get("/instruments/NSE")
    rows = [r for r in csv.DictReader(io.StringIO(body.decode("utf-8", "replace")))
            if r.get("segment") == "NSE" and r.get("instrument_type") == "EQ"
            and series_of(r.get("tradingsymbol", ""))[1] in SERIES]
    return body, rows


def series_of(tradingsymbol: str) -> tuple[str, str]:
    """('ABC', 'EQ') for ABC; ('ABC', 'BE') for ABC-BE. Kite names a non-EQ
    series by suffix on the same symbol."""
    sym, _, ser = tradingsymbol.rpartition("-")
    if sym and ser.isalpha() and len(ser) == 2:
        return sym, ser
    return tradingsymbol, "EQ"


def candles(c: Client, token: int, start: date, end: date) -> list[list]:
    out: list[list] = []
    a = start
    while a <= end:
        b = min(a + timedelta(days=DAY_SPAN), end)
        body = json.loads(c.get(f"/instruments/historical/{token}/day",
                                {"from": f"{a} 00:00:00", "to": f"{b} 23:59:59"}))
        out += body.get("data", {}).get("candles", [])
        a = b + timedelta(days=1)
    return out


def _path(kind: str, name: str, stamp: date) -> Path:
    return ROOT_DIR / kind / f"year={stamp.year}" / f"{name}_{stamp:%Y%m%d}.json.gz"


def record(entry: dict, manifest: Path | None = None) -> None:
    # Resolved at call time, not in the signature: a default bound at import
    # ignores a patched MANIFEST (the runreport.py lesson, 2026-09).
    manifest = manifest or MANIFEST
    manifest.parent.mkdir(parents=True, exist_ok=True)
    with manifest.open("a") as fh:
        fh.write(json.dumps(entry, sort_keys=True) + "\n")


def done_today(stamp: date, manifest: Path | None = None) -> set[int]:
    """Instrument tokens already pulled through `stamp` — the run resumes."""
    manifest = manifest or MANIFEST
    if not manifest.exists():
        return set()
    out = set()
    for ln in manifest.read_text().splitlines():
        r = json.loads(ln)
        if r.get("kind") == "candles" and r.get("status") == "STORED" and r.get("end") == stamp.isoformat():
            out.add(int(r["instrument_token"]))
    return out


def pull(c: Client, end: date, max_minutes: float = 50, start: date = START,
         only: set[str] | None = None) -> dict:
    t0 = time.monotonic()
    body, rows = instruments(c)
    p = _path("instruments", "NSE", today_ist())
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(gzip.compress(body))
    rows = [r for r in rows if only is None or series_of(r["tradingsymbol"])[0] in only]
    have = done_today(end)
    todo = [r for r in rows if int(r["instrument_token"]) not in have]
    stats = {"instruments": len(rows), "already": len(rows) - len(todo), "stored": 0, "failed": 0,
             "stopped": False}
    for r in todo:
        if time.monotonic() - t0 > max_minutes * 60:
            stats["stopped"] = True
            break
        tok = int(r["instrument_token"])
        sym, ser = series_of(r["tradingsymbol"])
        entry = {"kind": "candles", "instrument_token": tok, "tradingsymbol": r["tradingsymbol"],
                 "symbol": sym, "series": ser, "start": start.isoformat(), "end": end.isoformat(),
                 "fetched_at": datetime.now(UTC).isoformat()}
        try:
            cs = candles(c, tok, start, end)
        except KiteAuthError:
            raise
        except Exception as e:  # noqa: BLE001 - one instrument's failure is recorded, not fatal
            record({**entry, "status": "FAILED", "error": str(e)[:200]})
            stats["failed"] += 1
            continue
        raw = json.dumps({"tradingsymbol": r["tradingsymbol"], "instrument_token": tok,
                          "candles": cs}).encode()
        out = _path("candles", f"{tok}_{r['tradingsymbol'].replace('/', '_')}", end)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(gzip.compress(raw))
        record({**entry, "status": "STORED", "rows": len(cs), "path": str(out),
                "sha256": hashlib.sha256(raw).hexdigest()})
        stats["stored"] += 1
    return stats


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-minutes", type=float, default=50)
    ap.add_argument("--symbols", default="", help="comma-separated, for a trial run")
    a = ap.parse_args()
    try:
        key, _ = creds()
        c = Client(key, access_token())
        end = today_ist() - timedelta(days=1)
        only = {s.strip().upper() for s in a.symbols.split(",") if s.strip()} or None
        st = pull(c, end, a.max_minutes, only=only)
    except KiteAuthError as e:
        print(f"  KITE: {e}")
        return 1
    print(f"  KITE: {st['instruments']:,} instruments; {st['already']:,} already through {end}; "
          f"{st['stored']:,} stored, {st['failed']:,} failed" + ("; STOPPED at the time cap" if st["stopped"] else ""))
    return 0 if not st["failed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
