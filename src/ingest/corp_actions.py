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
from datetime import datetime
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

#: FORMS THAT CARRY AN INSTRUMENT THAT IS NOT THE ORDINARY EQUITY. A subject
#: mentioning any of these is refused whole, before any ratio is read from it:
#: "Bonus Ncrps 4:1", "Bonus Debentures 1:1", "Sch Of Agmt- Bonus Deb1:1",
#: "Bonus Preference Shares 21:1", "Bonus 1 Dvr : 10 Eq Share", "Rights - 7 Ccps
#: And 7 Warrants:40", "Rights Issue - 1 Ncd ... With 2 Detachable Warrants".
#: Each has a perfectly readable A:B in it and none dilutes the equity line the
#: way that A:B would claim. A partly-paid rights share is refused for the same
#: reason on the other side: its TERP is not the one the ratio and premium give.
_NOT_EQUITY = re.compile(
    r"ncrps|debenture|\bdeb\s*\d|preference|ccps|\bdvr\b|warrant|\bncd\b|"
    r"convertible|partly\s+paid|capital\s+reduction|entitlement", re.I)

_NUM = r"(\d+(?:\.\d+)?)"
_RS = r"(?:(?:rs|re)\.?\s*)?"
#: "Face Value Split (Sub-Division) - From Rs 10/- Per Share To Re 1/- Per
#: Share", "Fv Split Rs.10 To Rs.2", "Sub-Division From Rs 10/- Per Share To
#: Rs 2/- Per Share", "Face Valus Split (Sub-Division) - From Rs 10/- Per To
#: Rs 2/- Per Share" (NSE's own typo), and "Bonus 1:1 / Face Value Split From
#: 10/- To Face Value 2/-" where the split half carries no currency at all.
_SPLIT = re.compile(
    r"(?:face\s+valu[es]\s+split|fv\s+split|sub-division|\bsplit)"
    r"[^\d]*?(?:from\s+)?" + _RS + _NUM +
    r"\s*/?-?(?:\s*(?:per(?:\s+share)?|each))?\s+to\s+(?:face\s+value\s+)?" + _RS + _NUM,
    re.I)
#: The reverse of a split: "Consolidation Of Equity Shares From Re 1 Per Share
#: To Rs 10 Per Share". Face value RISES, share count falls, factor > 1.
_CONSOLIDATION = re.compile(
    r"consolidation[^\d]*?(?:from\s+)?" + _RS + _NUM +
    r"\s*/?-?(?:\s*per(?:\s+share)?)?\s+to\s+" + _RS + _NUM, re.I)
#: Only these words may stand between "bonus" and its ratio. "Bonus Ncrps",
#: "Bonus Debentures", "Bonus Preference Shares" and "Bonus 1 Dvr" all fail
#: here, and the instrument screen above refuses them before this is reached.
_BONUS = re.compile(
    r"\bbonus(?:\s+(?:issue|shares?|equity|of|in\s+the\s+ratio\s+of))*"
    r"\s*[-:]?\s*(\d+)\s*:\s*(\d+)(?![\d.])", re.I)
#: "Rights 3:5 @ Premium Rs 45/-", "Rights At 2:1 At A Premium Of Rs.39.50 Per
#: Share", "Rights Issue 4 : 25 @ Premium Rs 194/-", "Rights 5: 116 At Premium
#: Rs 244", "Rights 7:10 @ Prm Rs 102/-", "Ratio Of The Rights Is 3:2". The
#: negative look-ahead refuses "Rights 1:11.10", whose ratio is not integral
#: and whose meaning is not one this parser will guess.
_RIGHTS = re.compile(
    r"\brights(?:\s+issue)?\s*[-:]?\s*(?:at\s+|eq\s+|is\s+)?(\d+)\s*:\s*(\d+)(?![\d.])",
    re.I)
_PREMIUM = re.compile(
    r"(?:@|at)\s*(?:a\s+)?(?:prem(?:ium)?|prm)\s*(?:of\s+)?" + _RS + _NUM, re.I)
_AT_PAR = re.compile(r"(?:@|at)\s*par\b", re.I)


@dataclass(frozen=True, slots=True)
class Action:
    symbol: str
    isin: str
    date: str            # ex-date, ISO
    action_type: str     # SPLIT | CONSOLIDATION | BONUS | RIGHTS | DEMERGER | UNPARSED
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


Verdict = tuple[str, str, float | None]


def classify_all(subject: str) -> list[Verdict] | None:
    """Every action in the subject, or None if nothing in it is price-affecting.

    ONE SUBJECT CAN CARRY TWO ACTIONS. "Bonus 1:2 And Face Value Split Rs.10/-
    To Rs.5/-" is a bonus AND a split on one ex-date, and the spine multiplies
    every factor it finds for a (symbol, date), so both are emitted as rows and
    neither hides the other. What is NOT done is inference: a subject that
    names a non-equity instrument anywhere is refused whole, because reading
    the equity half of "Rights Eq 1:20 @ Premium Rs.715 And 3 Warrants : 1 Eq"
    and ignoring the warrants would produce a factor that is confidently wrong.
    """
    s = " ".join((subject or "").split())
    if not PRICE_AFFECTING.search(s):
        return None
    if _NOT_EQUITY.search(s):
        return [("UNPARSED", "", None)]

    out: list[Verdict] = []

    if (m := _SPLIT.search(s)):
        old, new = float(m.group(1)), float(m.group(2))
        if old > 0 and new > 0 and new <= old:
            out.append(("SPLIT", f"{m.group(1)}:{m.group(2)}", new / old))
        else:
            return [("UNPARSED", "", None)]
    elif (m := _CONSOLIDATION.search(s)):
        old, new = float(m.group(1)), float(m.group(2))
        if old > 0 and new > old:
            out.append(("CONSOLIDATION", f"{m.group(1)}:{m.group(2)}", new / old))
        else:
            return [("UNPARSED", "", None)]

    if (m := _BONUS.search(s)):
        a, b = int(m.group(1)), int(m.group(2))
        if a > 0 and b > 0:
            out.append(("BONUS", f"{a}:{b}", b / (a + b)))
        else:
            return [("UNPARSED", "", None)]

    if re.search(r"\bdemerger\b", s, re.I):
        # A demerger IS price-affecting and its factor is NOT derivable from the
        # text: it depends on the value assigned to the resulting entity. Found
        # because TRIVENI fell 41.6% on 2026-07-22 with no action on file — the
        # word was simply missing from the screen above, so the one class of
        # event that needs a human was the one class being filtered out.
        out.append(("DEMERGER", "", None))

    if (m := _RIGHTS.search(s)):
        a, b = int(m.group(1)), int(m.group(2))
        if a > 0 and b > 0:
            # factor needs the cum price; see the module docstring. The ratio
            # records the premium when the subject states one, "@0" for an
            # issue at par, and nothing after the ratio when it is silent.
            if (pm := _PREMIUM.search(s)):
                ratio = f"{a}:{b}@{pm.group(1)}"
            elif _AT_PAR.search(s):
                ratio = f"{a}:{b}@0"
            else:
                ratio = f"{a}:{b}"
            out.append(("RIGHTS", ratio, None))
        else:
            return [("UNPARSED", "", None)]

    # Every price-affecting word must be accounted for by something above. A
    # subject that says "split" or "rights" and yielded no such row is one the
    # expressions could not read, and it is surfaced rather than filed under
    # whatever half of it did parse.
    kinds = {k for k, _, _ in out}
    wanted = {"SPLIT": re.search(r"split|sub-division", s, re.I),
              "CONSOLIDATION": re.search(r"consolidat", s, re.I),
              "BONUS": re.search(r"bonus", s, re.I),
              "RIGHTS": re.search(r"rights", s, re.I),
              "DEMERGER": re.search(r"demerger", s, re.I)}
    for kind, hit in wanted.items():
        if hit and kind not in kinds:
            return [("UNPARSED", "", None)]
    return out or [("UNPARSED", "", None)]


def classify(subject: str) -> Verdict | None:
    """The first action in the subject — the single-verdict view `classify_all`
    generalises. A compound subject's remaining rows are only reachable through
    `classify_all`, which is what `parse` uses."""
    all_ = classify_all(subject)
    return None if all_ is None else all_[0]


def archived_files() -> list[Path]:
    return sorted(CORPACT_ARCHIVE.glob("**/*.json.gz"))


def parse() -> list[Action]:
    """Every price-affecting action across every archived window, deduplicated.

    Windows overlap by construction when re-fetched, so the same action appears
    more than once; the key is (symbol, ex-date, subject), which is what makes
    two records the same event rather than two events on one day.
    """
    seen: dict[tuple[str, str, str, str], Action] = {}
    for f in archived_files():
        with gzip.open(f, "rb") as fh:
            records = json.loads(fh.read())
        for r in records:
            subject = (r.get("subject") or "").strip()
            verdicts = classify_all(subject)
            if verdicts is None:
                continue
            ex = _ex_date(r.get("exDate") or "")
            if ex is None:
                # An action with no readable ex-date cannot be applied to a price
                # series at all. Kept as UNPARSED so it is counted, never dropped.
                verdicts = [("UNPARSED", "", None)]
                ex = ""
            for kind, ratio, factor in verdicts:
                # The kind is part of the key: a bonus-and-split subject is two
                # events on one day, and the spine multiplies both factors.
                key = ((r.get("symbol") or "").strip(), ex, subject, kind)
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
