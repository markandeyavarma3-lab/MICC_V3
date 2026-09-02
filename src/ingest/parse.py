"""parse.py — turn archived bytes into rows, without ever losing the bytes.

WHAT THIS IS AND IS NOT. `src/archive/stopgap.py` deliberately refuses to parse:
its job is to capture bytes before the endpoint rolls over, and every extra
responsibility is another way for that to fail on a night when a session is
unrecoverable. This module is the other half — it reads what the stopgap stored,
at leisure, as many times as we get it wrong.

THE RULE THAT MAKES RE-PARSING SAFE. Parsing NEVER touches the archive. Files are
opened read-only, and a parse failure produces a recorded failure rather than an
exception that stops a batch. Plan 1 §5.1: *"A parse failure still archives the
bytes and records the failure. That is the difference between a system that can
recover from a source format change and one that silently loses a day."* The
bytes are already safe when this runs; the only thing a bug here can cost is the
time to fix it.

VERBATIM, THEN CLEAN — NEVER BOTH AT ONCE. `institutional_deals_raw` (Plan 1
§5.3) stores source rows exactly as published: quantity and price as TEXT,
because the source sometimes carries commas and once shipped a hyphen where a
price belonged. Cleaning happens downstream where it can be versioned and undone.
A parser that both reads and repairs makes the repair invisible.

THE TWO FORMATS DIFFER, AND THE DIFFERENCE IS LOAD-BEARING. Measured against the
live archive on 2026-08-23: bulk carries eight columns and block seven — block
has no `Remarks`. Reading them with one schema silently shifts every field.
"""

from __future__ import annotations

import csv
import gzip
import io
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from src.common.hashing import hash_file
from src.common.paths import ARCHIVE

Status = Literal["OK", "PARSE_FAILED", "EMPTY"]

#: The stopgap's sentinel for a legitimately empty day. Distinguishing "no deals"
#: from "the fetch broke" is the whole difference between an honest ingestion log
#: and a guess.
EMPTY_SENTINEL = "NO RECORDS"

#: Canonical column order, matching the V1 seed's bulk_deals/block_deals schema
#: so newly collected sessions extend the historical corpus rather than forming a
#: second, differently-shaped one.
CANONICAL = ("date", "symbol", "name", "client", "buy_sell", "qty", "price", "remarks")

#: Source header -> canonical field. Bulk and block share all but `remarks`.
_CSV_MAP = {
    "date": "date",
    "symbol": "symbol",
    "security name": "name",
    "client name": "client",
    "buy/sell": "buy_sell",
    "quantity traded": "qty",
    "trade price / wght. avg. price": "price",
    "remarks": "remarks",
}


class ParseError(RuntimeError):
    """Raised only for programming errors. A malformed SOURCE is a recorded
    PARSE_FAILED, never an exception — that distinction is the point."""


@dataclass(frozen=True, slots=True)
class ParsedFile:
    path: Path
    sha256: str
    report_type: str
    exchange: str
    status: Status
    session_date: str | None = None
    rows: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.status in ("OK", "EMPTY")


def _iso(raw: str) -> str | None:
    """NSE writes 21-AUG-2026. Returns ISO, or None rather than guessing."""
    for fmt in ("%d-%b-%Y", "%d-%B-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw.strip(), fmt).date().isoformat()
        except ValueError:
            continue
    return None


def parse_csv(body: bytes, report_type: str) -> tuple[Status, list[dict], str | None]:
    """Bulk and block deals. Header-driven, never positional.

    Positional parsing is why the eight-vs-seven column difference between bulk
    and block would shift every field silently. Mapping by header name means an
    added column is ignored and a REMOVED one is visible as a missing key.
    """
    text = body.decode("utf-8", errors="replace")
    if EMPTY_SENTINEL in text[:4096].upper():
        return "EMPTY", [], None

    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except StopIteration:
        return "EMPTY", [], None

    cols = [_CSV_MAP.get(h.strip().lower()) for h in header]
    if "date" not in [c for c in cols if c] or "symbol" not in [c for c in cols if c]:
        return "PARSE_FAILED", [], f"unrecognised header for {report_type}: {header}"

    rows: list[dict] = []
    for idx, raw_row in enumerate(reader):
        if not any(cell.strip() for cell in raw_row):
            continue
        rec: dict[str, Any] = {k: None for k in CANONICAL}
        for col, cell in zip(cols, raw_row, strict=False):
            if col:
                rec[col] = cell.strip()
        # Kept verbatim; the ISO form is added alongside, not in place of it.
        rec["session_date"] = _iso(rec["date"] or "")
        rec["row_index"] = idx
        rec["raw_row_json"] = json.dumps(dict(zip(header, raw_row, strict=False)))
        rows.append(rec)

    if not rows:
        return "EMPTY", [], None
    if all(r["session_date"] is None for r in rows):
        return "PARSE_FAILED", [], "no row carried a parseable date"
    return "OK", rows, None


def parse_fii_dii(body: bytes) -> tuple[Status, list[dict], str | None]:
    """/api/fiidiiTradeReact — one record per category per session."""
    try:
        payload = json.loads(body.decode("utf-8", errors="replace"))
    except json.JSONDecodeError as exc:
        return "PARSE_FAILED", [], f"invalid json: {exc}"
    if not isinstance(payload, list) or not payload:
        return "EMPTY", [], None

    rows = []
    for idx, item in enumerate(payload):
        if not isinstance(item, dict):
            return "PARSE_FAILED", [], f"row {idx} is not an object"
        rows.append({
            "session_date": _iso(str(item.get("date", ""))),
            "category": item.get("category"),
            "buy_value": item.get("buyValue"),
            "sell_value": item.get("sellValue"),
            "net_value": item.get("netValue"),
            "row_index": idx,
            "raw_row_json": json.dumps(item, sort_keys=True),
        })
    return "OK", rows, None


def parse_archive(path: Path | str) -> ParsedFile:
    """Parse one archived file. Read-only, and never raises on bad content."""
    p = Path(path)
    parts = p.parts
    report_type = next((x for x in parts if x in ("BULK", "BLOCK", "FII_DII")), "UNKNOWN")
    exchange = "NSE" if "NSE" in parts else "UNKNOWN"

    try:
        with gzip.open(p, "rb") as fh:
            body = fh.read()
    except OSError as exc:
        return ParsedFile(p, "", report_type, exchange, "PARSE_FAILED",
                          error=f"unreadable archive: {exc}")

    digest = hash_file(p)
    if report_type == "FII_DII":
        status, rows, err = parse_fii_dii(body)
    else:
        status, rows, err = parse_csv(body, report_type)

    session = next((r["session_date"] for r in rows if r.get("session_date")), None)
    return ParsedFile(p, digest, report_type, exchange, status,
                      session_date=session, rows=tuple(rows), error=err)


#: The report types THIS parser understands. Declared, not inferred.
#:
#: BROKEN 2026-09-01, FIXED 2026-09-02. `iter_archive` used to rglob every
#: `*.gz` under the archive, which was correct while the archive held only deal
#: CSVs. Three collectors were then added — PRICE (`.csv.zip.gz`), INSIDER
#: (`.xml.gz`) and CORPACT (`.json.gz`) — and the glob swallowed all of them.
#: `parse_csv` hit a gzipped ZIP, raised an unhandled `_csv.Error`, and
#: `python -m src.ingest.land` died on the first PRICE file.
#:
#: The consequence was silent and total: no collected deal reached
#: `institutional_deals_raw` after 2026-08-28, while every collector kept
#: reporting success and the daily job stayed green — because land.py is not in
#: `collect_daily.sh` and nothing else calls it.
#:
#: `parse_archive` already knew this set; it defaulted anything else to
#: report_type "UNKNOWN" and tried to parse it anyway. The knowledge existed one
#: function away from where it was needed.
DEAL_REPORT_TYPES: tuple[str, ...] = ("BULK", "BLOCK", "FII_DII")


def iter_archive(root: Path | None = None) -> list[Path]:
    """Every archived DEAL payload, oldest first. Excludes the manifest.

    Restricted to `DEAL_REPORT_TYPES` on purpose: a new collector must be
    parsed by code that understands its format, and adding one must not
    silently redirect its bytes into this parser.
    """
    base = root or ARCHIVE
    return sorted(
        p for t in DEAL_REPORT_TYPES for p in (base / t).rglob("*.gz") if p.is_file()
    )


def parse_all(root: Path | None = None) -> list[ParsedFile]:
    return [parse_archive(p) for p in iter_archive(root)]


def main() -> int:
    files = parse_all()
    print(f"ARCHIVE PARSE — {len(files)} file(s)")
    by_status: dict[str, int] = {}
    total = 0
    for f in files:
        by_status[f.status] = by_status.get(f.status, 0) + 1
        total += len(f.rows)
        print(f"  {f.status:<13} {f.report_type:<8} session={f.session_date} "
              f"rows={len(f.rows):>4}  {f.sha256[:8]}"
              + (f"  ERROR: {f.error}" if f.error else ""))
    print(f"\n  {total:,} rows parsed; " + ", ".join(f"{k}={v}" for k, v in sorted(by_status.items())))
    return 1 if by_status.get("PARSE_FAILED") else 0


if __name__ == "__main__":
    raise SystemExit(main())
