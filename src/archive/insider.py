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

STOPPING IS A FEATURE, ADDED 2026-09-20. This module knew how to keep trying
and not how to stop. On 2026-09-19 the 22:30 stage ran 159 minutes against a
refusing host, retrieved 12 files, failed, and was still going when the 01:00
SHP session started — because a failing fetch costs three attempts at
(TIMEOUT + 15s) plus backoff, and nothing counted consecutive failures or
elapsed time. `shp.py` had learned exactly this the day before (0074). Both
guards are here now: a wall clock (`MAX_MINUTES`) and a breaker
(`BREAKER_FAILURES`), with the same STOPPED-vs-FAILED distinction — a backlog
run ending on the clock is expected and exits 0; a host refusing us is a
failure and exits 1.

TODAY IS NOT A QUIET WINDOW, ADDED 2026-09-25. The daily stage runs
`--start 30-days-ago`, so `end` defaults to today and `windows()` always
chunks the span into a trailing SINGLE-DAY window for today — structurally,
every morning, not occasionally. Insider filings trickle in through and
after the trading session, so an empty envelope for "today" at 08:30 IST is
not the retired-endpoint signal this module exists to catch; it is the day
being young. That window is now PENDING, not FAILED — fifteen mornings in
September paged "COLLECTION FAILED: insider" on a schedule before anyone
looked twice at why. A window whose end is NOT today, empty, is still FAILED:
the carve-out is for the one day that has not finished happening, not for
"empty" in general.
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
#: Per-XBRL manifest rows (2026-09-18). Until this the detail fetch recorded
#: nothing per file, so no run could know which URLs it already held; every
#: run re-fetched held files in index order, spent its 400-file budget on
#: duplicates, and reported "0 new" — while 1,580 of 2,672 distinct filings
#: had never been fetched. Measured by sampling three URLs: one held.
XBRL_SOURCE_ID = "nse_insider_xbrl"
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

from src.common.bounded import bounded

#: Hard bound on ONE attempt — resolution included. `timeout=TIMEOUT` below
#: bounds the socket after `getaddrinfo` returns; nothing bounds `getaddrinfo`,
#: and on 2026-09-17 it held the deal fetch for 50 minutes. See src/common/bounded.py.
DEADLINE = TIMEOUT + 15
RETRIES = 3
BACKOFF_BASE = 5
RATE_LIMIT = 1.5

#: The index accepts a range. 30 days keeps each archived file small enough to
#: read by eye and keeps one failure from costing a quarter.
WINDOW_DAYS = 30

#: XBRL detail files fetched per run. A first run has a backlog; the daily runs
#: that follow have a handful. Raise deliberately for a catch-up.
MAX_DETAIL_PER_RUN = 400

#: WALL CLOCK, ADDED 2026-09-20 AFTER IT COST 159 MINUTES.
#:
#: On 2026-09-19 the 22:30 collector's insider stage ran for two hours and
#: thirty-nine minutes, fetched 12 files, failed, and was still running when
#: the 01:00 SHP session started. NSE was refusing: every fetch spent three
#: attempts x (TIMEOUT + 15s) plus 5s and 10s of backoff before giving up, and
#: nothing counted how many had failed in a row or how long the stage had been
#: going. `shp.py` learned this on 2026-09-18 (0074) and got both guards; this
#: module is the one that did not, and it failed the same way six weeks later.
#:
#: 45 minutes. A healthy daily run does a handful of files and finishes in
#: under a minute; a run still going at 45 is not going to finish, and the
#: budget it would spend is better spent by the next slot on a quieter host.
MAX_MINUTES = 45

#: Circuit breaker. This many CONSECUTIVE network failures means the host is
#: refusing us, not that these particular filings are missing. A 404 is exempt:
#: it is a fact about one file (12 old filings 404 permanently) and says
#: nothing about the host's willingness to serve the next one.
BREAKER_FAILURES = 5

MANIFEST = ARCHIVE / "manifest.jsonl"


class Throttled(RuntimeError):
    """The host is refusing us. Stop and say so, rather than spending the rest
    of the budget proving it once per file at two minutes each."""


def _is_network_failure(err: str) -> bool:
    """A 404 is a fact about one file. Everything else that reaches here is the
    host, or the path to it."""
    return "404" not in err


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
            def _get(req=req, op=op) -> bytes:
                with op.open(req, timeout=TIMEOUT) as resp:  # noqa: S310 - fixed https hosts
                    return resp.read()
            return bounded(_get, DEADLINE, what=url)
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


#: XBRL url -> latest status ("GONE" for a 404). Built per run by collect();
#: read by capture_window so a held or gone URL costs no request.
_prior_xbrl: dict[str, str] = {}


def _index_prior_xbrl() -> dict[str, str]:
    out: dict[str, str] = {}
    if not MANIFEST.exists():
        return out
    for line in MANIFEST.read_text().splitlines():
        if '"nse_insider_xbrl"' not in line:
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if r.get("url"):
            st = r.get("status")
            out[r["url"]] = "GONE" if st == "FAILED" and "404" in (r.get("error") or "") else st
    return out


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
        if r.get("source_id") in {SOURCE_ID, XBRL_SOURCE_ID} and r.get("status") in {"STORED", "DUPLICATE"}:
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
                   budget: list[int], streak: list[int] | None = None,
                   deadline_at: datetime | None = None, today: date | None = None) -> dict:
    """`streak` counts CONSECUTIVE network failures ACROSS windows; a success
    resets it and BREAKER_FAILURES raises Throttled. `deadline_at` is the run's
    wall-clock cap: detail fetching stops at it, the index still lands.
    `today` is injectable for tests; `collect()` passes the real date."""
    streak = streak if streak is not None else [0]
    today = today or datetime.now(UTC).date()
    url = INDEX_URL.format(frm=f"{frm:%d-%m-%Y}", to=f"{to:%d-%m-%Y}")
    base = {
        "source_id": SOURCE_ID, "exchange": EXCHANGE, "report_type": REPORT_TYPE,
        "url": url, "window_from": frm.isoformat(), "window_to": to.isoformat(),
        "fetched_at": datetime.now(UTC).isoformat(),
    }
    try:
        body = _get(op, url, REFERER)
        streak[0] = 0
    except Exception as exc:  # noqa: BLE001 - the record is the deliverable
        if _is_network_failure(str(exc)):
            streak[0] += 1
            if streak[0] >= BREAKER_FAILURES:
                record({**base, "status": "FAILED", "error": str(exc)[:200]})
                raise Throttled(f"{streak[0]} consecutive network failures; last: {str(exc)[:80]}")
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
        if to >= today:
            # THE DAY HAS NOT FINISHED HAPPENING YET. `collect()`'s rolling
            # `--start 30-days-ago` span always ends on today, and windows()
            # always chunks that into a trailing SINGLE-DAY window for today —
            # every morning, structurally, not occasionally. Insider filings
            # trickle in through and after the trading session, so asking for
            # "today" at 08:30 IST before most of them exist is not evidence
            # of anything wrong with the endpoint; it is evidence the day is
            # young. PENDING, not FAILED — the same status and the same
            # `session_date` key index_close.py uses for a dated feed asked
            # before publish, so runreport.py's existing PENDING handling
            # reports it as "not yet published" with no changes needed there.
            #
            # Found 2026-09-25: left as FAILED this had paged "COLLECTION
            # FAILED: insider" on a SCHEDULE, not a fault — fifteen mornings in
            # September before anyone looked twice at the reason.
            return {**base, "status": "PENDING", "bytes": len(body), "filings": 0,
                    "session_date": to.isoformat(),
                    "note": "today's window returned no filings yet — not "
                            "evidence of a retired endpoint"}
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
    already = 0
    done_urls: set[str] = set()  # one index row per PERSON; the XML is per filing
    for r in rows:
        if budget[0] <= 0:
            break
        if deadline_at and datetime.now(UTC) >= deadline_at:
            # The INDEX is already stored above; only the detail stops here,
            # and the next run resumes from the URL index. A window whose
            # detail was cut off is not complete and is not recorded as if it
            # were — `details_stopped` says so and survives into the manifest.
            entry["details_stopped"] = "wall clock"
            break
        xml = (r.get("xmlFileName") or "").strip()
        app = str(r.get("appId") or "").strip()
        if not xml or not app or xml in done_urls:
            continue
        done_urls.add(xml)
        # KNOWN URL, NO REQUEST. This is the whole fix: a held or gone file
        # costs nothing, so the budget reaches the filings never fetched.
        if _prior_xbrl.get(xml) in {"STORED", "DUPLICATE", "GONE"}:
            already += 1
            continue
        xrow = {"source_id": XBRL_SOURCE_ID, "exchange": EXCHANGE, "report_type": REPORT_TYPE,
                "url": xml, "app_id": app, "symbol": (r.get("symbol") or "").strip().upper(),
                "window_from": frm.isoformat(), "fetched_at": datetime.now(UTC).isoformat()}
        try:
            xb = _get(op, xml, "https://www.nseindia.com/")
            streak[0] = 0
        except Exception as exc:  # noqa: BLE001 - one bad filing must not stop the run
            detail_failures += 1
            record({**xrow, "status": "FAILED", "error": str(exc)[:200]})
            _prior_xbrl[xml] = "GONE" if "404" in str(exc) else "FAILED"
            if _is_network_failure(str(exc)):
                streak[0] += 1
                if streak[0] >= BREAKER_FAILURES:
                    # THE 159-MINUTE RUN. Every one of these costs three
                    # attempts at (TIMEOUT + 15s) plus 15s of backoff, so
                    # proving the host is down one file at a time is the most
                    # expensive way to learn it.
                    entry["details_stored"] = got
                    entry["details_already_held"] = already
                    entry["detail_failures"] = detail_failures
                    raise Throttled(
                        f"{streak[0]} consecutive network failures; last: {str(exc)[:80]}")
            time.sleep(RATE_LIMIT)
            continue
        budget[0] -= 1
        d2 = hash_bytes(xb)
        p2 = _path("xbrl", app, d2, frm)
        if d2 in seen or p2.exists():
            record({**xrow, "status": "DUPLICATE", "sha256": d2, "bytes": len(xb), "path": str(p2)})
            _prior_xbrl[xml] = "DUPLICATE"
            time.sleep(RATE_LIMIT)
            continue
        _store(xb, p2)
        seen.add(d2)
        record({**xrow, "status": "STORED", "sha256": d2, "bytes": len(xb), "path": str(p2)})
        _prior_xbrl[xml] = "STORED"
        got += 1
        time.sleep(RATE_LIMIT)
    entry["details_stored"] = got
    entry["details_already_held"] = already
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
            max_detail: int = MAX_DETAIL_PER_RUN,
            max_minutes: int = MAX_MINUTES) -> list[Outcome]:
    end = end or datetime.now(UTC).date()
    # SEPARATE FROM `end` ON PURPOSE. An explicit historical --end (a deliberate
    # backfill) must not read as "today" just because it is this call's last
    # window — only the real calendar date earns the PENDING carve-out below.
    today = datetime.now(UTC).date()
    deadline_at = datetime.now(UTC) + timedelta(minutes=max_minutes)
    op = _opener()
    try:
        _get(op, WARMUP, "https://www.google.com/")
    except Exception as exc:  # noqa: BLE001
        print(f"  warmup failed (continuing, the API may still answer): {exc}")

    seen = _seen_digests()
    _prior_xbrl.clear()
    _prior_xbrl.update(_index_prior_xbrl())
    budget = [max_detail]
    streak = [0]
    out: list[Outcome] = []
    stopped = ""
    for i, (a, b) in enumerate(windows(start, end)):
        if datetime.now(UTC) >= deadline_at:
            stopped = f"wall clock: {max_minutes} min reached after {i} window(s)"
            break
        if i:
            time.sleep(RATE_LIMIT)
        try:
            e = capture_window(op, a, b, seen, budget, streak=streak, deadline_at=deadline_at, today=today)
        except Throttled as exc:
            stopped = f"THROTTLED after {i} window(s): {exc}"
            break
        record(e)
        out.append(Outcome((a, b), e["status"], e.get("filings", 0),
                           e.get("details_stored", 0), e.get("error") or e.get("note", "")))

    if stopped:
        # THROTTLED is a failure: the host refused us and the run got less than
        # it asked for because of something outside this machine. The WALL
        # CLOCK is not — it is how a backlog run is EXPECTED to end, and a
        # stage alert for it every night is the alert nobody reads. Same
        # distinction as shp.py (0074): STOPPED, exit 0, visible in /feeds.
        status = "FAILED" if stopped.startswith("THROTTLED") else "STOPPED"
        record({"source_id": SOURCE_ID, "exchange": EXCHANGE, "report_type": REPORT_TYPE,
                "status": status, "fetched_at": datetime.now(UTC).isoformat(),
                "error" if status == "FAILED" else "note": f"run stopped — {stopped}"})
        out.append(Outcome((start, end), status, detail=stopped))
    return out


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Archive NSE insider-trading filings.")
    ap.add_argument("--start", type=date.fromisoformat, required=True)
    ap.add_argument("--end", type=date.fromisoformat, default=None)
    ap.add_argument("--max-detail", type=int, default=MAX_DETAIL_PER_RUN)
    ap.add_argument("--max-minutes", type=int, default=MAX_MINUTES,
                    help="wall clock; the run stops between fetches, not mid-file")
    args = ap.parse_args()

    results = collect(args.start, args.end, args.max_detail, args.max_minutes)
    for r in results:
        flag = {"STORED": "ok   ", "DUPLICATE": "dup  ", "FAILED": "FAIL ",
                "STOPPED": "stop ", "PENDING": "pend "}.get(r.status, r.status)
        print(f"  {flag} {r.window[0]} .. {r.window[1]}  "
              f"{r.filings:>5} filings  {r.details:>4} xbrl  {r.detail}"[:140])
    failed = sum(r.status == "FAILED" for r in results)
    stopped = [r for r in results if r.status == "STOPPED"]
    print(f"\nINSIDER: {len(results) - len(stopped)} window(s), {failed} failed, "
          f"{sum(r.filings for r in results):,} filings indexed")
    if stopped:
        # Exit 0: the backlog is resumed next run, and a nightly stage alert
        # for the expected ending of a catch-up is the alert nobody reads.
        print(f"  RUN STOPPED: {stopped[-1].detail}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
