# 0057 — The classifier was fine; I broke the report of it

**Date:** 2026-09-11
**Decided by:** Me, executing an outside reviewer's trust-repair workstream. The
reviewer asked for a contamination audit before the PROP_HFT kill was accepted as
fact. The audit found the contamination was in my own reporting, not the data.
**Status:** accepted
**Supersedes:** amendment 2 of
[0056](0056-the-participant-study-cannot-be-run-and-the-machine-does-not-invent-findings.md),
point 2 only.

## 1. The retraction

0056 amendment 2 claimed the PROP_HFT classifier "does almost nothing" — 168 of
239,480 deals, 0.07% — and that Graviton, HRT, Tower and XTX "survive it". **All
of that is false.** Measured by running the classifier
(`python -m src.mart.eligibility`):

| | |
|---|---|
| PROP_HFT participants | **310** |
| their deal rows | **97,249** |
| share of corpus | **41.2%** (docstring predicted ~44%) |

`ineligibility_reason` is a **priority-ordered display field**, and
`src/mart/clean.py` says so in a comment one line above the CASE: *"ONE reason
per row, in priority order."* `same-day round trip` is evaluated above `PROP_HFT
participant`, so the 168 is the residual — PROP_HFT deals that were not *also*
round trips — not the coverage.

**I answered a membership question by counting a display label.** They differ by
whatever a higher-priority rule absorbs: 97,081 rows here. A guard now asserts
that gap exists, in `tests/test_eligibility.py`, which had no tests at all until
today despite removing 41% of the corpus.

## 2. The contamination audit, which is what was actually asked for

Which artefact uses which filter, read from source rather than recalled:

| artefact | PROP_HFT | round-trip | eligible_for_research |
|---|---|---|---|
| exp_001 (study_result 1, 2) | — | — | — (builds its own population) |
| charges 1, 2, 4 (confounds) | — | **yes** | — |
| charges 3, 5 (delisting) | — | via import | — |
| `measure.grid` (power grid) | — | — | **yes** |
| consensus | **yes** | yes | yes |
| selling | **yes** | yes | — |
| outcomes (step 6.3) | — | — | **yes** |

**Does any verdict change if the classifier is replaced by the round-trip flag?**
The classifier removes 168 deals the flag alone would keep. Of those, **10 would
become eligible** — the rest fail the side, size or ADV filters regardless. Ten
against an eligible population of 5,944 is **0.17%**, against a twelve-month MDE
of 11.54% versus a 6% bound.

**No artefact needs re-running. Action for every row of the table: none.**

## 3. The round-trip flag, now load-bearing, validated

The reviewer asked for a 50 + 50 stratified sample. A deterministic recomputation
over the full corpus is strictly better and was cheap:

| | |
|---|---|
| rows checked | 239,480 |
| stored flag agrees with recomputation | **239,480** |
| false positives | **0** |
| false negatives | **0** |

Precision and recall against its own definition are exact. But the *definition*
has a hole: **19 round-trip pairs escape** because the same entity appears under
two spellings on the same symbol and day, so the client-stock-day aggregation
never groups them. 19 against 79,106 round-trip days is 0.024% — small, in the
direction of under-detection, and it is the first measured cost of Plan 1 step
3.6 (participant normalisation) being unbuilt.

## 4. 110 of 124 seed tables are read by no code

The reviewer caught me citing a table's presence in the seed to dismiss a build
request. `index_membership`, `regime_daily` and `sector_regime_daily` are
referenced by **no module**. Rather than fix three tables, `DATA_INVENTORY.md`
now carries a **wired** column for every table, and the honest total is that
**110 of 124 seed tables are referenced nowhere**. Presence is not capability.

**And the scan got it backwards first.** Its own comment names those three
tables as unwired, so the first version matched all three as *wired* — a
detector reading its own explanation of what it detects. Decision 0048 found the
identical shape in `status.py`. The file is now excluded from its own scan and a
test fails if that exclusion is removed.

## What would reverse this

For the classifier: a measured drop in coverage below ~50,000 rows, which the new
test asserts against. For the flag: a name-normalisation layer would close the
19-pair hole and is the only thing that would.

## Cost accepted

No trials. Nothing here estimates an effect; the audit reprices no result and
changes no verdict.
