"""probe.py — try a public route, archive the bytes only if the payload is real.

One function, `probe()`, for routes that are not yet a feed. It fetches with
the project's UA and rate limit, requires the caller to say what a real
payload looks like (`validate`), and writes the SAME manifest record and the
SAME archive layout as `src/archive/derivatives.py` — a probe that stored
bytes is a first session of a feed, not a side file.

A 200 that is HTML, `[]`, `{"Table":[]}` or an error page is FAILED with the
first 80 bytes recorded (decision 0024: a retired endpoint answered 200 with an
empty envelope for weeks and every count looked healthy). Nothing here parses
into the warehouse.
"""

from __future__ import annotations

import gzip
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.archive.derivatives import (  # noqa: E402
    BACKOFF_BASE, RATE_LIMIT, RETRIES, TIMEOUT, UA, record,
)
from src.common.hashing import hash_bytes  # noqa: E402
from src.common.paths import ARCHIVE  # noqa: E402

_last_call = 0.0


def _rate_limit() -> None:
    global _last_call
    wait = RATE_LIMIT - (time.monotonic() - _last_call)
    if wait > 0:
        time.sleep(wait)
    _last_call = time.monotonic()


def fetch(url: str, headers: dict | None = None, data: bytes | None = None,
          retries: int = 1) -> tuple[int | None, bytes, str]:
    """(status, body, error). Never raises. Rate-limited to RATE_LIMIT."""
    hdrs = {"User-Agent": UA, "Accept": "*/*", **(headers or {})}
    err, body, status = "", b"", None
    for attempt in range(retries):
        _rate_limit()
        req = urllib.request.Request(url, headers=hdrs, data=data)
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                return r.status, r.read(), ""
        except urllib.error.HTTPError as e:
            status = e.code
            try:
                body = e.read()[:2000]
            except Exception:  # noqa: BLE001
                body = b""
            err = f"HTTP {e.code} {e.reason}"
            if e.code in (301, 302, 403, 404, 503):
                break
        except Exception as e:  # noqa: BLE001
            err = f"{type(e).__name__}: {e}"
        if attempt < retries - 1:
            time.sleep(BACKOFF_BASE * (attempt + 1))
    return status, body, err


def archive_path(report_type: str, exchange: str, session: date, digest: str,
                 suffix: str) -> Path:
    name = f"{report_type}_{exchange}_{session:%Y%m%d}_{digest[:8]}{suffix}"
    return (ARCHIVE / report_type / exchange
            / f"year={session:%Y}" / f"month={session:%m}" / name)


def probe(*, source_id: str, exchange: str, report_type: str, url: str,
          session: date, validate: Callable[[bytes], str | None],
          suffix: str = ".csv.gz", headers: dict | None = None,
          data: bytes | None = None, dry_run: bool = False) -> dict:
    """Fetch `url`; if `validate(body)` returns None the bytes are archived and
    a STORED record appended to the manifest. `validate` returns a short reason
    string when the payload is not real. With `dry_run` nothing is written or
    recorded; the dict is still returned."""
    base = {"source_id": source_id, "exchange": exchange, "report_type": report_type,
            "session_date": session.isoformat(), "url": url,
            "fetched_at": datetime.now(UTC).isoformat()}
    status, body, err = fetch(url, headers=headers, data=data)
    head = body[:80].decode("utf-8", "replace") if body else ""
    if status != 200:
        out = {**base, "status": "FAILED", "http": status, "error": err or f"HTTP {status}",
               "head": head}
        if not dry_run:
            record(out)
        return out
    reason = validate(body)
    if reason:
        out = {**base, "status": "FAILED", "http": 200, "bytes": len(body),
               "error": f"200 but not a real payload: {reason}", "head": head}
        if not dry_run:
            record(out)
        return out
    digest = hash_bytes(body)
    dest = archive_path(report_type, exchange, session, digest, suffix)
    if dest.exists():
        out = {**base, "status": "DUPLICATE", "http": 200, "sha256": digest, "bytes": len(body)}
        if not dry_run:
            record(out)
        return out
    if not dry_run:
        dest.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(dest, "wb") as fh:
            fh.write(body)
    out = {**base, "status": "STORED", "http": 200, "sha256": digest, "bytes": len(body),
           "path": str(dest.relative_to(ARCHIVE))}
    if not dry_run:
        record(out)
    return out


# --- validators ---------------------------------------------------------------

def csv_with_header(*must_contain: str, min_rows: int = 1) -> Callable[[bytes], str | None]:
    """Real if text, first line contains every token, and at least min_rows data rows."""
    def _v(body: bytes) -> str | None:
        if not body:
            return "empty body"
        if body[:1] in (b"<", b"{", b"["):
            return "HTML/JSON where CSV expected"
        text = body.decode("utf-8", "replace")
        lines = [ln for ln in text.splitlines() if ln.strip()]
        if not lines:
            return "no lines"
        hdr = lines[0]
        missing = [t for t in must_contain if t.lower() not in hdr.lower()]
        if missing:
            return f"header lacks {missing}: {hdr[:80]!r}"
        if len(lines) - 1 < min_rows:
            return f"{len(lines) - 1} data rows (< {min_rows})"
        return None
    return _v


def json_nonempty_list(key: str | None = None, min_items: int = 1) -> Callable[[bytes], str | None]:
    def _v(body: bytes) -> str | None:
        import json
        if not body:
            return "empty body"
        if body[:1] == b"<":
            return "HTML where JSON expected"
        try:
            obj = json.loads(body)
        except json.JSONDecodeError:
            return "not JSON"
        items = obj.get(key) if (key and isinstance(obj, dict)) else obj
        if not isinstance(items, list):
            return f"no list at {key!r}: {type(items).__name__}"
        if len(items) < min_items:
            return f"{len(items)} items (< {min_items})"
        return None
    return _v
