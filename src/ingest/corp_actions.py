"""corp_actions.py — archived NSE corporate actions become a typed, factored table.

WHAT A PRICE ADJUSTMENT FACTOR IS HERE. For an action with ex-date D, every
price strictly BEFORE D is multiplied by `factor` to be comparable with prices
from D onward, and volume is divided by it. A 1:2 split has factor 0.5; the
history halves and a -50% artefact disappears.

    SPLIT   face value Rs A -> Rs B            factor = B / A
    BONUS   A new shares for every B held      factor = B / (A + B)
    RIGHTS  A new for every B, at price P      factor = TERP / cum_price,
            where TERP = (B*cum + A*P) / (A + B)

RIGHTS IS THE ONE THAT NEEDS A PRICE, AND SO IT IS NOT COMPUTED HERE. Its factor
depends on the cum-price on the day before the ex-date, which lives in the spine,
not in this file. Emitting a placeholder would be worse than emitting nothing, so
RIGHTS rows carry `factor = NULL` and the consumer must resolve them or refuse.

WHY THE PARSER IS DELIBERATELY NARROW.

The subject line is free text and two forms in a single 90-day sample are traps:

    "Scheme Of Arrangement - Bonus Ncrps 4:1"
    "Rights - 7 Ccps And 7 Warrants:40"

NCRPS are non-convertible redeemable *preference* shares and CCPS are compulsorily
convertible preference shares. Neither is a bonus or rights issue of ORDINARY
shares, and neither dilutes the equity the way the regex would claim if it simply
hunted for "Bonus" and a colon. Applying a 1/5 factor to a company because it
issued preference shares would manufacture a -80% return out of nothing.

So this matches only unambiguous, fully-specified forms, and anything that looks
price-affecting but does not match is emitted as UNPARSED with its text intact.
UNKNOWN beats inference (standing rule 9), and a row a human must look at is
strictly better than a number nobody can defend.
"""

from __future__ import annotations

import gzip
import json
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.common.paths import ARCHIVE, COLLECTED  # noqa: E402
from src.governance import provenance as prov  # noqa: E402

CORPACT_ARCHIVE = ARCHIVE / "CORPACT" / "NSE"
OUT = COLLECTED / "corporate_actions" / "corporate_actions.parquet"
PRODUCED_BY = "src/ingest/corp_actions.py"

#: Anything matching this is price-affecting and MUST be classified or reported.
#: Deliberately broader than the patterns below, so a form we cannot read is
#: surfaced rather than filtered out by the same expression that failed to parse
#: it. A screen that only sees what it can already handle reports nothing wrong.
PRICE_AFFECTING = re.compile(
    r"split|bonus|rights|consolidat|sub-division|demerger", re.I)

_SPLIT = re.compile(
    r"face\s+value\s+split.*?from\s+(?:rs|re)\.?\s*([\d.]+).*?to\s+(?:rs|re)\.?\s*([\d.]+)",
    re.I | re.S)
_BONUS = re.compile(r"^bonus\s+(\d+)\s*:\s*(\d+)$", re.I)
#: The currency prefix is OPTIONAL. "Rights 1:9 @ Premium 91" (RELTD, ex
#: 2026-06-08) is a perfectly ordinary rights issue that a mandatory `Rs`
#: rejected — a parser that is strict about punctuation is not being careful,
#: it is being wrong in a way that looks careful.
_RIGHTS = re.compile(
    r"^rights\s+(\d+)\s*:\s*(\d+)\s*@\s*premium\s+(?:(?:rs|re)\.?\s*)?([\d.]+)", re.I)


@dataclass(frozen=True, slots=True)
class Action:
    symbol: str
    isin: str
    date: str            # ex-date, ISO
    action_type: str     # SPLIT | BONUS | RIGHTS | UNPARSED
    ratio: str
    factor: float | None  # NULL for RIGHTS and UNPARSED
    subject: str


def _ex_date(raw: str) -> str | None:
    for fmt in ("%d-%b-%Y", "%d-%B-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw.strip(), fmt).date().isoformat()
        except (ValueError, AttributeError):
            continue
    return None


def classify(subject: str) -> tuple[str, str, float | None] | None:
    """(action_type, ratio, factor), or None if not price-affecting at all."""
    s = " ".join((subject or "").split())
    if not PRICE_AFFECTING.search(s):
        return None

    if (m := _SPLIT.search(s)):
        old, new = float(m.group(1)), float(m.group(2))
        if old > 0 and new > 0 and new <= old:
            return "SPLIT", f"{m.group(1)}:{m.group(2)}", new / old
        return "UNPARSED", "", None

    if (m := _BONUS.match(s)):
        a, b = int(m.group(1)), int(m.group(2))
        if a > 0 and b > 0:
            return "BONUS", f"{a}:{b}", b / (a + b)
        return "UNPARSED", "", None

    if re.match(r"^demerger\b", s, re.I) or re.search(r"\bdemerger\b", s, re.I):
        # A demerger IS price-affecting and its factor is NOT derivable from the
        # text: it depends on the value assigned to the resulting entity. Found
        # because TRIVENI fell 41.6% on 2026-07-22 with no action on file — the
        # word was simply missing from the screen above, so the one class of
        # event that needs a human was the one class being filtered out.
        return "DEMERGER", "", None

    if (m := _RIGHTS.match(s)):
        a, b = int(m.group(1)), int(m.group(2))
        if a > 0 and b > 0:
            # factor needs the cum price; see the module docstring.
            return "RIGHTS", f"{a}:{b}@{m.group(3)}", None
        return "UNPARSED", "", None

    return "UNPARSED", "", None


def archived_files() -> list[Path]:
    return sorted(CORPACT_ARCHIVE.glob("**/*.json.gz"))


def parse() -> list[Action]:
    """Every price-affecting action across every archived window, deduplicated.

    Windows overlap by construction when re-fetched, so the same action appears
    more than once; the key is (symbol, ex-date, subject), which is what makes
    two records the same event rather than two events on one day.
    """
    seen: dict[tuple[str, str, str], Action] = {}
    for f in archived_files():
        for r in json.loads(gzip.open(f, "rb").read()):
            subject = (r.get("subject") or "").strip()
            verdict = classify(subject)
            if verdict is None:
                continue
            ex = _ex_date(r.get("exDate") or "")
            if ex is None:
                # An action with no readable ex-date cannot be applied to a price
                # series at all. Kept as UNPARSED so it is counted, never dropped.
                verdict = ("UNPARSED", "", None)
                ex = ""
            kind, ratio, factor = verdict
            key = ((r.get("symbol") or "").strip(), ex, subject)
            seen[key] = Action(key[0], (r.get("isin") or "").strip(), ex,
                               kind, ratio, factor, subject)
    return sorted(seen.values(), key=lambda a: (a.date, a.symbol))


def write(actions: list[Action]) -> Path:
    import duckdb

    OUT.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    try:
        con.execute(
            "CREATE TABLE ca (symbol VARCHAR, isin VARCHAR, date VARCHAR,"
            " action_type VARCHAR, ratio VARCHAR, factor DOUBLE, subject VARCHAR)")
        con.executemany("INSERT INTO ca VALUES (?,?,?,?,?,?,?)",
                        [(a.symbol, a.isin, a.date, a.action_type, a.ratio,
                          a.factor, a.subject) for a in actions])
        tmp = OUT.with_suffix(".parquet.partial")
        con.execute(f"COPY (SELECT * FROM ca ORDER BY date, symbol) TO '{tmp}' (FORMAT PARQUET)")
        tmp.replace(OUT)
    finally:
        con.close()
    return OUT


def register(env: str | None = None) -> str:
    return prov.register_dataset(
        OUT.parent, artefact_type="SOURCE",
        logical_name="collected:corporate_actions",
        produced_by=PRODUCED_BY, pattern="**/*.parquet",
        params={"source": "NSE /api/corporates-corporateActions",
                "note": "RIGHTS factors are NULL by design; they need a cum price"},
        env=env,
    )


def main() -> int:
    actions = parse()
    if not actions:
        print("CORPACT: no price-affecting actions in the archive")
        return 0

    by_kind: dict[str, int] = {}
    for a in actions:
        by_kind[a.action_type] = by_kind.get(a.action_type, 0) + 1

    write(actions)
    digest = register()
    print(f"  {len(actions)} price-affecting action(s) "
          f"{min(a.date for a in actions if a.date)} .. {max(a.date for a in actions)}")
    for k, n in sorted(by_kind.items()):
        print(f"    {k:<10} {n}")
    unparsed = [a for a in actions if a.action_type == "UNPARSED"]
    if unparsed:
        print("\n  NEEDS A HUMAN — looked price-affecting, could not be read:")
        for a in unparsed:
            print(f"    {a.symbol:<12} {a.date:<12} {a.subject[:70]}")
    print(f"\nCORPACT: {OUT}")
    print(f"  registered collected:corporate_actions as {digest[:16]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
