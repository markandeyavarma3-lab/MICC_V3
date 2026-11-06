"""sme_prices.py — closing prices of SME-platform shares, for the site only.

WHY (2026-11-06). The price spine is main-board by decision (0045), so a company on
NSE's SME platform had a page with no price chart. The exchange's own bhavcopies,
already held, carry those rows as series SM and ST: the salvaged files back to 2012
and the archive since. This reads them into one table the site uses when a symbol
has no spine price. No research reads it.

AS TRADED. Nothing here adjusts for a split or bonus, so a chart can step at one, and
the page says so.

Two parts, because the salvaged files never change and take minutes to read: a
baseline written once, and the archive read every night in seconds.

    RESEARCH_ENV=prod .venv/bin/python -m src.site.sme_prices
"""

from __future__ import annotations

import csv
import gzip
import io
import re
import sys
import zipfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.common.paths import ARCHIVE, ROOT, SALVAGED  # noqa: E402

OUT = ROOT / "data" / "derived" / "sme_prices.parquet"
BASELINE = ROOT / "data" / "derived" / "sme_prices_salvaged.parquet"
SERIES = {"SM", "ST"}
#: NSE's SME platform opened in 2012: no point reading the seven years before it.
FIRST_YEAR = 2012
_DATES = ("%d-%b-%Y", "%Y-%m-%d", "%d-%m-%Y", "%d-%B-%Y")


def _iso(s: str) -> str | None:
    s = (s or "").strip()
    for fmt in _DATES:
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def rows_of(text: str) -> list[tuple[str, str, float, str]]:
    """(symbol, date, close, series) for the SME rows of one bhavcopy, in any of
    the three layouts NSE has used: legacy, sec_bhavdata_full and UDiFF."""
    out = []
    for raw in csv.DictReader(io.StringIO(text)):
        r = {(k or "").strip().upper(): (v or "").strip() for k, v in raw.items() if k}
        series = r.get("SCTYSRS") or r.get("SERIES") or ""
        if series not in SERIES:
            continue
        sym = r.get("TCKRSYMB") or r.get("SYMBOL") or ""
        day = _iso(r.get("TRADDT") or r.get("DATE1") or r.get("TIMESTAMP") or "")
        try:
            close = float(r.get("CLSPRIC") or r.get("CLOSE_PRICE") or r.get("CLOSE") or "")
        except ValueError:
            continue
        if sym and day and close > 0:
            out.append((sym.upper(), day, close, series))
    return out


def _text_of(path: Path) -> str:
    body = path.read_bytes()
    if path.suffix == ".gz":
        body = gzip.decompress(body)
    if body[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(body)) as z:
            body = z.read(z.namelist()[0])
    return body.decode("utf-8", "replace")


def _read(paths: list[Path]) -> list[tuple]:
    out: list[tuple] = []
    for p in paths:
        try:
            out.extend(rows_of(_text_of(p)))
        except (OSError, ValueError, zipfile.BadZipFile, csv.Error) as e:
            print(f"  skipped {p.name}: {e}")
    return out


def _salvaged_files() -> list[Path]:
    root = SALVAGED / "v1_raw" / "bhavcopy"
    legacy = [p for p in (root / "legacy").rglob("cm*bhav.csv.zip")
              if (m := re.search(r"(\d{4})bhav", p.name)) and int(m.group(1)) >= FIRST_YEAR]
    return legacy + sorted((root / "secfull").rglob("*.csv")) + sorted((root / "udiff").rglob("*.zip"))


def _write(rows: list[tuple], dest: Path) -> None:
    import duckdb
    con = duckdb.connect()
    try:
        con.execute("CREATE TABLE t (symbol VARCHAR, date VARCHAR, close DOUBLE, series VARCHAR)")
        if rows:
            con.executemany("INSERT INTO t VALUES (?,?,?,?)", rows)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(".partial")
        # One row per symbol and day; a day two files both carry reads the same.
        con.execute(f"""COPY (SELECT symbol, date, any_value(close) AS close, any_value(series) AS series
                              FROM t GROUP BY 1, 2 ORDER BY 1, 2) TO '{tmp}' (FORMAT PARQUET)""")
        tmp.replace(dest)
    finally:
        con.close()


def build() -> int:
    """The baseline if it is missing, plus the archive, into OUT. Returns rows."""
    import duckdb
    if not BASELINE.exists():
        files = _salvaged_files()
        if not files:
            raise FileNotFoundError(f"no salvaged bhavcopies under {SALVAGED}: an empty baseline would never be rebuilt")
        _write(_read(files), BASELINE)
    _write(_read(sorted((ARCHIVE / "PRICE").glob("**/*.gz"))), OUT.with_name("sme_prices_archive.parquet"))
    arch = OUT.with_name("sme_prices_archive.parquet")
    con = duckdb.connect()
    try:
        tmp = OUT.with_suffix(".partial")
        con.execute(f"""COPY (SELECT symbol, date, any_value(close) AS close, any_value(series) AS series
                              FROM read_parquet(['{BASELINE}', '{arch}']) GROUP BY 1, 2 ORDER BY 1, 2)
                        TO '{tmp}' (FORMAT PARQUET)""")
        tmp.replace(OUT)
        return con.execute(f"SELECT COUNT(*) FROM read_parquet('{OUT}')").fetchone()[0]
    finally:
        con.close()


def weekly(path: Path | None = None) -> dict[str, list]:
    """symbol -> [[last day of the week, close], ...], the shape of the site's price line."""
    import duckdb
    path = path or OUT
    if not path.exists():
        return {}
    con = duckdb.connect()
    try:
        out: dict[str, list] = {}
        for sym, d, c in con.execute(f"""
                SELECT symbol, MAX(date), arg_max(close, date) FROM read_parquet('{path}')
                GROUP BY symbol, strftime(CAST(date AS DATE), '%G-%V') ORDER BY 1, 2""").fetchall():
            out.setdefault(sym, []).append([d, round(c, 2)])
        return out
    finally:
        con.close()


def main() -> int:
    n = build()
    print(f"  SME PRICES: {n:,} stock-days -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
