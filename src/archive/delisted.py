"""delisted.py — NSE's own list of delisted companies, with the type of each.

WHAT IT IS. `nsearchives.nseindia.com/content/equities/delisted.csv`: Symbol,
Company, Delisted Date, Type of Delisting. Found 2026-10-01 while building the
delisting classifier (step 3.3). Measured that day: 329 rows, 2002-04-15 ..
2020-11-09 — NSE appears to have stopped maintaining the file in late 2020 —
with three types: Compulsory Delisting (137), Delisting - Liquidation (99) and
Voluntary Delisting (92).

WHAT IT IS NOT. Mergers are absent. An amalgamated company's shares are
extinguished under a court- or NCLT-sanctioned scheme; NSE does not call that
a delisting, so a merged company is simply not on this list. Absence from the
list therefore proves nothing.

Fetched once per run like any other source: the bytes are archived as served
and the parser reads the newest copy. If NSE ever resumes the file, the next
run picks it up; if it disappears, the archived copy stands.
"""

from __future__ import annotations

import csv
import glob
import gzip
import io
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.archive import probe  # noqa: E402
from src.common.paths import ARCHIVE  # noqa: E402

SOURCE_ID = "nse_delisted_list"
EXCHANGE = "NSE"
REPORT_TYPE = "DELISTED"
URL = "https://nsearchives.nseindia.com/content/equities/delisted.csv"

#: NSE's type -> security_master.delisting_reason (configs/universe.yml).
#: Voluntary delisting is a buy-out of the public at a discovered exit price —
#: the holder is paid, which is what ACQUISITION means here. Compulsory
#: delisting and liquidation both leave the public holder with shares that no
#: longer trade, and the plan's class for that is SUSPENSION.
TYPE_TO_REASON = {
    "voluntary delisting": "ACQUISITION",
    "compulsory delisting": "SUSPENSION",
    "delisting - liquidation": "SUSPENSION",
}


def capture(today: date | None = None, dry_run: bool = False) -> dict:
    return probe.probe(
        source_id=SOURCE_ID, exchange=EXCHANGE, report_type=REPORT_TYPE, url=URL,
        session=today or date.today(),
        validate=probe.csv_with_header("Symbol", "Type of Delisting", min_rows=100),
        dry_run=dry_run)


def parse(body: bytes) -> list[dict]:
    """[{symbol, company, delisted_on, type, reason}] — reason None for a type
    this module does not know, which is information, not a row to drop."""
    text = body.decode("latin-1")   # served in Windows-1252; utf-8 fails on it
    out = []
    for r in csv.DictReader(io.StringIO(text)):
        sym = (r.get("Symbol") or "").strip().upper()
        if not sym:
            continue
        typ = (r.get("Type of Delisting") or "").strip()
        raw = (r.get("Delisted Date") or "").strip()
        try:
            on = datetime.strptime(raw, "%d-%b-%y").date().isoformat()
        except ValueError:
            on = ""
        out.append({"symbol": sym, "company": (r.get("Company") or "").strip(),
                    "delisted_on": on, "type": typ,
                    "reason": TYPE_TO_REASON.get(typ.lower())})
    return out


def latest() -> list[dict]:
    """The newest archived copy, parsed; [] if none has been archived."""
    files = sorted(glob.glob(str(ARCHIVE / REPORT_TYPE / EXCHANGE / "**" / "*.gz"), recursive=True))
    return parse(gzip.decompress(Path(files[-1]).read_bytes())) if files else []


def main() -> int:
    r = capture()
    print(f"  {r['status']:<9} {URL}  {r.get('bytes', 0):,} B {r.get('error', '')}")
    return 0 if r["status"] in ("STORED", "DUPLICATE") else 1


if __name__ == "__main__":
    raise SystemExit(main())
