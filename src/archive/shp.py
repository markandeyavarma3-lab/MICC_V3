"""shp.py — quarterly shareholding patterns, per symbol, with the named holders.

WHY THIS SOURCE, AND WHY THE BYTES COME BEFORE THE REGISTRATION.

Every event class this project has tested is bounded by the same number: how
many independent monthly cohorts exist. Deals have 249 months and a handful of
events in each; the verdict is DEAD and no source on earth adds months to the
past. Shareholding patterns are a different shape — every listed company
reports FII, DII, mutual-fund, promoter and public holding every quarter, all
at once — ~2,000 symbols per period instead of a handful of events per month.
That is the first structure in this project that is not starved on the
dimension that kept killing results. (The time dimension is still ~20
quarters, and any registration has to say so.)

Probed 2026-09-17 on five symbols across sizes (RELIANCE, TCS, SBIN, CDSL,
KPRMILL): 20-22 filings each, quarter-ends 2021-09-30 -> 2026-06-30 for ALL
five, and the oldest XBRL still resolves with holder names inside. The floor is
uniform, so it is the endpoint's window rather than listing age — and it is
UNKNOWN whether that window is fixed (the XBRL format started then) or rolls.
The insider endpoint turned out to be a four-month rolling window, found the
same day; the months before it were already gone. This collector exists to
make that question moot: archived bytes do not expire.

THIS FILE ARCHIVES. IT DOES NOT PARSE. Nothing here reads a holding percentage
or writes a table. What to compute — active change net of price, entry/exit
counts, whatever the registration says — is a research decision that is taken
in a registration, not in a collector. The bytes are collected first only
because they may not wait.

TWO FETCHES PER SYMBOL. The filing master (JSON, needs the Akamai cookies from
the public SHP page — the same warm-up fii_dii and insider do; NOT a login)
lists every filing with its quarter-end and an `xbrl` URL. The XBRL itself is
on the static host, no cookies, and carries the named holders
(`in-bse-shp:NameOfTheShareholder`). Both archived raw, both sha256-deduped,
both recorded in the manifest with the symbol and quarter they belong to.

AN EMPTY MASTER IS NOT A FAILURE PER SYMBOL, AND IS A FAILURE PER RUN. A new
listing, a debt-only symbol or a company that files late genuinely has no
filings, and calling that FAILED would drown the manifest. But the retired
`/api/corporates-pit` answered 200 with an empty list for two months and every
green check stayed green — so if MOST of a run comes back empty, the endpoint
is gone and the run says so. The threshold is a number, below, not a feeling.

THE SWEEP IS RESUMABLE BECAUSE THE MANIFEST IS THE CHECKPOINT. ~2,900 symbols
at the 2-second rate limit is ~1.6 hours for the masters alone and ~60,000
XBRL files — about 33 hours — for the detail. A run has a detail budget; a
symbol whose master was stored within the last quarter is skipped unless
`--force`; killing the process and starting it again loses at most one fetch.
"""

from __future__ import annotations

import csv
import gzip
import io
import json
import sys
import time
import zipfile
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import HTTPCookieProcessor, Request, build_opener

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.common.bounded import bounded  # noqa: E402
from src.common.network import NetworkDown, counts_against_host  # noqa: E402
from src.common.hashing import hash_bytes  # noqa: E402
from src.common.paths import ARCHIVE  # noqa: E402

EXCHANGE = "NSE"
#: Two series, as the 2026-09-15 proof recorded them: the master under SHP,
#: the filing XML under SHP_XBRL. Kept so the manifest stays one series.
MASTER_SOURCE, MASTER_TYPE = "nse_shp_master", "SHP"
XBRL_SOURCE, XBRL_TYPE = "nse_shp_xbrl", "SHP_XBRL"

MASTER_URL = ("https://www.nseindia.com/api/corporate-share-holdings-master"
              "?index=equities&symbol={symbol}")
WARMUP = "https://www.nseindia.com/companies-listing/corporate-filings-shareholding-pattern"
REFERER = WARMUP

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
TIMEOUT = 30
#: Hard bound on ONE attempt, resolution included — see src/common/bounded.py.
DEADLINE = TIMEOUT + 15
RETRIES = 3
BACKOFF_BASE = 5
RATE_LIMIT = 2.0

#: XBRL files fetched per run. The first sweep has ~60,000 behind it; a
#: quarterly top-up has ~2,900.
#:
#: 2000 was the first number. The first sweep (2026-09-17, budget 4000)
#: measured NSE's tolerance: ~1,150 files/hour sustained for three hours, then
#: the host slowed every response to the deadline, the run stretched from an
#: estimated four hours to seven, and it was still running when the 20:30
#: collector started — whose deal fetch then took eleven minutes instead of
#: twenty seconds. 1500 was under an hour at the observed rate.
#:
#: 2500 from 2026-09-19. With the wall clock (below) as the hard stop and the
#: breaker as the throttle detector, the budget was the binding limit and not
#: the guard: the 10:30 session on 09-19 spent all 1,500 in 82 minutes at
#: 3.3 s/file and then idled for the remaining 68. 2500 fills the 150 minutes
#: at that pace; if the host slows, the wall clock ends the run at the same
#: hour it always did, with more files instead of fewer. Measured, not
#: assumed: compare files-per-session before and after in the SHP log.
MAX_DETAIL_PER_RUN = 2500

#: Wall-clock cap. A run that is being throttled does not finish faster by
#: continuing; it finishes later and collides with the next scheduled job. The
#: nightly job starts at 01:00 and the collector at 08:30; 150 minutes ends
#: the sweep by 03:30 with room.
MAX_MINUTES = 150

#: Circuit breaker. This many CONSECUTIVE network failures (deadline, refused,
#: reset — not 404, which is a fact about one file) means the host is
#: throttling us, and the honest move is to stop and say so, not to retry the
#: next 2,000 files at 135 seconds each.
BREAKER_FAILURES = 5

#: A master stored more recently than this is not re-fetched without --force.
#: Filings are quarterly; a week of slack covers late filers without
#: re-sweeping 2,900 symbols every night.
MASTER_FRESH_DAYS = 80

#: An EMPTY master (an ETF, a debt-only listing) is fresh for this long. ~100
#: ETFs sit in the EQ series and will never file; re-asking nightly is 100
#: wasted fetches. Seven days, not eighty, in case an EMPTY was ever a
#: throttled 200 rather than a fact.
EMPTY_FRESH_DAYS = 7

#: If MORE than this fraction of masters in a run come back empty, the run is
#: FAILED: that is a retired endpoint, not 1,500 companies that stopped filing.
EMPTY_RUN_FRACTION = 0.5

#: Bhavcopy series that are main-board equities. SM (SME platform) files under
#: a different regime and is left out on purpose; GB/GS are bonds.
EQUITY_SERIES = {"EQ", "BE"}

MANIFEST = ARCHIVE / "manifest.jsonl"


@dataclass(frozen=True, slots=True)
class Outcome:
    symbol: str
    status: str
    filings: int = 0
    details: int = 0
    detail: str = ""


# --- universe ------------------------------------------------------------------


def universe() -> list[str]:
    """Every main-board equity symbol in the newest archived bhavcopy.

    The bhavcopy is the exchange's own daily list of what traded, so it IS the
    listed universe on that date — no hand-maintained list to drift. The
    identity master's `symbol_history` is NOT used: it covers the ~1,200
    symbols the deals data ever touched, not the ~2,900 that are listed.
    """
    files = sorted((ARCHIVE / "PRICE" / EXCHANGE).rglob("*.gz"))
    if not files:
        raise RuntimeError("no archived bhavcopy under PRICE/NSE; run src.archive.prices first")
    raw = gzip.open(files[-1], "rb").read()
    if raw[:2] == b"PK":
        z = zipfile.ZipFile(io.BytesIO(raw))
        raw = z.read(z.namelist()[0])
    rows = csv.DictReader(io.StringIO(raw.decode(errors="ignore")))
    out = {r["TckrSymb"].strip() for r in rows
           if r.get("SctySrs", "").strip() in EQUITY_SERIES and r.get("TckrSymb", "").strip()}
    return sorted(out)


# --- http --------------------------------------------------------------------


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
            def _read(req=req, op=op) -> bytes:
                with op.open(req, timeout=TIMEOUT) as resp:  # noqa: S310 - fixed https hosts
                    return resp.read()
            return bounded(_read, DEADLINE, what=url)
        except HTTPError as exc:
            if exc.code == 404:
                raise  # a filing whose XML is gone; retrying cannot help
            last = exc
        except (URLError, TimeoutError) as exc:
            last = exc
    raise RuntimeError(f"all {RETRIES} attempts failed for {url}: {last}")


# --- archive -----------------------------------------------------------------


def _master_path(symbol: str, digest: str, when: date) -> Path:
    return (ARCHIVE / MASTER_TYPE / EXCHANGE / f"year={when:%Y}" / f"month={when:%m}"
            / f"{MASTER_TYPE}_{EXCHANGE}_{symbol}_{when:%Y%m%d}_{digest[:8]}.json.gz")


def _xbrl_path(quarter_end: date, digest: str) -> Path:
    return (ARCHIVE / XBRL_TYPE / EXCHANGE / f"year={quarter_end:%Y}" / f"month={quarter_end:%m}"
            / f"{XBRL_TYPE}_{EXCHANGE}_{quarter_end:%Y%m%d}_{digest[:8]}.xml.gz")


def record(entry: dict) -> None:
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    with MANIFEST.open("a") as fh:
        fh.write(json.dumps(entry, sort_keys=True) + "\n")


def _store(body: bytes, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".partial")
    with gzip.open(tmp, "wb") as fh:
        fh.write(body)
    tmp.rename(dest)


def _manifest_rows() -> list[dict]:
    if not MANIFEST.exists():
        return []
    out = []
    for line in MANIFEST.read_text().splitlines():
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _seen_digests(rows: list[dict]) -> set[str]:
    return {r["sha256"] for r in rows
            if r.get("source_id") in {MASTER_SOURCE, XBRL_SOURCE}
            and r.get("status") in {"STORED", "DUPLICATE"} and r.get("sha256")}


def _fresh_masters(rows: list[dict], days: int = MASTER_FRESH_DAYS,
                   empty_days: int = EMPTY_FRESH_DAYS) -> tuple[set[str], dict[str, str]]:
    """(done, cached): `done` are symbols to skip — master fresh AND every
    filing's XBRL attempted, or EMPTY within `empty_days`. `cached` maps a
    symbol whose master is fresh but whose XBRL is INCOMPLETE to the archived
    master's path, so the next session reads the filing list from disk and
    spends its requests on the XBRL.

    THE BUG THIS REPLACES (2026-09-18). "Fresh" meant "master fetched within
    80 days", full stop. The second session fetched masters for 1,596
    companies in 53 minutes, ran out of XBRL budget after 84 of them, and the
    other 1,500 were then skipped as fresh — for 80 days, filings unfetched.
    The index outran the detail and the detail could never catch up. The
    count of companies with XBRL sat at 240 while 22,470 filings were
    "indexed".
    """
    now = datetime.now(UTC)
    cut, ecut = now - timedelta(days=days), now - timedelta(days=empty_days)
    done: set[str] = set()
    cached: dict[str, str] = {}
    latest: dict[str, dict] = {}
    for r in rows:
        if r.get("source_id") != MASTER_SOURCE or not (r.get("symbol") and r.get("fetched_at")):
            continue
        if r["symbol"] not in latest or r["fetched_at"] > latest[r["symbol"]]["fetched_at"]:
            latest[r["symbol"]] = r
    for s, r in latest.items():
        try:
            at = datetime.fromisoformat(r["fetched_at"])
        except ValueError:
            continue
        if r.get("status") == "EMPTY" and at >= ecut:
            done.add(s)
        elif r.get("status") in {"STORED", "DUPLICATE"} and at >= cut:
            if r.get("xbrl_complete"):
                done.add(s)
            elif r.get("path"):
                cached[s] = r["path"]
    return done, cached


class Throttled(RuntimeError):
    """The host is slowing every response to the deadline. Stop, do not grind."""


def _is_network_failure(err: str) -> bool:
    """A 404 is a fact about one file. Everything else that reaches here is the
    host, or the path to it."""
    return "404" not in err


def _quarter_end(row: dict) -> date | None:
    """The filing's quarter-end, from the master's `date` field (DD-MON-YYYY)."""
    raw = str(row.get("date") or "").strip()
    for fmt in ("%d-%b-%Y", "%d-%b-%Y %H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


# --- one symbol ----------------------------------------------------------------


def capture_symbol(op, symbol: str, seen: set[str], budget: list[int],
                   today: date | None = None, streak: list[int] | None = None,
                   deadline_at: datetime | None = None, cached_master: str | None = None) -> dict:
    """`streak` counts CONSECUTIVE network failures across symbols; a success
    resets it, BREAKER_FAILURES raises Throttled. `deadline_at` is the run's
    wall-clock cap; detail fetching stops at it, the master still lands.
    `cached_master` is an archived master to read the filing list from
    instead of fetching it — a fresh index whose XBRL is still owed."""
    today = today or datetime.now(UTC).date()
    streak = streak if streak is not None else [0]
    url = MASTER_URL.format(symbol=symbol)
    base = {"source_id": MASTER_SOURCE, "exchange": EXCHANGE, "report_type": MASTER_TYPE,
            "symbol": symbol, "url": url, "session_date": today.isoformat(),
            "fetched_at": datetime.now(UTC).isoformat()}
    if cached_master and Path(cached_master).exists():
        with gzip.open(cached_master, "rb") as fh:
            body = fh.read()
        base["note"] = "filing list read from the archived master; XBRL continued"
    else:
        try:
            body = _get(op, url, REFERER)
            streak[0] = 0
        except Exception as exc:  # noqa: BLE001 - the record is the deliverable
            if _is_network_failure(str(exc)) and counts_against_host(str(exc)):
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
    rows = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        return {**base, "status": "FAILED", "bytes": len(body),
                "error": f"no filing list; keys={list(payload)[:5] if isinstance(payload, dict) else type(payload).__name__}"}
    if not rows:
        # Per symbol this is a fact (new listing, late filer, no equity SHP).
        # Per RUN it is checked in collect(): most-empty means retired endpoint.
        return {**base, "status": "EMPTY", "bytes": len(body), "filings": 0}

    digest = hash_bytes(body)
    entry = {**base, "sha256": digest, "bytes": len(body), "filings": len(rows)}
    qs = [q for q in (_quarter_end(r) for r in rows) if q]
    if qs:
        entry["quarter_first"], entry["quarter_last"] = min(qs).isoformat(), max(qs).isoformat()
    dest = _master_path(symbol, digest, today)
    if digest in seen or dest.exists():
        entry["status"] = "DUPLICATE"
    else:
        _store(body, dest)
        seen.add(digest)
        entry["status"] = "STORED"
    entry["path"] = str(dest)

    # The holders are in the XBRL. Counted failures, as in insider.py: if the
    # index succeeds and EVERY detail fetch fails, the host has moved and the
    # run must not read as healthy on the strength of the index.
    got = skipped = failures = 0
    attempted = 0
    wanted = sum(1 for r in rows if str(r.get("xbrl") or "").strip() and _quarter_end(r))
    for r in rows:
        if budget[0] <= 0 or (deadline_at and datetime.now(UTC) >= deadline_at):
            break
        xurl = str(r.get("xbrl") or "").strip()
        q = _quarter_end(r)
        if not xurl or not q:
            continue
        # Already held or already known-gone: skip without a request. This is
        # what makes a resumed symbol cost only its MISSING filings.
        prior = _prior_xbrl.get(xurl)
        if prior in {"STORED", "DUPLICATE", "GONE"}:
            attempted += 1
            skipped += prior != "GONE"
            continue
        try:
            xb = _get(op, xurl, "https://www.nseindia.com/")
            streak[0] = 0
        except Exception as exc:  # noqa: BLE001 - one bad filing must not stop the run
            failures += 1
            attempted += "404" in str(exc)  # a 404 is final; a network failure is not
            if _is_network_failure(str(exc)) and counts_against_host(str(exc)):
                streak[0] += 1
                if streak[0] >= BREAKER_FAILURES:
                    entry["details_stored"], entry["detail_failures"] = got, failures
                    entry["status"] = "FAILED"
                    entry["error"] = f"throttled after {got} detail file(s): {str(exc)[:80]}"
                    record({"source_id": XBRL_SOURCE, "exchange": EXCHANGE, "report_type": XBRL_TYPE,
                            "symbol": symbol, "session_date": q.isoformat(), "url": xurl,
                            "record_id": r.get("recordId"), "status": "FAILED", "error": str(exc)[:200],
                            "fetched_at": datetime.now(UTC).isoformat()})
                    record(entry)
                    raise Throttled(f"{streak[0]} consecutive network failures; last: {str(exc)[:80]}")
            record({"source_id": XBRL_SOURCE, "exchange": EXCHANGE, "report_type": XBRL_TYPE,
                    "symbol": symbol, "session_date": q.isoformat(), "url": xurl,
                    "record_id": r.get("recordId"), "status": "FAILED", "error": str(exc)[:200],
                    "fetched_at": datetime.now(UTC).isoformat()})
            time.sleep(RATE_LIMIT)
            continue
        budget[0] -= 1
        attempted += 1
        d2 = hash_bytes(xb)
        p2 = _xbrl_path(q, d2)
        x = {"source_id": XBRL_SOURCE, "exchange": EXCHANGE, "report_type": XBRL_TYPE,
             "symbol": symbol, "session_date": q.isoformat(), "url": xurl,
             "record_id": r.get("recordId"), "sha256": d2, "bytes": len(xb),
             "path": str(p2), "fetched_at": datetime.now(UTC).isoformat()}
        if d2 in seen or p2.exists():
            x["status"] = "DUPLICATE"; skipped += 1
        else:
            _store(xb, p2); seen.add(d2); got += 1
            x["status"] = "STORED"
        record(x)
        time.sleep(RATE_LIMIT)
    entry["details_stored"], entry["details_dup"], entry["detail_failures"] = got, skipped, failures
    entry["xbrl_wanted"], entry["xbrl_attempted"] = wanted, attempted
    entry["xbrl_complete"] = attempted >= wanted
    if failures and not got and not skipped:
        entry["status"] = "FAILED"
        entry["error"] = (f"master lists {len(rows)} filings but ALL {failures} XBRL fetches "
                          f"failed — the static host has moved or is refusing us.")
    return entry


# --- the sweep ----------------------------------------------------------------


#: XBRL url -> its latest manifest status ("GONE" for a 404). Built per run by
#: collect(); read by capture_symbol() so a resumed symbol requests only what
#: it is missing.
_prior_xbrl: dict[str, str] = {}


def _index_prior_xbrl(rows: list[dict]) -> dict[str, str]:
    out: dict[str, str] = {}
    for r in rows:
        if r.get("source_id") != XBRL_SOURCE or not r.get("url"):
            continue
        st = r.get("status")
        if st == "FAILED":
            st = "GONE" if "404" in (r.get("error") or "") else "FAILED"
        out[r["url"]] = st
    return out


def collect(symbols: list[str] | None = None, max_detail: int = MAX_DETAIL_PER_RUN,
            force: bool = False, max_minutes: int = MAX_MINUTES) -> list[Outcome]:
    symbols = symbols or universe()
    started = datetime.now(UTC)
    deadline_at = started + timedelta(minutes=max_minutes)
    rows = _manifest_rows()
    seen = _seen_digests(rows)
    _prior_xbrl.clear()
    _prior_xbrl.update(_index_prior_xbrl(rows))
    done, cached = (set(), {}) if force else _fresh_masters(rows)
    # INCOMPLETE SYMBOLS FIRST. Their filing list is on disk, so every request
    # goes to XBRL; unindexed symbols follow. This is what lets the detail
    # catch up with the index instead of trailing it by 80 days.
    todo = [s for s in symbols if s in cached] + [s for s in symbols if s not in done and s not in cached]
    print(f"  universe {len(symbols)} symbols; {len(done)} done, {len(cached)} indexed-but-incomplete (XBRL owed), "
          f"{len(todo) - len(cached)} unindexed; XBRL budget {max_detail}", flush=True)

    op = _opener()
    try:
        _get(op, WARMUP, "https://www.google.com/")
    except Exception as exc:  # noqa: BLE001
        print(f"  warmup failed (continuing, the API may still answer): {exc}")

    budget = [max_detail]
    streak = [0]
    out: list[Outcome] = []
    empties = 0
    stopped = ""
    skipped = 0
    for i, sym in enumerate(todo):
        if datetime.now(UTC) >= deadline_at:
            stopped = f"wall clock: {max_minutes} min reached after {i} symbol(s)"
            break
        if budget[0] <= 0 and sym in cached:
            # The index is on disk and the only thing owed is XBRL, which
            # this run can no longer fetch. Walking it anyway cost 2 s of
            # rate-limit sleep per symbol for a DUPLICATE row and nothing
            # else — 945 symbols, 31 minutes, on 2026-09-19 — while the
            # unindexed symbols behind it waited. They get the time instead.
            skipped += 1
            continue
        if i:
            time.sleep(RATE_LIMIT)
        try:
            e = capture_symbol(op, sym, seen, budget, streak=streak, deadline_at=deadline_at,
                               cached_master=cached.get(sym))
        except Throttled as exc:
            stopped = f"THROTTLED after {i} symbol(s): {exc}"
            break
        except NetworkDown as exc:
            # THIS MACHINE'S NETWORK, NOT THE HOST (2026-09-25). A DNS failure
            # used to count toward the throttle breaker, so a Wi-Fi radio still
            # re-associating after sleep stopped whole sessions "THROTTLED".
            stopped = f"NETWORK DOWN after {i} symbol(s): {exc}"
            break
        record(e)
        if e["status"] == "EMPTY":
            empties += 1
        out.append(Outcome(sym, e["status"], e.get("filings", 0),
                           e.get("details_stored", 0), e.get("error", "")))
        # When the XBRL budget is spent the loop keeps going: masters are one
        # cheap fetch each, so every symbol's index lands THIS run and the
        # detail resumes next run from the manifest.
        if (i + 1) % 100 == 0:
            print(f"  ... {i + 1}/{len(todo)}  xbrl budget left {budget[0]}", flush=True)
    if skipped:
        print(f"  {skipped} indexed symbol(s) skipped after the XBRL budget was spent; "
              f"their detail is owed to the next run", flush=True)

    if stopped:
        # THROTTLED is a failure: the host refused us and the budget was lost.
        # The WALL CLOCK is not: it is how every backlog session is expected
        # to end, and a stage alert for it three times a day is the alert
        # nobody reads. Recorded as STOPPED, exit 0, visible in /feeds.
        status = "STOPPED" if stopped.startswith("wall clock") else "FAILED"
        record({"source_id": MASTER_SOURCE, "exchange": EXCHANGE, "report_type": MASTER_TYPE,
                "status": status, "fetched_at": datetime.now(UTC).isoformat(),
                "error" if status == "FAILED" else "note": f"run stopped — {stopped}"})
        print(f"\n  RUN {status}: {stopped}", flush=True)
        out.append(Outcome("(run)", status, detail=stopped))
    if todo and empties / len(todo) > EMPTY_RUN_FRACTION:
        record({"source_id": MASTER_SOURCE, "exchange": EXCHANGE, "report_type": MASTER_TYPE,
                "status": "FAILED", "fetched_at": datetime.now(UTC).isoformat(),
                "error": f"{empties}/{len(todo)} masters EMPTY — above {EMPTY_RUN_FRACTION:.0%}. "
                         f"That is a retired endpoint, not {empties} companies that stopped filing."})
        print(f"\n  RUN FAILED: {empties}/{len(todo)} symbols returned an empty master.")
    return out


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Archive NSE shareholding-pattern filings.")
    ap.add_argument("--symbols", nargs="*", help="override the bhavcopy universe")
    ap.add_argument("--max-detail", type=int, default=MAX_DETAIL_PER_RUN)
    ap.add_argument("--force", action="store_true", help="re-fetch masters stored recently")
    ap.add_argument("--max-minutes", type=int, default=MAX_MINUTES)
    args = ap.parse_args()

    results = collect(args.symbols or None, args.max_detail, args.force, args.max_minutes)
    for r in results:
        if r.status in {"FAILED", "STOPPED"} or r.details:
            flag = {"STORED": "ok   ", "DUPLICATE": "dup  ", "EMPTY": "empty", "FAILED": "FAIL ", "STOPPED": "stop "}.get(r.status, r.status)
            print(f"  {flag} {r.symbol:<12} {r.filings:>3} filings  {r.details:>3} xbrl  {r.detail}"[:120])
    by = {}
    for r in results:
        by[r.status] = by.get(r.status, 0) + 1
    print(f"\nSHP: {len(results)} symbol(s) {by}; {sum(r.filings for r in results):,} filings indexed, "
          f"{sum(r.details for r in results):,} xbrl stored")
    return 1 if by.get("FAILED") else 0


if __name__ == "__main__":
    raise SystemExit(main())
