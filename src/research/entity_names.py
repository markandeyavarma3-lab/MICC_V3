"""entity_names.py — counting-grade normalisation of deal counterparty strings.

NOT Plan 1 STEP 3.6. `participant_aliases` is a persisted, reviewed alias table
with a merge queue and a review status per mapping. This is a pure function with
no state, built for one purpose: make a COUNT of distinct entities trustworthy
enough to publish. 0058 logged the requirement; 0057 measured the cost of its
absence — 19 same-day round-trip pairs escape detection because one entity
appears under two spellings on the same symbol and day.

THE TWO ERRORS ARE NOT SYMMETRIC, AND THAT DECIDES THE DESIGN.

  * Merging two DISTINCT entities pools their trades into one inflated track
    record. That manufactures a finding, and Workstream 3 exists to test whether
    any track record survives — so this error is the one that corrupts the
    answer.
  * Failing to merge two spellings of ONE entity splits its record in two and
    pushes both below the eligibility floor. That hides a finding.

Hiding is recoverable; manufacturing is not. So the rules below are
conservative: strip only what is unambiguously decorative, and never touch a
token that could distinguish two legal entities. `GOLDMAN SACHS INVESTMENTS
MAURITIUS I` and `... MAURITIUS II` must stay apart, as must `ISHARES MSCI INDIA`
and `ISHARES MSCI INDIA SMALL-CAP`.

WHAT IS DELIBERATELY NOT DONE. No fuzzy matching, no edit distance, no token
overlap. Every one of those merges names that merely look alike, and the review
step that would catch a bad merge is exactly the thing step 3.6 provides and
this does not.
"""

from __future__ import annotations

import re

#: Purely decorative corporate suffixes. Each carries no distinguishing
#: information: a firm is the same firm whether it writes LTD or LIMITED.
#: Country and region words are NOT here — `MAURITIUS` and `SINGAPORE` separate
#: real legal entities and removing them would merge them.
SUFFIXES = (
    "PRIVATE", "PVT", "LIMITED", "LTD", "LLP", "LLC", "INC", "PLC",
    "COMPANY", "CO", "CORP", "CORPORATION", "THE",
)

_SUFFIX_RE = re.compile(r"\b(" + "|".join(SUFFIXES) + r")\b")
_PUNCT_RE = re.compile(r"[^A-Z0-9 ]+")
_SPACE_RE = re.compile(r"\s+")


def normalize(raw: str) -> str:
    """Canonical form of a counterparty string, for counting only.

    Upper-cases, removes punctuation, drops decorative corporate suffixes and
    collapses whitespace. Returns the punctuation-stripped original when the
    result would otherwise be empty — a name made only of suffixes must not
    become the empty string, or every such name merges into a single entity.
    """
    s = _PUNCT_RE.sub(" ", (raw or "").upper())
    s = _SPACE_RE.sub(" ", s).strip()
    stripped = _SPACE_RE.sub(" ", _SUFFIX_RE.sub(" ", s)).strip()
    return stripped or s
