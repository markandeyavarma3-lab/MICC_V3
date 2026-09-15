# 0061 — Studies join prices on security_id, not on the ticker string

**Date:** 2026-09-15
**Decided by:** Owner, on a handover audit's finding (`handover_delta/01_JOIN_CHECK.md`,
`handover_delta2/01_CONTAMINATION.md`, `handover_delta4/02_JOIN_SPEC.md`).
Implemented the same day.
**Status:** accepted
**Related:** 0009 (partition on ISIN, never on symbol — the same principle,
applied to the split three weeks earlier and not to the studies), 0032
(uncovered symbols leave the universe), 0055 (`_returns_sql` is the engine
six modules share).

## Context

`measure.py`, `consensus.py` and `selling.py` attached forward returns to
deals with `JOIN rets r ON r.symbol = UPPER(TRIM(raw.symbol_raw)) AND r.date
= cl.trade_date`, and `measure._returns_sql` computed every window
`PARTITION BY symbol`. None of the three selected
`institutional_deals_clean.security_id`; none imported the identity layer.
The mart had resolved every deal to a security at build time and the studies
threw that away and re-derived identity from a string.

A ticker is not an identity. Measured on the adjusted spine: **331** symbols
were held by more than one security over time; **275** securities traded
under more than one symbol. On a recycled ticker the LEAD window ran one
company's last rows into the next company's first rows (`max_span_days`
catches this only when there is a multi-year gap between them). On a rename
the window broke at the old ticker's last row and the event was silently
dropped while the security kept trading. Among the 5,944 eligible rows,
1,083 (18.22%) carry a ticker with recycling somewhere in its history; the
identity layer's own LOW grade — several securities genuinely held the ticker
*on that date* — covers 62 (1.04%), all inside the 1,083.

The obvious fix — join `deal.security_id` to the `symbol_history` row valid
on `deal.trade_date` — does not work on this data. `symbol_history` comes
from a single reference snapshot (`v1seed:isin_master`): 44.7% of its rows
end on exactly 2019-12-02 and 39.4% start on exactly 2011-07-01. A literal
`valid_from`/`valid_to` join finds no covering window for **2,959 of 5,944**
eligible rows (49.8%) — 1,885 after the snapshot's end date, 1,072 before
the seed's start date. The identity layer already knows this: `RESOLVE_SQL`
scores every candidate by `gap_days` (0 if the window covers the date, else
distance to the nearest edge) and takes the lowest, calling the no-window
case MEDIUM. Half the eligible population is MEDIUM.

## Decision

1. `_returns_sql` assigns every spine row a `security_id` by the identity
   layer's own rule — covering window wins, else nearest, ties to the lowest
   `security_id`, the exact ordering `RESOLVE_SQL` uses — collapses rename
   days to one row per `(security_id, date)`, and computes every window
   `PARTITION BY security_id`. Its output carries `security_id`.
2. The three studies join `r.security_id = cl.security_id AND r.date =
   cl.trade_date`. `institutional_deals_raw.symbol_raw` is not read by any of
   them for identity. Consensus counts convergence per security, not per
   ticker.
3. A deal with `security_id IS NULL` is **excluded with the explicit reason
   `unresolved_identity`**, counted by each module's `UNRESOLVED_SQL` and
   printed by `main()`. No ticker is guessed for it. Counts on 2026-09-15:
   measure 0, selling 158 (already excluded by the symbol flags; now named),
   consensus PERMISSIVE 9,212 (the one population that materially changes —
   from string-matching unresolved buys to not matching them).
4. `tests/test_identity_join.py` pins the rule on a recycled-ticker and a
   rename fixture, with the pre-patch SQL kept in the test as a negative
   fixture. It was watched to fail against unpatched code (1 pass / 5 fail)
   and then pass (6 / 6).

## Why

**Same rule on both sides, or half the data vanishes for a non-reason.** The
spine-side assignment reproduces the stored `security_id` on the trade date
for **5,944 / 5,944** eligible rows and **4,166 / 4,166** selling events,
measured read-only against prod before the patch. That agreement is the whole
argument: the join can be by identity *without* changing what identity the
mart already assigned, and without a stricter window rule that the data
cannot satisfy.

**Rejected: a literal as-of join.** Loses 49.8% of eligible rows to a
snapshot artefact, and would have to be undone the day the identity source
is refreshed.

**Rejected: keep `symbol_raw` as a fallback for unresolved rows.** That is
the old join wearing a new name; 0032 already decided that a deal the
universe cannot place is out, not matched by guessing.

**Rejected: fix the identity source first.** The identity layer is frozen
for this workstream and its rule is correct for the data it has; the defect
was in the studies ignoring it.

**Rejected: also patch confounds / insider_power / delisting / outcomes now.**
They share `_returns_sql` and therefore inherit the security-partitioned
windows and the identified-only benchmark, but their event side still keys on
`symbol_raw`. Out of scope for this record; listed in
`handover_delta4/03_JOIN_DONE.md`.

## What would reverse this

- A refreshed `symbol_history` with real, complete validity windows. Then
  the nearest-window fallback should become a hard as-of join and MEDIUM
  should become an error, not a grade.
- The spine gaining a `security_id` column at build time (a warehouse
  change). Then the spine-side assignment in `_returns_sql` is redundant and
  should be deleted in favour of the stored column.
- Evidence that the spine-side rule and the mart's stored `security_id`
  disagree on some trade date. Today they agree on every row measured; a
  future divergence means the two rules drifted and must be re-unified, not
  papered over.

## Cost accepted

**Every figure quoted from these three modules moves and none has been
re-measured here.** The market benchmark is now the mean over identified
securities (94.68% of spine rows), not every string in the spine; windows
follow securities across renames and stop at recycles. `VERDICT.md` §4.1's
quoted MDEs and `tests/test_measure.py`'s 12-month pin (11.5374% on 4,673
events, decision 0055) are known to be stale and are left stale on purpose:
this record changes how returns are attached, and a re-pin without its own
decision record would be the "quiet re-pin" 0055 refused. **VERDICT.md is
not reopened. The −22.7% / −23.80% sell figure (0044) is not claimed to have
changed.** This is a measurement-integrity fix, and whether the verdict
survives it is a separate measurement with a separate record.

Consensus PERMISSIVE loses 9,212 unresolved buys it used to string-match.
That is a smaller population and a correct one.

No trials. No effect is estimated here; the modules compute dispersion only,
as before.
