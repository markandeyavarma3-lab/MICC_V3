"""roles.py — what economic role a counterparty is playing. Workstream 3 item 2.

THE STEP THAT STOPS THE STUDY MANUFACTURING AN EDGE.

A cash bulk buy by a derivatives arbitrage desk is one leg of a hedge. The desk
did not form a view on the stock; it sold an option and bought delta. Tiering
forward returns across such trades measures the hedge's mechanical relationship
to the underlying and reports it as skill — and it would look *excellent*
in-sample for exactly that reason.

The same applies, for different reasons, to the other excluded classes:

  * `ODI_ISSUER` — `- ODI` in an NSE counterparty name is an Offshore Derivative
    Instrument, a participatory note. The named entity issued the note. The
    beneficial owner who chose the trade is not disclosed anywhere, so any track
    record built here belongs to a conduit.
  * `INDEX_VEHICLE` — an index tracker rebalances because the index changed.
    Skill is not the mechanism and cannot be.
  * `BANK_EXECUTION` — an offshore vehicle of a global bank crossing a block is
    executing for a client. `CITIGROUP GLOBAL MARKETS MAURITIUS` is a conduit.

CLASSIFY BEFORE MEASURING, AND DECLARE THE EXCLUSIONS FIRST. The order is the
control: choosing which classes to drop after seeing which of them look
profitable is the whole failure this project was built to avoid.

NAME PATTERNS, NOT BEHAVIOUR, AND WHY. A behavioural rule — "two-sided flow
means arbitrage" — would classify using the same return data the study then
tests, and a classifier fitted on the test set is not a control. Names are
independent of outcomes. The cost is recall: `UNKNOWN` is large, and it is
reported rather than swept into the tested class.

THE DEFAULT IS UNKNOWN. Defaulting to LONG_ONLY would put every unclassifiable
conduit into the alpha test, which is the error that runs in the dangerous
direction.
"""

from __future__ import annotations

import re

Role = str

#: Checked in order; the first match wins. ODI is first because a name can carry
#: both a bank and an ODI marker, and the ODI fact dominates — it says the
#: beneficial owner is undisclosed regardless of who issued it.
PATTERNS: tuple[tuple[Role, str], ...] = (
    ("ODI_ISSUER", r"\bODI\b|OFFSHORE DERIVATIVE|PARTICIPATORY NOTE"),
    ("INDEX_VEHICLE",
     r"\bETF\b|ISHARES|POWERSHARES|VANGUARD|LYXOR|\bMSCI\b|\bFTSE\b"
     r"|INDEX FUND|INDEX PORTFOLIO|TRACKER"),
    ("ARBITRAGE",
     r"ARBITRAGE|INTEGRATED CORE STRATEGIES|MILLENNIUM|CITADEL|SEGANTII"
     r"|MARKET NEUTRAL|STAT ARB|QUANTITATIVE STRATEG"),
    ("LONG_ONLY",
     r"MUTUAL FUND|LIFE INSURANCE|\bAMC\b|ASSET MANAGEMENT|PENSION"
     r"|PROVIDENT FUND|UNIT TRUST|\bLIC\b|GENERAL INSURANCE"),
    ("BANK_EXECUTION",
     r"GOLDMAN SACHS|MORGAN STANLEY|CITIGROUP|MERRILL LYNCH|DEUTSCHE"
     r"|CREDIT SUISSE|NOMURA|MACQUARIE|SOCIETE GENERALE|\bUBS\b|BARCLAYS"
     r"|JP ?MORGAN|\bHSBC\b|BNP PARIBAS|ABN AMRO|\bDB \b|COPTHALL"
     r"|BOFA|BANK OF AMERICA|JEFFERIES|CLSA|\bCIMB\b"),
)

_COMPILED = tuple((role, re.compile(rx)) for role, rx in PATTERNS)

#: Declared BEFORE any return is computed. Each is excluded because its cash
#: trades are not expressions of a view on the stock.
EXCLUDED_FROM_ALPHA: frozenset[Role] = frozenset(
    {"ARBITRAGE", "ODI_ISSUER", "INDEX_VEHICLE", "BANK_EXECUTION"})

EXCLUSION_REASON: dict[Role, str] = {
    "ARBITRAGE": (
        "a cash leg against an options book is a delta hedge, not a view; its "
        "forward return is mechanically related to the underlying and would "
        "read as skill in-sample"),
    "ODI_ISSUER": (
        "the disclosed name issued a participatory note; the beneficial owner "
        "who chose the trade is not disclosed anywhere, so the track record "
        "belongs to a conduit rather than to a decision-maker"),
    "INDEX_VEHICLE": (
        "an index tracker trades because the index changed, so skill is not the "
        "mechanism and no amount of persistence would imply it"),
    "BANK_EXECUTION": (
        "an offshore vehicle of a global bank crossing a block is executing for "
        "an undisclosed client, so the name on the disclosure is a conduit and "
        "not the party with the view"),
}

TESTED_CLASSES: frozenset[Role] = frozenset({"LONG_ONLY"})


def classify(name: str) -> Role:
    """Economic role from the NORMALISED name. Default UNKNOWN, never LONG_ONLY."""
    s = (name or "").upper()
    for role, rx in _COMPILED:
        if rx.search(s):
            return role
    return "UNKNOWN"
