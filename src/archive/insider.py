"""insider.py — SEBI insider-trading filings, and the empty envelope that hid them.

WHY THIS SOURCE. [0046](../../docs/decisions/0046-the-data-we-already-have-is-better-powered.md)
measured promoter sells at **1.25x short** of their bound against bulk buys at
2.22x, consensus at 1.94x and disclosed selling at 1.95x. It is the closest
anything in this project has come, and the only gap that is closeable: 1.56x
more monthly cohorts is about five more years, against seventy for consensus.
The binding constraint is that the seed's insider data starts in 2016, so every
session collected from here is a cohort the study could not otherwise have.

THE FAILURE MODE THIS FILE IS BUILT AROUND, AND IT IS NOT HYPOTHETICAL.

`/api/corporates-pit` answers **HTTP 200** with a well-formed body:

    {"acqNameList":[],"data":[]}

NSE retired it around April 2026 and left it answering. MICC's own fetcher,
recovered from the bundle [0042](../../docs/decisions/0042-salvage-before-deleting-the-predecessors.md)
salvaged, records the consequence in its own words: it *"went silently
green-but-empty for ~2 months (last real row 2026-06-09)"*. Every status check
it had was green. Two months of filings were lost because a retired endpoint is
polite.

So this module treats **an empty payload as a FAILURE, not as a quiet day**, and
says so in the manifest. A day with genuinely no filings is possible but rare —
644 arrived in August 2026 alone — and the cost of investigating a real quiet
day is a minute, against two months of silent loss.

TWO FETCHES PER FILING. The index gives symbol, company and `broadcastDateTime`;
the transaction detail — category, type, quantity, value — lives in a per-filing
XBRL XML on nsearchives. Both are archived raw, because the parse can be redone
and the bytes cannot.

WHY THE TIMESTAMP IS WORTH MORE THAN THE STUDY. `available_from` is LOW
confidence on 5,742 of 5,877 eligible deals, because bulk-deal publication time
is assumed rather than observed. These filings carry `broadcastDateTime` to the
second, so this event class is HIGH confidence from its first collected row.
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

SOURCE_ID = "nse_insider_pit"
EXCHANGE = "NSE"
REPORT_TYPE = "INSIDER"

#: The LIVE route. `/api/corporates-pit` (no -gg) is retired and answers 200
#: with an empty envelope; using it is the two-month silent failure above.
INDEX_URL = ("https://www.nseindia.com/api/corporates-pit-gg"
             "?index=equities&from_date={frm}&to_date={to}")
WARMUP = "https://www.nseindia.com/"
REFERER = "https://www.nseindia.com/companies-listing/corporate-filings-insider-trading"

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
TIMEOUT = 30
RETRIES = 3
BACKOFF_BASE = 5
RATE_LIMIT = 1.5

#: The index accepts a range. 30 days keeps each archived file small enough to
#: read by eye and keeps one failure from costing a quarter.
WINDOW_DAYS = 30

#: XBRL detail files fetched per run. A first run has a backlog; the daily runs
#: that follow have a handful. Raise deliberately for a catch-up.
MAX_DETAIL_PER_RUN = 400

MANIFEST = ARCHIVE / "manifest.jsonl"


@dataclass(frozen=True, slots=True)
class Outcome:
    window: tuple[date, date]
    status: str
    filings: int = 0
    details: int = 0
    detail: str = ""


def _opener():
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
            with op.open(req, timeout=TIMEOUT) as resp:  # noqa: S310 - fixed https hosts
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


def _path(kind: str, name: str, digest: str, when: date) -> Path:
    return (ARCHIVE / REPORT_TYPE / EXCHANGE / f"year={when:%Y}" / f"month={when:%m}"
            / f"{kind}_{name}_{digest[:8]}.{'json' if kind == 'index' else 'xml'}.gz")


def record(entry: dict) -> None:
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    with MANIFEST.open("a") as fh:
        fh.write(json.dumps(entry, sort_keys=True) + "\n")


def _seen_digests() -> set[str]:
    if not MANIFEST.exists():
        return set()
    out = set()
    for line in MANIFEST.read_text().splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if r.get("source_id") == SOURCE_ID and r.get("status") in {"STORED", "DUPLICATE"}:
            if r.get("sha256"):
                out.add(r["sha256"])
    return out


def _store(body: bytes, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".partial")
    with gzip.open(tmp, "wb") as fh:
        fh.write(body)
    tmp.rename(dest)


def capture_window(op, frm: date, to: date, seen: set[str],
                   budget: list[int]) -> dict:
    url = INDEX_URL.format(frm=f"{frm:%d-%m-%Y}", to=f"{to:%d-%m-%Y}")
    base = {
        "source_id": SOURCE_ID, "exchange": EXCHANGE, "report_type": REPORT_TYPE,
        "url": url, "window_from": frm.isoformat(), "window_to": to.isoformat(),
        "fetched_at": datetime.now(UTC).isoformat(),
    }
    try:
        body = _get(op, url, REFERER)
    except Exception as exc:  # noqa: BLE001 - the record is the deliverable
        return {**base, "status": "FAILED", "error": str(exc)}

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return {**base, "status": "FAILED", "bytes": len(body),
                "error": "response is not JSON (session likely not warmed)"}

    rows = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return {**base, "status": "FAILED", "bytes": len(body),
                "error": f"no 'data' array; keys={list(payload)[:5]}"}

    if not rows:
        # THE WHOLE POINT OF THIS MODULE. A retired endpoint answers 200 with an
        # empty envelope and every green check stays green. Treated as failure.
        return {**base, "status": "FAILED", "bytes": len(body), "filings": 0,
                "error": "EMPTY ENVELOPE — 200 with data:[]. Either a genuinely "
                         "quiet window or the endpoint has been retired the way "
                         "/api/corporates-pit was. Verify before trusting."}

    digest = hash_bytes(body)
    entry = {**base, "sha256": digest, "bytes": len(body), "filings": len(rows)}
    dest = _path("index", f"{frm:%Y%m%d}_{to:%Y%m%d}", digest, frm)
    if digest in seen or dest.exists():
        entry["status"] = "DUPLICATE"
    else:
        _store(body, dest)
        entry["status"] = "STORED"
    entry["path"] = str(dest)

    # The transaction detail lives per filing, in XBRL on nsearchives.
    #
    # FAILURES ARE COUNTED, NOT JUST TOLERATED. One bad filing must not stop the
    # run — but until 2026-09-02 every failure here was `except: continue` with
    # no record, so if the XBRL host moved or started refusing, EVERY fetch
    # would fail, `details_stored` would read 0, and the entry would still be
    # STORED with a healthy `filings` count from the index.
    #
    # That is precisely the green-but-empty failure this module's docstring is
    # about, reproduced in the same file, one function below the guard written
    # to prevent it. The index guard covered the index and nothing covered this.
    got = 0
    detail_failures = 0
    for r in rows:
        if budget[0] <= 0:
            break
        xml = (r.get("xmlFileName") or "").strip()
        app = str(r.get("appId") or "").strip()
        if not xml or not app:
            continue
        try:
            xb = _get(op, xml, "https://www.nseindia.com/")
        except Exception:  # noqa: BLE001 - one bad filing must not stop the run
            detail_failures += 1
            continue
        budget[0] -= 1
        d2 = hash_bytes(xb)
        p2 = _path("xbrl", app, d2, frm)
        if d2 in seen or p2.exists():
            continue
        _store(xb, p2)
        seen.add(d2)
        got += 1
        time.sleep(RATE_LIMIT)
    entry["details_stored"] = got
    entry["detail_failures"] = detail_failures
    # Every detail fetch failing while the index succeeded means the XBRL host
    # has moved or is refusing us, not that the filings had no detail.
    if detail_failures and got == 0:
        entry["status"] = "FAILED"
        entry["error"] = (
            f"index returned {len(rows)} filings but ALL {detail_failures} XBRL "
            f"detail fetches failed. The transaction detail — category, type, "
            f"quantity, value — is on nsearchives and none of it arrived."
        )
    return entry


def collect(start: date, end: date | None = None,
            max_detail: int = MAX_DETAIL_PER_RUN) -> list[Outcome]:
    end = end or datetime.now(UTC).date()
    op = _opener()
    try:
        _get(op, WARMUP, "https://www.google.com/")
    except Exception as exc:  # noqa: BLE001
        print(f"  warmup failed (continuing, the API may still answer): {exc}")

    seen = _seen_digests()
    budget = [max_detail]
    out: list[Outcome] = []
    for i, (a, b) in enumerate(windows(start, end)):
        if i:
            time.sleep(RATE_LIMIT)
        e = capture_window(op, a, b, seen, budget)
        record(e)
        out.append(Outcome((a, b), e["status"], e.get("filings", 0),
                           e.get("details_stored", 0), e.get("error", "")))
    return out


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Archive NSE insider-trading filings.")
    ap.add_argument("--start", type=date.fromisoformat, required=True)
    ap.add_argument("--end", type=date.fromisoformat, default=None)
    ap.add_argument("--max-detail", type=int, default=MAX_DETAIL_PER_RUN)
    args = ap.parse_args()

    results = collect(args.start, args.end, args.max_detail)
    for r in results:
        flag = {"STORED": "ok   ", "DUPLICATE": "dup  ", "FAILED": "FAIL "}.get(r.status, r.status)
        print(f"  {flag} {r.window[0]} .. {r.window[1]}  "
              f"{r.filings:>5} filings  {r.details:>4} xbrl  {r.detail}"[:140])
    failed = sum(r.status == "FAILED" for r in results)
    print(f"\nINSIDER: {len(results)} window(s), {failed} failed, "
          f"{sum(r.filings for r in results):,} filings indexed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
