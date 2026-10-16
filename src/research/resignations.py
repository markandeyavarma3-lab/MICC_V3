"""resignations.py — resignation events, classified from the filing text.

WHY TEXT, NOT NSE'S CATEGORY (measured 2026-10-16,
docs/plan/EXP007_RESIGNATIONS_AND_INDUSTRY_PLAN.md). NSE's "Resignation"
category holds about one filing a week in 2014 and 2016 and 17–24 a week from
2019; earlier resignations sit under "Change in Director(s)", "Updates" and
others, and from 2023 NSE added role categories. A rule keyed on the category
would measure NSE's taxonomy changing. The filing text is regular across all
of it: "... Resignation of <name> as <role> ...".

THE RULE, IN ORDER (first match wins), applied to category + text:

  not a resignation   no resign/resignation/resigned word, or the word is in
                      a business sense ("resignation-cum-disinvestment")
  AUDITOR             the statutory auditor (not internal, secretarial, cost
                      or tax auditors — those are OTHER_OFFICER)
  INDEPENDENT_DIRECTOR
  CEO_MD              chief executive, managing director, whole-time director
  CFO                 chief financial officer
  ROUTINE             company secretary, compliance officer
  OTHER_DIRECTOR      any other director (non-executive, nominee, additional)
  OTHER_OFFICER       any other named role (CIO, COO, CSO, auditors of other kinds)
  UNKNOWN             a resignation whose role cannot be read ("Resignation of
                      Director/KMP/SMP") — excluded from every population,
                      never guessed

A filing naming two roles takes the first in this order, so an independent
director and a company secretary resigning together is INDEPENDENT_DIRECTOR.

GOVERNANCE = AUDITOR | INDEPENDENT_DIRECTOR | CEO_MD | CFO: the roles the
literature ties to information (plan §1.2). ROUTINE and the rest carry no such
story and are excluded by definition, before any return is read.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

RESIGN = re.compile(r"\bresign(?:ation|ed|s|ing)?\b", re.I)
NOT_A_RESIGNATION = re.compile(r"resignation[- ]cum[- ]|\bLLPs?\b.*resign|resign.*\bLLPs?\b", re.I)

#: (role, pattern), first match wins.
ROLES: tuple[tuple[str, re.Pattern], ...] = (
    ("AUDITOR", re.compile(r"(?<!internal )(?<!secretarial )(?<!cost )(?<!tax )statutory\s+auditor|"
                           r"resignation of statutory audit|"
                           r"(?<!internal )(?<!secretarial )(?<!cost )(?<!tax )\bauditors?\b(?! of (?:the )?subsidiar)",
                           re.I)),
    # 'Indepedent Directors' (sic, Uniply 2016): the typo and the plural are real.
    ("INDEPENDENT_DIRECTOR", re.compile(r"\bindep\w*\s+directors?\b", re.I)),
    ("CEO_MD", re.compile(r"chief\s+executive|\bC\.?E\.?O\b|managing\s+director|\bM\.?D\.?\b(?!\s*&)|"
                          r"whole[- ]?time\s+director|(?<!non- )(?<!non-)(?<!non )executive\s+director|\bWTD\b", re.I)),
    ("CFO", re.compile(r"chief\s+financ\w*\s+officer|\bC\.?F\.?O\b", re.I)),
    ("ROUTINE", re.compile(r"company\s+secretary|compliance\s+officer|\bC\.?S\.?\b(?=\s*(?:&|and|,|$))", re.I)),
    ("OTHER_DIRECTOR", re.compile(r"\bdirector\b(?!\s*/\s*KMP)", re.I)),
    ("OTHER_OFFICER", re.compile(r"\bchief\s+\w+\s+officer|\bC[IOST]O\b|\bofficer\b|internal\s+auditor|"
                                 r"secretarial\s+auditor|cost\s+auditor|\bhead\b|\bpresident\b", re.I)),
)
GOVERNANCE = frozenset({"AUDITOR", "INDEPENDENT_DIRECTOR", "CEO_MD", "CFO"})


#: Words read around each 'resign' mention. A multi-item filing ('Outcome of
#: Board Meeting': results approved, auditors' limited review, a director
#: resigned) names roles that did NOT resign; the audit of 2026-10-16 found
#: results filings classed AUDITOR and re-designations classed CFO when the
#: whole text was searched.
BEFORE, AFTER = 90, 160
SUBSIDIARY = re.compile(r"subsidiar", re.I)


def _near(text: str) -> str:
    return " … ".join(text[max(0, m.start() - BEFORE): m.end() + AFTER] for m in RESIGN.finditer(text))


def classify(category: str | None, text: str | None) -> str | None:
    """The role a filing reports resigning, or None if it is not a resignation.
    The role is read from the category and from the words around each mention
    of resigning, never from the whole filing."""
    cat, txt = category or "", " ".join((text or "").split())
    if not RESIGN.search(f"{cat} {txt}") or NOT_A_RESIGNATION.search(f"{cat} {txt}"):
        return None
    body = f"{cat if RESIGN.search(cat) else ''} | {_near(txt)}"
    for role, rx in ROLES:
        m = rx.search(body)
        if m:
            # An auditor of a subsidiary is not the company's auditor.
            if role == "AUDITOR" and SUBSIDIARY.search(body[m.start(): m.end() + 80]):
                return "OTHER_OFFICER"
            return role
    return "UNKNOWN"


@dataclass(frozen=True, order=True)
class Event:
    date: str          # YYYY-MM-DD, the filing's date
    isin: str
    role: str


def events(rows: list[dict]) -> list[Event]:
    """Every resignation filing, one per (company, day, role); the strongest
    role of a day wins when one company files several the same day."""
    order = {r: i for i, (r, _) in enumerate(ROLES)}
    order["UNKNOWN"] = len(order)
    best: dict[tuple[str, str], str] = {}
    for r in rows:
        role = classify(r.get("desc"), r.get("attchmntText"))
        isin, d = r.get("sm_isin"), (r.get("sort_date") or "")[:10]
        if not role or not isin or len(d) != 10:
            continue
        k = (d, isin)
        if k not in best or order[role] < order[best[k]]:
            best[k] = role
    return sorted(Event(d, i, role) for (d, i), role in best.items())


def first_in_window(evs: list[Event], sessions: list[str], window: int = 21) -> list[Event]:
    """Clusters are one event: a company's governance resignation counts only
    if it had none in the previous `window` sessions (several directors
    leaving together, or a resignation followed by its 'outcome' filing)."""
    idx = {d: i for i, d in enumerate(sessions)}
    def pos(d: str) -> int:
        # a filing on a non-session day belongs to the next session
        import bisect
        return idx.get(d, bisect.bisect_left(sessions, d))
    last: dict[str, int] = {}
    out = []
    for e in sorted(evs, key=lambda e: e.date):
        p = pos(e.date)
        if e.isin in last and p - last[e.isin] < window:
            continue
        last[e.isin] = p
        out.append(e)
    return out


def table(evs: list[Event]) -> dict[str, Counter]:
    """role -> Counter(year)."""
    out: dict[str, Counter] = {}
    for e in evs:
        out.setdefault(e.role, Counter())[e.date[:4]] += 1
    return out
