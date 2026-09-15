# 0062 — The F&O parse exists; the land does not

**Date:** 2026-09-15
**Decided by:** Owner. The deals verdict has landed (exp_002, VERDICT DEAD),
which is the condition 0058 named for lifting its boundary. Built the same
afternoon, before the 20:30 collector slot, and deliberately not wired into it.
**Status:** accepted
**Supersedes:** the "collection only" boundary of 0058, **for code and
fixtures only**. 0058's prod-side boundary — nothing parses these bytes into
the warehouse, no study reads them — stands.
**Related:** 0058 (the feeds and their 34/15-column schemas, flagged not
mapped), 0027 (the seed carries `participant_oi`), migration 0004.

## Context

0058 resumed collecting `nse_fo_bhavcopy` (UDiFF, 34 columns) and
`nse_participant_oi` (15 columns) and refused to parse them: *"UDiFF names
none of these the same way. Resuming the spine needs an explicit column
mapping, and inventing one here would be the parsing this workstream was
told not to do."* Since then `fno_spine` has ended at 2026-08-14 while the
archive is current to 2026-09-10, and `docs/HEALTH.md` has correctly nagged
`fno_spine 28d STALE` every run — a nag 0058 said should persist until a
parse step exists.

The map was read, not invented (`handover_delta4/06_FNO_MAP.md`): the real
34-column header and a stock future, index future, stock option and index
option row from the 2026-09-10 file; the real 15-column participant header
with its title line and trailing-space column names; the `fno_spine` parquet
schema and the conventions on its rows. Three things the data said that a
guess would have got wrong:

- **Futures carry `strike = 0.0` and `option_typ = 'XX'`**, not NULL as the
  comment in `spine.py` claims — on every one of 17,890 legacy futures rows
  since 2026-07-01. A stretch dated 2026-06-17..07-07 (583,741 rows, from a
  V1 increment) already carries raw UDiFF codes `IDF/STF/IDO/STO` with NULL
  futures fields: a defect in the spine, not a convention.
- **`TtlTradgVol` is contracts and `TtlTrfVal` is rupees**, so `val_inlakh =
  TtlTrfVal / 1e5`. Verified: RELIANCE 26SEP future, 18,697 contracts × lot
  500 × ~₹1,278 ≈ ₹11.94 bn = `TtlTrfVal`. `open_int` is shares on both
  sides. The participant file is in contracts (its title says so).
- **The participant `TOTAL` row is not exactly the sum of its parts.** On
  2026-09-10, `Option Index Call Long` is +1 and `Total Long Contracts` is
  −1 against the four categories; NSE forces TOTAL long == TOTAL short per
  instrument and the parts do not quite. A parser that recomputed TOTAL would
  disagree with the published figure by one contract.

## Decision

`src/ingest/fo_bhavcopy.py` exists, with three public functions:
`parse_udiff_bytes(body) -> DataFrame` (zip or csv, all 34 columns, strings),
`to_legacy_spine(df) -> DataFrame` (the 15-column `fno_spine` shape, legacy
instrument codes, futures at `0.0`/`'XX'`, rupees to lakh, zero silent
drops), and `parse_participant_oi_bytes(body, session_date=None) ->
DataFrame` (five rows, mapped by column **name**, `TOTAL` kept verbatim,
session date from the title line and checked against the caller's).
`to_participant_oi_rows` selects migration 0004's 14 columns; the four source
columns with no table home are named in `PARTICIPANT_OI_SIDECAR`, as the 17
UDiFF columns with no spine home are named in `SIDECAR_COLUMNS`.

**No function in the module takes an env, opens DuckDB, or imports
`src.common.paths`.** `write_legacy(df, path)` exists for tests and refuses
any path under the repository's `data/` or `db/`. A test parses the module's
AST to hold that line.

`tests/test_fo_parse.py` (16 tests) was watched to fail on `ImportError`
before the module existed and passes with it; `tests/test_derivatives.py`
(10) is unchanged and green. Fixtures are a 20-row slice of the 2026-09-10
bhavcopy across all four instrument types and the 975-byte participant file.

**Not done, on purpose:** no call from `collect_daily.sh`; no write to
`data/prod/warehouse/fno_spine` or to `participant_oi`; no
`spine.build(FNO)` re-run; no study reads either frame. The `fno_spine
STALE` nag continues, and should, until a land decision exists.

## Why

**Why now.** 0058's own reversal condition was the deals verdict landing.
It has. The parse is the smallest piece that unblocks the feed and the one
whose correctness can be proven on fixtures without touching prod.

**Why not land today.** Landing is a write to the warehouse three hours
before a scheduled collector run, into a spine that already has a known
defective stretch. The parser's output convention (legacy codes, `0.0`/`'XX'`
futures) is the right one; whether to also repair the 2026-06-17..07-07
stretch, and whether `to_legacy_spine` output goes through `SEED_INCREMENTS`
or a new increment path, are `spine.build` questions with their own blast
radius. Separate record.

**Why read every column and name the discards.** Two of the seventeen
unmapped UDiFF fields — `UndrlygPric` (spot at close) and `NewBrdLotQty` (lot
size, the shares↔contracts conversion) — are things a derivatives study will
want. Dropping them silently would repeat the "109 of 119 seed tables read by
no code" pattern one layer down. They are dropped explicitly, by name, in one
place.

**Why `TOTAL` is verbatim.** Migration 0004 keeps it as a fifth category so
a careless `GROUP BY` double-counts visibly. Re-deriving it would silently
"fix" NSE's ±1 and make the warehouse disagree with the published file.

## What would reverse this

- A land decision. When it comes, `write_legacy` should be deleted, not
  extended — the land step belongs in `src/warehouse/spine.py`'s increment
  path, not in a parser.
- NSE changing the UDiFF header or the participant title format. Both parsers
  raise on the header rather than guessing, so the change surfaces as a
  failed stage, not a silently empty spine.
- A migration adding the four sidecar participant columns or the two useful
  UDiFF fields to the tables. Then the sidecar tuples shrink and the tests
  that pin them change with the migration.

## Cost accepted

`fno_spine` stays stale and `HEALTH.md` keeps saying so. That is the honest
state: the bytes are archived and parseable, and nothing has yet decided how
they enter the warehouse.

No trials. Parsing bytes estimates nothing.
