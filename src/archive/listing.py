"""listing.py — NSE's lists of companies now listed, main board and SME.

WHY (2026-11-06). 1,020 symbols in the deal data had no ISIN or company name:
`security_master` holds main-board equities, and bulk deals also name the SME
platform. Without an ISIN a page cannot reach its shareholding or fund holdings.
These two public files name 661 of them (564 SME, 97 main board). The other 359
are not listed today, mostly dead or renamed, and stay unnamed.

A snapshot of today, not a history: a company that delisted is simply absent, so
it can name a symbol but never date one. The site uses it only for a symbol the
identity layer does not know (src/site/export.py); `security_master` is untouched.

    RESEARCH_ENV=prod .venv/bin/python -m src.archive.listing
"""

from __future__ import annotations

import csv
import gzip
import io
import sys
import time
from datetime import date
from functools import lru_cache
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.archive import corporate_actions as ca  # noqa: E402
from src.common.paths import ARCHIVE  # noqa: E402

ROOT_DIR = ARCHIVE / "LISTING"
ROUTES = {"main": "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv",
          "sme": "https://nsearchives.nseindia.com/emerge/corporates/content/SME_EQUITY_L.csv"}
REFERER = "https://www.nseindia.com/market-data/securities-available-for-trading"
RATE_LIMIT = 2.0
#: The two files name their columns differently (spaces against underscores).
_NAME = ("NAME OF COMPANY", "NAME_OF_COMPANY")
_ISIN = ("ISIN NUMBER", "ISIN_NUMBER")
_LISTED = ("DATE OF LISTING", "DATE_OF_LISTING")


def parse(body: bytes) -> dict[str, dict]:
    """symbol -> {isin, co, listed}. Rows without a symbol, name or ISIN are skipped."""
    out: dict[str, dict] = {}
    for raw in csv.DictReader(io.StringIO(body.decode("utf-8", "replace"))):
        r = {(k or "").strip(): (v or "").strip() for k, v in raw.items() if k}
        pick = lambda names: next((r[n] for n in names if r.get(n)), "")  # noqa: E731, B023
        sym, co, isin = r.get("SYMBOL", "").upper(), pick(_NAME), pick(_ISIN)
        if sym and co and isin:
            out[sym] = {"isin": isin, "co": co, "listed": pick(_LISTED)}
    return out


def fetch(root: Path | None = None) -> dict[str, int]:
    """Today's two files into the archive; a file that fails keeps yesterday's."""
    root = root or ROOT_DIR
    root.mkdir(parents=True, exist_ok=True)
    op, got = ca._opener(), {}
    for name, url in ROUTES.items():
        time.sleep(RATE_LIMIT)
        body = ca._get(op, url, REFERER)
        n = len(parse(body))
        if not n:
            raise ValueError(f"{name}: no usable rows in {len(body)} bytes; not stored")
        dest = root / f"{name}_{date.today().isoformat()}.csv.gz"
        tmp = dest.with_suffix(".partial")
        tmp.write_bytes(gzip.compress(body))
        tmp.replace(dest)
        got[name] = n
    return got


def latest(root: Path | None = None) -> dict[str, dict]:
    """symbol -> {isin, co, listed} from the newest file of each list; main board
    wins for a symbol that has moved up from SME."""
    root = root or ROOT_DIR
    out: dict[str, dict] = {}
    for name in ("sme", "main"):
        files = sorted(root.glob(f"{name}_*.csv.gz"))
        if files:
            out.update(parse(gzip.decompress(files[-1].read_bytes())))
    return out


@lru_cache(maxsize=1)
def sme_symbols() -> frozenset[str]:
    """Symbols on the SME platform today, not also on the main board. NSE files
    their results and shareholding under `index=sme`; asked under `index=equities`
    every one of 566 answered empty (measured 2026-11-06)."""
    files = sorted(ROOT_DIR.glob("sme_*.csv.gz"))
    if not files:
        return frozenset()
    main_files = sorted(ROOT_DIR.glob("main_*.csv.gz"))
    board = set(parse(gzip.decompress(main_files[-1].read_bytes()))) if main_files else set()
    return frozenset(set(parse(gzip.decompress(files[-1].read_bytes()))) - board)


def index_of(symbol: str) -> str:
    """The `index=` NSE's company endpoints file this symbol under."""
    return "sme" if symbol in sme_symbols() else "equities"


def asked_rightly(symbol: str, url: str) -> bool:
    """False for an SME symbol asked under the main board's index: an empty answer
    to the wrong question, which must not count as fresh."""
    return symbol not in sme_symbols() or "index=sme" in url


def main() -> int:
    got = fetch()
    print(f"  LISTING: {got} -> {ROOT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
