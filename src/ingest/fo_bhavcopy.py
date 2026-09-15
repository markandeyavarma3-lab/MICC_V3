"""fo_bhavcopy.py — UDiFF F&O bhavcopy and participant-wise OI bytes -> frames.

WHAT THIS IS, AND WHAT IT DELIBERATELY IS NOT.

Decision 0058 resumed collecting two derivatives feeds and forbade parsing
them: the legacy `fno_spine` names none of the 34 UDiFF columns the same way,
and an invented map would have been the parsing that workstream was told not
to do. Decision 0062 lifts that boundary for CODE AND FIXTURES ONLY. This
module turns archived bytes into DataFrames in the legacy shape and proves
the map on real rows. It does not land anything: there is no function here
that takes an env and writes a spine, no DuckDB connection, no import of
`src.common.paths`. `write_legacy` exists for tests and refuses any path
under the repository's `data/` or `db/`. Wiring into `collect_daily.sh`, the
prod land step, and any analysis are later decisions with their own records.

THE MAP IS READ FROM REAL BYTES, NOT GUESSED. `handover_delta4/06_FNO_MAP.md`
records the 34-column header of the 2026-09-10 file, the 15-column
participant-OI header, the legacy conventions observed on the spine, and the
unit checks (RELIANCE 26SEP fut: 18,697 contracts x lot 500 x ~1,278 =
11.94 bn = TtlTrfVal, so TtlTradgVol is contracts and TtlTrfVal is rupees).

TWO CONVENTIONS THE DATA IMPOSES ON THE OUTPUT.

- Futures carry `strike = 0.0` and `option_typ = 'XX'`, as every legacy
  futures row does. `spine.py`'s comment says NULL; 17,890 rows say
  otherwise, and a stretch dated 2026-06-17..07-07 that a V1 increment loaded
  with raw UDiFF codes and NULL futures fields is already a defect in the
  spine. This parser does not add to it.
- `instrument` is the legacy code (`FUTIDX/FUTSTK/OPTIDX/OPTSTK`), mapped
  from `FinInstrmTp` (`IDF/STF/IDO/STO`). Any other code raises. Nothing is
  dropped silently: a bad price, a second `TradDt`, a sixth category, all
  raise.

TOTAL IS KEPT. The participant-OI file's `TOTAL` row is the source's own sum
of the other four categories. Migration 0004 keeps it as a fifth category so
that a naive `GROUP BY session_date` is wrong by a visible factor of two
rather than silently right by accident. This parser never aggregates across
categories.

UNITS DIFFER BETWEEN THE TWO FEEDS. The bhavcopy's `open_int` is in shares;
the participant file is "no. of contracts" (its own title says so). Neither
is converted here.
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from datetime import date, datetime
from pathlib import Path

import pandas as pd


class FoParseError(ValueError):
    """A row or file the map does not cover. Raised, never skipped."""


# --- UDiFF -> legacy fno_spine ------------------------------------------------

#: legacy column -> the UDiFF column it is sourced from. The transform is in
#: `to_legacy_spine`; this is the declaration a test checks against
#: `spine.FNO.columns` so an unsourced column cannot appear as NULLs.
LEGACY_FROM_UDIFF: dict[str, str] = {
    "date": "TradDt",
    "instrument": "FinInstrmTp",
    "symbol": "TckrSymb",
    "expiry": "XpryDt",
    "strike": "StrkPric",
    "option_typ": "OptnTp",
    "open": "OpnPric",
    "high": "HghPric",
    "low": "LwPric",
    "close": "ClsPric",
    "settle_pr": "SttlmPric",
    "contracts": "TtlTradgVol",
    "val_inlakh": "TtlTrfVal",
    "open_int": "OpnIntrst",
    "chg_in_oi": "ChngInOpnIntrst",
}

#: Read as guards (must be FO / NSE), never carried.
UDIFF_GUARD_COLUMNS: tuple[str, ...] = ("Sgmt", "Src")

#: UDiFF columns with no home in the 15-column legacy spine. Named so the
#: discard is explicit. `UndrlygPric` (spot at close) and `NewBrdLotQty` (lot
#: size, converts open_int shares <-> contracts) are the two a future schema
#: would want; the rest are constants, empties, or derivable.
SIDECAR_COLUMNS: tuple[str, ...] = (
    "BizDt", "FinInstrmId", "ISIN", "SctySrs", "FininstrmActlXpryDt",
    "FinInstrmNm", "LastPric", "PrvsClsgPric", "UndrlygPric",
    "TtlNbOfTxsExctd", "SsnId", "NewBrdLotQty", "Rmks",
    "Rsvd1", "Rsvd2", "Rsvd3", "Rsvd4",
)

INSTRUMENT: dict[str, str] = {
    "IDF": "FUTIDX",
    "STF": "FUTSTK",
    "IDO": "OPTIDX",
    "STO": "OPTSTK",
}

#: The spine's column order, restated from the map so this module has no
#: import from src.warehouse (which imports paths). A test asserts equality.
LEGACY_COLUMNS: tuple[str, ...] = tuple(LEGACY_FROM_UDIFF)

_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _csv_bytes(body: bytes) -> bytes:
    """The CSV inside a zip, or the bytes themselves if they are already CSV."""
    if body[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(body)) as z:
            members = [m for m in z.namelist() if m.lower().endswith(".csv")]
            if len(members) != 1:
                raise FoParseError(f"expected one .csv in the zip, found {z.namelist()}")
            return z.read(members[0])
    return body


def parse_udiff_bytes(body: bytes) -> pd.DataFrame:
    """UDiFF F&O bhavcopy (zip or csv bytes) -> one row per contract, all 34
    columns as strings. Nothing is interpreted here; `to_legacy_spine` does
    that, so the full width is available to anything that wants the sidecar."""
    text = _csv_bytes(body).decode("utf-8")
    reader = csv.reader(io.StringIO(text))
    header = [h.strip() for h in next(reader)]
    if len(header) != 34 or header[:4] != ["TradDt", "BizDt", "Sgmt", "Src"]:
        raise FoParseError(f"not a UDiFF F&O header ({len(header)} columns): {header[:6]}")
    rows = [r for r in reader if r and any(c.strip() for c in r)]
    for i, r in enumerate(rows, start=2):
        if len(r) != 34:
            raise FoParseError(f"line {i}: {len(r)} fields, expected 34")
    return pd.DataFrame(rows, columns=header, dtype=str)


def _float(v: str, what: str) -> float:
    try:
        return float(v)
    except ValueError as exc:
        raise FoParseError(f"{what}: unparseable number {v!r}") from exc


def _int(v: str, what: str) -> int:
    try:
        return int(float(v))
    except ValueError as exc:
        raise FoParseError(f"{what}: unparseable integer {v!r}") from exc


def to_legacy_spine(df: pd.DataFrame) -> pd.DataFrame:
    """34-column UDiFF frame -> the 15-column legacy `fno_spine` shape.

    Zero silent drops: every input row is an output row or an exception.
    """
    missing = [c for c in list(LEGACY_FROM_UDIFF.values()) + list(UDIFF_GUARD_COLUMNS) if c not in df.columns]
    if missing:
        raise FoParseError(f"UDiFF frame lacks {missing}")

    bad_seg = df[(df["Sgmt"] != "FO") | (df["Src"] != "NSE")]
    if len(bad_seg):
        raise FoParseError(f"{len(bad_seg)} row(s) not Sgmt=FO/Src=NSE: {bad_seg.iloc[0].to_dict()}")

    sessions = sorted(set(df["TradDt"].str.strip()))
    if len(sessions) != 1 or not _ISO.match(sessions[0]):
        raise FoParseError(f"expected one ISO TradDt, found {sessions[:5]}")
    session = sessions[0]

    out: list[dict] = []
    for i, r in enumerate(df.itertuples(index=False), start=1):
        rec = r._asdict()
        code = rec["FinInstrmTp"].strip()
        if code not in INSTRUMENT:
            raise FoParseError(
                f"row {i}: FinInstrmTp {code!r} has no legacy instrument; "
                f"known: {sorted(INSTRUMENT)}"
            )
        instrument = INSTRUMENT[code]
        is_option = instrument.startswith("OPT")
        strike_raw = rec["StrkPric"].strip()
        optn = rec["OptnTp"].strip()
        if is_option:
            if optn not in ("CE", "PE") or not strike_raw:
                raise FoParseError(f"row {i}: option without CE/PE and strike: {optn!r} {strike_raw!r}")
            strike = _float(strike_raw, f"row {i} StrkPric")
            option_typ = optn
        else:
            if optn or strike_raw:
                raise FoParseError(f"row {i}: future carrying option fields: {optn!r} {strike_raw!r}")
            strike, option_typ = 0.0, "XX"
        expiry = rec["XpryDt"].strip()
        if not _ISO.match(expiry):
            raise FoParseError(f"row {i}: XpryDt {expiry!r} is not ISO")
        tag = f"row {i} {rec['TckrSymb'].strip()}"
        out.append({
            "date": session,
            "instrument": instrument,
            "symbol": rec["TckrSymb"].strip(),
            "expiry": expiry,
            "strike": strike,
            "option_typ": option_typ,
            "open": _float(rec["OpnPric"], tag),
            "high": _float(rec["HghPric"], tag),
            "low": _float(rec["LwPric"], tag),
            "close": _float(rec["ClsPric"], tag),
            "settle_pr": _float(rec["SttlmPric"], tag),
            "contracts": _int(rec["TtlTradgVol"], tag),
            "val_inlakh": _float(rec["TtlTrfVal"], tag) / 1e5,
            "open_int": _int(rec["OpnIntrst"], tag),
            "chg_in_oi": _int(rec["ChngInOpnIntrst"], tag),
        })
    leg = pd.DataFrame(out, columns=list(LEGACY_COLUMNS))
    for c in ("contracts", "open_int", "chg_in_oi"):
        leg[c] = leg[c].astype("int64")
    for c in ("strike", "open", "high", "low", "close", "settle_pr", "val_inlakh"):
        leg[c] = leg[c].astype("float64")
    key = ["date", "instrument", "symbol", "expiry", "strike", "option_typ"]
    dupes = int(leg.duplicated(subset=key).sum())
    if dupes:
        raise FoParseError(f"{session}: {dupes} duplicate contract row(s) on the spine key")
    return leg


def write_legacy(df: pd.DataFrame, path: Path) -> Path:
    """Write a legacy-shape frame to parquet — FOR TESTS. Refuses anything
    under the repository's data/ or db/; landing to prod is a separate,
    later decision with its own record."""
    path = Path(path).resolve()
    repo = Path(__file__).resolve().parents[2]
    for forbidden in (repo / "data", repo / "db"):
        if forbidden == path or forbidden in path.parents:
            raise FoParseError(f"refusing to write under {forbidden}: this module does not land")
    if list(df.columns) != list(LEGACY_COLUMNS):
        raise FoParseError("frame is not in the legacy spine shape")
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    return path


# --- participant-wise OI -----------------------------------------------------

#: source header (after strip) -> table column. Order is the migration's.
#: `index_fut_net` / `stock_fut_net` are derived, not sourced.
PARTICIPANT_OI_FROM_SOURCE: dict[str, str] = {
    "index_fut_long": "Future Index Long",
    "index_fut_short": "Future Index Short",
    "index_call_long": "Option Index Call Long",
    "index_call_short": "Option Index Call Short",
    "index_put_long": "Option Index Put Long",
    "index_put_short": "Option Index Put Short",
    "stock_fut_long": "Future Stock Long",
    "stock_fut_short": "Future Stock Short",
    "stock_call_long": "Option Stock Call Long",
    "stock_put_long": "Option Stock Put Long",
}

#: Source columns with no home in migration 0004. Named, not lost.
PARTICIPANT_OI_SIDECAR: tuple[str, ...] = (
    "Option Stock Call Short", "Option Stock Put Short",
    "Total Long Contracts", "Total Short Contracts",
)

#: All 14 numeric source columns, for the TOTAL = sum check.
PARTICIPANT_OI_SOURCE_NUMERIC: tuple[str, ...] = tuple(PARTICIPANT_OI_FROM_SOURCE.values()) + PARTICIPANT_OI_SIDECAR

#: The same 14, as they are named in the parsed frame: table names for the
#: ten that have a home, source names for the four sidecar columns. The two
#: derived `*_net` columns are not source-backed and are not listed.
PARTICIPANT_OI_SOURCE_BACKED: tuple[str, ...] = tuple(PARTICIPANT_OI_FROM_SOURCE) + PARTICIPANT_OI_SIDECAR

PARTICIPANT_OI_TABLE_COLUMNS: tuple[str, ...] = (
    "session_date", "category",
    "index_fut_long", "index_fut_short", "index_fut_net",
    "index_call_long", "index_call_short", "index_put_long", "index_put_short",
    "stock_fut_long", "stock_fut_short", "stock_fut_net",
    "stock_call_long", "stock_put_long",
)

CATEGORIES: frozenset[str] = frozenset({"Client", "DII", "FII", "Pro", "TOTAL"})

_TITLE_DATE = re.compile(r"as on\s+([A-Za-z]{3}\s+\d{1,2},\s*\d{4})")


def parse_participant_oi_bytes(body: bytes, session_date: date | None = None) -> pd.DataFrame:
    """NSE participant-wise OI csv -> five rows (one per category), every source
    column as a number, table-named columns plus the sidecar, plus
    `session_date` read from the title line. If `session_date` is given (from
    the archive filename) it must agree with the title, or this raises."""
    text = body.decode("utf-8", "replace")
    lines = [ln for ln in text.splitlines() if ln.strip(" ,\r")]
    if len(lines) < 2:
        raise FoParseError("participant-OI file has no header")

    m = _TITLE_DATE.search(lines[0])
    if not m:
        raise FoParseError(f"no 'as on <date>' in the title line: {lines[0][:80]!r}")
    title_date = datetime.strptime(m.group(1).replace(",", ""), "%b %d %Y").date()
    if session_date is not None and session_date != title_date:
        raise FoParseError(f"session mismatch: title says {title_date}, caller says {session_date}")

    reader = csv.reader(io.StringIO("\n".join(lines[1:])))
    header = [h.strip() for h in next(reader)]
    if header[0] != "Client Type" or len(header) != 15:
        raise FoParseError(f"unexpected participant-OI header ({len(header)}): {header[:4]}")
    need = set(PARTICIPANT_OI_SOURCE_NUMERIC)
    if not need <= set(header):
        raise FoParseError(f"header lacks {sorted(need - set(header))}")

    out: list[dict] = []
    for r in reader:
        if not r or not any(c.strip() for c in r):
            continue
        rec = dict(zip(header, [c.strip() for c in r]))
        cat = rec["Client Type"]
        if cat not in CATEGORIES:
            raise FoParseError(f"unknown category {cat!r}; expected one of {sorted(CATEGORIES)}")
        row: dict = {"session_date": title_date, "category": cat}
        for col, src in PARTICIPANT_OI_FROM_SOURCE.items():
            row[col] = _float(rec[src], f"{cat} {src}")
        row["index_fut_net"] = row["index_fut_long"] - row["index_fut_short"]
        row["stock_fut_net"] = row["stock_fut_long"] - row["stock_fut_short"]
        for src in PARTICIPANT_OI_SIDECAR:
            row[src] = _float(rec[src], f"{cat} {src}")
        out.append(row)

    seen = [r["category"] for r in out]
    if sorted(seen) != sorted(CATEGORIES):
        raise FoParseError(f"expected exactly {sorted(CATEGORIES)}, found {seen}")
    cols = list(PARTICIPANT_OI_TABLE_COLUMNS) + list(PARTICIPANT_OI_SIDECAR)
    return pd.DataFrame(out, columns=cols)


def to_participant_oi_rows(df: pd.DataFrame) -> pd.DataFrame:
    """The 14 columns migration 0004 declares, in its order. The sidecar is
    dropped HERE and only here, by name."""
    return df[list(PARTICIPANT_OI_TABLE_COLUMNS)].copy()
