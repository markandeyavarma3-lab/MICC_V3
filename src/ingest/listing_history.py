"""listing_history.py — when each symbol last traded in ANY series, 2005 to now.

WHY THIS EXISTS. The price spine is EQ-series only, by decision 0045: the seed
was EQ-only for twenty-one years and the collector matches it. So a company
that is moved from EQ into a surveillance series (BE trade-to-trade, BZ
non-compliant) vanishes from the spine and is indistinguishable there from a
company that was delisted. Measured 2026-10-01: of 483 symbols with no spine
price after 2026-08-14, 160 were still trading that day in BE or BZ, and most
of the rest were ETF units (decision 0040). `security_master` called every one
of them DELISTED, and step 6.4 prices a STOPPED event at its last close times
a recovery factor — the treatment for a company that is gone.

THE SOURCE. NSE's full bhavcopy, every series, every session:

    salvaged/v1_raw/bhavcopy/legacy   2005-2019   cm<DDMONYYYY>bhav.csv.zip   with ISIN
    salvaged/v1_raw/bhavcopy/secfull  2020-2026   sec_bhavdata_full_*.csv     symbol only
    salvaged/v1_raw/bhavcopy/udiff    2024-2026   BhavCopy_NSE_CM_*.csv.zip   with ISIN
    archive/PRICE/NSE                 2026-08 ->  the collector's own UDiFF   with ISIN

One source per session — UDiFF over sec_full over legacy, the archive over
everything — so a day held twice is counted once.

THE OUTPUT. One row per (symbol, series, isin): first and last session seen
and the number of sessions. An empty isin means the row came from sec_full,
which carries none; the same symbol's ISIN-bearing rows on either side say
which company it was. Nothing is decided here; `src/identity/master.py` reads
this to say whether a company that left the spine left the exchange.

THE KNOWN GAP. No full bhavcopy is held for 2026-06-26 .. the collector's
first session in August; the EQ seed covers that stretch for EQ only. A
non-EQ symbol whose last day falls just before the gap is therefore not
proof of a stop — master.py's tolerance must span it.
"""

from __future__ import annotations

import csv
import glob
import gzip
import io
import re
import sys
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.common.paths import ARCHIVE, COLLECTED, ROOT  # noqa: E402
from src.governance import provenance as prov  # noqa: E402

BHAV = ROOT / "data" / "raw" / "salvaged" / "v1_raw" / "bhavcopy"
OUT = COLLECTED / "listing" / "series_presence.parquet"
PRODUCED_BY = "src/ingest/listing_history.py"

#: Lower wins when two sources hold the same session.
PRECEDENCE = {"archive": 0, "udiff": 1, "secfull": 2, "legacy": 3}

_LEGACY = re.compile(r"cm(\d{2})([A-Z]{3})(\d{4})bhav\.csv\.zip$")
_SECFULL = re.compile(r"sec_bhavdata_full_(\d{2})(\d{2})(\d{4})\.csv$")
_UDIFF = re.compile(r"BhavCopy_NSE_CM_0_0_0_(\d{8})_F_0000\.csv\.zip$")
_ARCHIVE = re.compile(r"PRICE_NSE_(\d{8})_[0-9a-f]+\.csv\.zip\.gz$")


def session_of(path: str) -> tuple[str, str] | None:
    """(ISO date, source) from a filename, or None if it is not a bhavcopy."""
    name = Path(path).name
    if m := _ARCHIVE.search(name):
        return datetime.strptime(m.group(1), "%Y%m%d").date().isoformat(), "archive"
    if m := _UDIFF.search(name):
        return datetime.strptime(m.group(1), "%Y%m%d").date().isoformat(), "udiff"
    if m := _SECFULL.search(name):
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}", "secfull"
    if m := _LEGACY.search(name):
        return datetime.strptime("".join(m.groups()), "%d%b%Y").date().isoformat(), "legacy"
    return None


def _text(path: str) -> str:
    p = Path(path)
    data = p.read_bytes()
    if p.name.endswith(".gz"):
        data = gzip.decompress(data)
    if p.name.endswith(".zip") or p.name.endswith(".zip.gz"):
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            data = z.read(z.namelist()[0])
    return data.decode("utf-8", "replace")


def rows_of(path: str, source: str) -> list[tuple[str, str, str]]:
    """(symbol, series, isin) for every row of one session's file."""
    reader = csv.DictReader(io.StringIO(_text(path)))
    out = []
    for r in reader:
        r = {(k or "").strip(): (v or "").strip() for k, v in r.items()}
        if source in ("udiff", "archive"):
            sym, ser, isin = r.get("TckrSymb", ""), r.get("SctySrs", ""), r.get("ISIN", "")
        else:
            sym, ser, isin = r.get("SYMBOL", ""), r.get("SERIES", ""), r.get("ISIN", "")
        if sym:
            out.append((sym.upper(), ser.upper(), isin.upper()))
    return out


@dataclass
class Report:
    sessions: int = 0
    by_source: dict[str, int] = field(default_factory=dict)
    duplicates_skipped: int = 0
    unreadable: list[str] = field(default_factory=list)
    keys: int = 0
    first: str = ""
    last: str = ""

    def render(self) -> str:
        return "\n".join([
            f"  sessions            {self.sessions:>8,}  ({self.first} .. {self.last})",
            f"  by source           {self.by_source}",
            f"  same session held twice, lower-precedence copy skipped  {self.duplicates_skipped:,}",
            f"  unreadable files    {len(self.unreadable):>8,}"
            + (f"  e.g. {self.unreadable[:2]}" if self.unreadable else ""),
            f"  (symbol, series, isin) keys {self.keys:>8,}",
        ])


def files() -> tuple[dict[str, tuple[str, str]], int]:
    """session -> (path, source), one file per session by PRECEDENCE, and the
    number of lower-precedence copies set aside."""
    cands = (glob.glob(str(BHAV / "legacy" / "**" / "*.zip"), recursive=True)
             + glob.glob(str(BHAV / "secfull" / "**" / "*.csv"), recursive=True)
             + glob.glob(str(BHAV / "udiff" / "**" / "*.zip"), recursive=True)
             + glob.glob(str(ARCHIVE / "PRICE" / "NSE" / "**" / "*.gz"), recursive=True))
    best: dict[str, tuple[str, str]] = {}
    skipped = 0
    for p in sorted(cands):
        s = session_of(p)
        if not s:
            continue
        d, src = s
        if d in best:
            skipped += 1
            if PRECEDENCE[src] >= PRECEDENCE[best[d][1]]:
                continue
        best[d] = (p, src)
    return best, skipped


def build() -> Report:
    rep = Report()
    chosen, rep.duplicates_skipped = files()
    agg: dict[tuple[str, str, str], list] = {}
    for d in sorted(chosen):
        path, src = chosen[d]
        try:
            rows = rows_of(path, src)
        except (zipfile.BadZipFile, OSError, csv.Error, EOFError) as e:
            rep.unreadable.append(f"{Path(path).name}: {type(e).__name__}")
            continue
        rep.sessions += 1
        rep.by_source[src] = rep.by_source.get(src, 0) + 1
        for key in set(rows):
            a = agg.get(key)
            if a is None:
                agg[key] = [d, d, 1]
            else:
                a[1] = d
                a[2] += 1
    days = sorted(chosen)
    rep.first, rep.last = (days[0], days[-1]) if days else ("", "")
    rep.keys = len(agg)
    _write(agg)
    return rep


def _write(agg: dict[tuple[str, str, str], list]) -> None:
    import duckdb

    OUT.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    try:
        con.execute("CREATE TABLE t (symbol VARCHAR, series VARCHAR, isin VARCHAR,"
                    " first_date DATE, last_date DATE, sessions INTEGER)")
        con.executemany("INSERT INTO t VALUES (?, ?, ?, CAST(? AS DATE), CAST(? AS DATE), ?)",
                        [(*k, *v) for k, v in agg.items()])
        tmp = OUT.with_suffix(".parquet.partial")
        con.execute(f"COPY (SELECT * FROM t ORDER BY symbol, series, isin) TO '{tmp}' (FORMAT PARQUET)")
        tmp.replace(OUT)
    finally:
        con.close()


def main() -> int:
    print("LISTING HISTORY — every series, every session, from the full bhavcopy")
    rep = build()
    print(rep.render())
    prov.register_dataset(
        OUT.parent, artefact_type="SOURCE", logical_name="collected:listing",
        produced_by=PRODUCED_BY, pattern="*.parquet",
        params={"sources": sorted(PRECEDENCE), "sessions": rep.sessions})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
