"""derivatives.py — participant-wise OI and the F&O bhavcopy. Decision 0058.

WHY THESE TWO ARE ONE MODULE. Every other collector here is one file per source,
and that convention is right when the sources differ. These do not: both are
dated NSE archive files, fetched the same way, archived under the same layout,
settled by the same 404-is-a-holiday rule. Two files would have been two copies
of `capture()` diverging quietly. The feed is a parameter, not a module.

WHY NOW. `sources.yml` parked both behind the trigger
`fno_institutional_positioning`, whose condition was "FII/DII cash history
reaches 24 months, making Engine E researchable". Decision 0058 supersedes it:
that condition was written before 0056 measured that the deals track bottoms out
on month-sparsity for entity-level work, which makes participant-wise OI the
best entity-attributable flow series in the warehouse rather than a nice-to-have
behind another study.

WHAT THIS DOES NOT DO. It stores bytes and reports staleness. It does not parse
into the warehouse, and no study reads it — Workstream 3 is the deals verdict and
this must not become a second open front. Collection only, deliberately.

THE ALERT IS PART OF THE BUILD. A parked feed going stale is honest; a *live*
feed going stale silently is the char_panel failure, which cost 27 days of
quietly degrading CHAR_MATCHED quality. `staleness()` exists before the first
byte is fetched, and its test was watched failing.
"""

from __future__ import annotations

import gzip
import json
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.common.hashing import hash_bytes  # noqa: E402
from src.common.paths import ARCHIVE  # noqa: E402

MANIFEST = ARCHIVE / "manifest.jsonl"
EXCHANGE = "NSE"

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
TIMEOUT = 40

from src.common.bounded import bounded

#: Hard bound on ONE attempt — resolution included. `timeout=TIMEOUT` below
#: bounds the socket after `getaddrinfo` returns; nothing bounds `getaddrinfo`,
#: and on 2026-09-17 it held the deal fetch for 50 minutes. See src/common/bounded.py.
DEADLINE = TIMEOUT + 15
RETRIES = 3
BACKOFF_BASE = 5
RATE_LIMIT = 2.0

#: Sessions behind before a live feed is called stale. Matches STALE_SESSIONS in
#: src/monitor/health.py rather than inventing a second threshold.
STALE_SESSIONS = 2


@dataclass(frozen=True, slots=True)
class Feed:
    source_id: str
    report_type: str
    url_template: str
    suffix: str
    earliest: date
    #: What the payload must start with to be the thing we asked for. A 200 that
    #: returns an HTML error page is the failure mode this project has already
    #: been bitten by (0024: a retired endpoint answering 200 with data:[]).
    magic: bytes


FEEDS: tuple[Feed, ...] = (
    Feed(
        source_id="nse_participant_oi",
        report_type="PARTICIPANT_OI",
        url_template=("https://nsearchives.nseindia.com/content/nsccl/"
                      "fao_participant_oi_{dmy}.csv"),
        suffix=".csv.gz",
        # The seed already holds 2014-01-01 .. 2026-06-25; this collector only
        # ever needs the gap forward from there.
        earliest=date(2026, 6, 26),
        magic=b'""Participant wise Open Interest',
    ),
    Feed(
        source_id="nse_fo_bhavcopy",
        report_type="FO",
        url_template=("https://nsearchives.nseindia.com/content/fo/"
                      "BhavCopy_NSE_FO_0_0_0_{ymd}_F_0000.csv.zip"),
        suffix=".csv.zip.gz",
        # fno_spine ends 2026-08-14; the UDiFF route itself starts 2024-01-01.
        earliest=date(2026, 8, 15),
        magic=b"PK\x03\x04",
    ),
)


def feed(source_id: str) -> Feed:
    for f in FEEDS:
        if f.source_id == source_id:
            return f
    raise KeyError(f"no such feed: {source_id}")


def url_for(f: Feed, session: date) -> str:
    return f.url_template.format(ymd=f"{session:%Y%m%d}", dmy=f"{session:%d%m%Y}")


def archive_path(f: Feed, session: date, digest: str) -> Path:
    """`raw/archive/{report_type}/{exchange}/year=/month=/` per sources.yml."""
    name = f"{f.report_type}_{EXCHANGE}_{session:%Y%m%d}_{digest[:8]}{f.suffix}"
    return (ARCHIVE / f.report_type / EXCHANGE
            / f"year={session:%Y}" / f"month={session:%m}" / name)


def _manifest_rows() -> list[dict]:
    if not MANIFEST.exists():
        return []
    out = []
    for line in MANIFEST.read_text().splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def settled_sessions(f: Feed) -> set[str]:
    """STORED, DUPLICATE and NO_SESSION never need asking again. PENDING and
    FAILED are deliberately absent — those must be retried."""
    return {
        r["session_date"] for r in _manifest_rows()
        if r.get("source_id") == f.source_id and r.get("session_date")
        and r.get("status") in {"STORED", "DUPLICATE", "NO_SESSION"}
    }


def missing(f: Feed, start: date, end: date,
            settled: set[str] | None = None) -> list[date]:
    """Weekday sessions in [start, end] with nothing settled against them.

    Holidays are not hardcoded. A holiday calendar in a config is a claim that
    goes stale; the 404 that discovers one is recorded NO_SESSION and never
    repeated, so the observed calendar earns itself.
    """
    done = settled_sessions(f) if settled is None else settled
    if start < f.earliest:
        start = f.earliest
    out, d = [], start
    while d <= end:
        if d.weekday() < 5 and d.isoformat() not in done:
            out.append(d)
        d += timedelta(days=1)
    return out


@dataclass(frozen=True, slots=True)
class Staleness:
    source_id: str
    last: date | None
    sessions_stale: int

    @property
    def alerting(self) -> bool:
        return self.last is None or self.sessions_stale >= STALE_SESSIONS

    def render(self) -> str:
        when = self.last.isoformat() if self.last else "never"
        mark = "STALE" if self.alerting else "ok   "
        return f"  {mark}  {self.source_id:<20} last {when}  {self.sessions_stale} session(s) stale"


def _weekday_sessions_between(a: date, b: date) -> int:
    if b <= a:
        return 0
    n, d = 0, a
    while d < b:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n += 1
    return n


def staleness(f: Feed, last: date | None, today: date | None = None) -> Staleness:
    today = today or datetime.now(UTC).date()
    if last is None:
        return Staleness(f.source_id, None, 999)
    return Staleness(f.source_id, last, _weekday_sessions_between(last, today))


def last_session(f: Feed) -> date | None:
    got = settled_sessions(f)
    real = sorted(s for s in got if s)
    return date.fromisoformat(real[-1]) if real else None


def record(entry: dict) -> None:
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    with MANIFEST.open("a") as fh:
        fh.write(json.dumps(entry, sort_keys=True) + "\n")


def capture(f: Feed, session: date, today: date | None = None) -> dict:
    """Fetch, verify and archive one session. Never raises; the record is the
    deliverable, failures included."""
    today = today or datetime.now(UTC).date()
    url = url_for(f, session)
    base = {"source_id": f.source_id, "exchange": EXCHANGE,
            "report_type": f.report_type, "session_date": session.isoformat(),
            "url": url, "fetched_at": datetime.now(UTC).isoformat()}

    body: bytes | None = None
    err = ""
    for attempt in range(RETRIES):
        req = urllib.request.Request(url, headers={
            "User-Agent": UA, "Referer": "https://www.nseindia.com/", "Accept": "*/*"})
        try:
            def _get(req=req) -> bytes:
                with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                    return r.read()
            body = bounded(_get, DEADLINE, what=url)
            break
        except urllib.error.HTTPError as e:
            if e.code == 404:
                # A 404 on a past date is a holiday, not a failure.
                if session < today:
                    return {**base, "status": "NO_SESSION",
                            "note": "404 on a past date — NSE did not trade"}
                return {**base, "status": "PENDING", "note": "404, session not yet published"}
            err = f"HTTP {e.code} {e.reason}"
        except Exception as e:  # noqa: BLE001 - the record is the deliverable
            err = f"{type(e).__name__}: {e}"
        if attempt < RETRIES - 1:
            time.sleep(BACKOFF_BASE * (attempt + 1))

    if body is None:
        return {**base, "status": "FAILED", "error": err}
    if not body.startswith(f.magic):
        # A 200 that is not the payload. 0024 is why this is checked rather than
        # assumed: a retired endpoint answered 200 with an empty envelope for
        # weeks and every downstream count looked healthy.
        return {**base, "status": "FAILED", "bytes": len(body),
                "error": f"200 but payload does not start with {f.magic!r}"}

    digest = hash_bytes(body)
    dest = archive_path(f, session, digest)
    if dest.exists():
        return {**base, "status": "DUPLICATE", "sha256": digest, "bytes": len(body)}
    dest.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(dest, "wb") as fh:
        fh.write(body)
    return {**base, "status": "STORED", "sha256": digest, "bytes": len(body),
            "path": str(dest.relative_to(ARCHIVE))}


def main() -> int:
    today = datetime.now(UTC).date()
    rc = 0
    for f in FEEDS:
        todo = missing(f, f.earliest, today)
        print(f"DERIVATIVES {f.source_id}: {len(todo)} session(s) to fetch")
        counts: dict[str, int] = {}
        for session in todo:
            entry = capture(f, session, today)
            record(entry)
            counts[entry["status"]] = counts.get(entry["status"], 0) + 1
            if entry["status"] == "FAILED":
                rc = 1
            time.sleep(RATE_LIMIT)
        for k, v in sorted(counts.items()):
            print(f"    {k:<12} {v:>4}")
        st = staleness(f, last_session(f), today)
        print(st.render())
        if st.alerting:
            rc = 1
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
