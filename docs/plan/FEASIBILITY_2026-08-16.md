# Source Feasibility Report — 2026-08-16

**Phase 0.5 spike.** The deliverable the owner's original plan §21 Phase 1 asked
for and that I had wrongly folded away without a gate. Every line below is a
measured HTTP response, not an expectation.

## Verdict

**Forward collection from NSE is solved. BSE and historical backfill are not.**

| Source | Route | Status | Evidence |
|---|---|---|---|
| **NSE bulk, forward** | `nsearchives.nseindia.com/content/equities/bulk.csv` | ✅ **CONFIRMED** | 200 · 18,888 B · 199 real rows for 14-AUG-2026 |
| **NSE block, forward** | `nsearchives.nseindia.com/content/equities/block.csv` | ✅ **CONFIRMED** | 200 · 111 B · `NO RECORDS` (legitimately empty day) |
| **NSE FII/DII, forward** | `nseindia.com/api/fiidiiTradeReact` | ✅ **CONFIRMED** | 200 |
| NSE bulk/block, historical | `nseindia.com/api/historical/bulk-deals` | ❌ UNPROVEN | 503 with and without session cookie + referer |
| NSE bulk/block, historical | dated static paths (3 variants tried) | ❌ UNPROVEN | 404 |
| BSE bulk | `api.bseindia.com/BseIndiaAPI/api/BulkDeal/w` | ❌ UNPROVEN | 301 → `error_Bse.html`, even with `Origin` + `Referer` |
| BSE block | 3 alternate paths tried | ❌ UNPROVEN | 301 |

## What the working route actually returns

```
Date,Symbol,Security Name,Client Name,Buy/Sell,Quantity Traded,Trade Price / Wght. Avg. Price,Remarks
14-AUG-2026,AGIIL,Agi Infra Limited,ARIHANT CAPITAL MARKETS LIMITED,BUY,841254,302.04,-
14-AUG-2026,APEX,Apex Frozen Foods Limited,JUNOMONETA FINSOL PRIVATE LIMITED,BUY,180160,429.50,-
...
14-AUG-2026,ZEEL,Zee Entertain. Enterp.Ltd,QE SECURITIES LLP,SELL,5092545,102.04,-
```

Schema matches `v1seed.bulk_deals` column-for-column, so the existing 223,450
rows and new rows land in one table without a mapping layer.

`sha256(bulk.csv) = d5ece411db8b0c53a63a2512af873535c6b62c33b06dc806a822014558c50c32`

Two details that matter for the archive design:

1. **An empty day is distinguishable from a failure.** `block.csv` returns
   `NO RECORDS` rather than an error or a zero-byte body. That distinction is what
   lets `ingestion_status` be honest instead of guessing, and its absence is how
   the predecessor lost a Friday without noticing.
2. **`QE SECURITIES LLP` and `JUNOMONETA FINSOL` are in the first day of live
   data** — both identified in the audit as ~100% same-day round-trippers. The
   behavioural PROP_HFT classifier will be filtering from day one, on live data,
   exactly as designed.

## The consequence nobody flagged before now

**The working route is a rolling current-day snapshot, not an archive.** It serves
today's file only. Combined with the historical API returning 503, that means:

> **Every trading day not collected is permanently lost.**

The gap from **2026-07-09 to 2026-08-13** — roughly 26 trading sessions between
the V1 export's last day and today — is very likely **unrecoverable** unless the
historical route is cracked. Owner decision Q8 was "backfill it"; that may no
longer be possible, and I should have established this before accepting the
instruction.

This turns the collector from a Phase 2 item into the **most time-sensitive piece
of work in the project.** Every day it is not running costs a day of data that
cannot be bought back. It vindicates owner decision Q13 (automate from day one)
for a reason neither of us had at the time.

## Effect on the plan

| Was | Now |
|---|---|
| All institutional sources UNPROVEN | NSE forward CONFIRMED; BSE and backfill still UNPROVEN |
| Collector was Phase 2, week 4–6 | Collector is **urgent** — pull forward ahead of the identity layer |
| "Backfill the 5-week gap" (Q8) | Probably impossible; treat 2026-07-09→08-13 as a permanent hole and record it as such |
| Feasibility spike capped at 8 h | ~1 h spent. **7 h remain** for BSE and the historical route |

The 223,450 historical bulk and 12,430 block deals are unaffected. Every study in
Plan 2 runs on them regardless of how BSE resolves.

## Remaining spike budget: BSE and backfill

Not yet tried, in order of expected yield:

1. BSE's own page (`bseindia.com/markets/equities/DealNew.aspx`) to capture the
   exact XHR the browser issues — the 301 suggests my path or query shape is
   wrong rather than the endpoint being closed
2. BSE static archive under `bseindia.com/download/`, which is how BSE serves
   bhavcopy and is the analogue of the NSE route that just worked
3. NSE `/api/historical/*` with a full `sec-fetch-*` / `x-requested-with` header
   set — the FII/DII endpoint on the same host answers, so the 503 is likely
   header-shaped, not a block
4. If historical stays closed: accept the hole, document it, and note that
   forward collection from 2026-08-17 onward makes it a one-off scar rather than
   an ongoing loss

## Standing correction to Plan 3 §4.2

I recorded institutional collection under "Need to build — no blockers" having
never sent a request. Two of four sources were in fact blocked, one of them still
is, and the most consequential fact — that unco llected days are gone forever — was
invisible until the routes were actually probed. The claim should have read
UNPROVEN until measured.
