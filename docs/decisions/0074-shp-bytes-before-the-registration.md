# 0074 — Shareholding patterns: the bytes before the registration

**Date:** 2026-09-17
**Decided by:** Owner ("yeah proceed like that"), after being told plainly that
this reverses the project's usual order and why.
**Status:** accepted
**Related:** 0046 (insider: the closeable gap), 0058 (derivatives collected,
deliberately not studied), 0073 (the insider window measured the same day),
Plan 1 §5 (archive raw bytes before parsing).

## The finding that changed the order

The project's rule is register first, look second. It has held for every study
here, and it is why the deals verdict is trusted even though it is DEAD.

This morning the insider endpoint was probed for history and found to be a
**four-month rolling window**: May 2026 answered, April did not, and the months
before April were already gone — nobody had asked. The same hour, the
shareholding-pattern master was probed on five symbols across sizes: every one
held filings back to **2021-09-30**, and the oldest XBRL still resolved with the
named holders inside. The floor is uniform, so it is the endpoint's window, not
listing age — and whether that window is fixed (the XBRL-format SHP began then)
or rolls at five years is **unknown**. If it rolls, 2021-Q3 falls off at the
next quarter-end.

A registration cannot be written for data that is gone. Archiving raw bytes is
not looking at an outcome: nothing is parsed, no holding percentage is read, no
table is written. So the bytes come first, and the registration — which will
have to defend against the obvious confound before anything else — comes after,
with the data secured either way.

## Why this source, honestly

Every event class tested here is bounded by the same number: independent
monthly cohorts. Deals have 249 and a handful of events in each; no source adds
months to the past. SHP is a different shape — ~2,900 symbols reporting FII, DII,
mutual-fund, promoter and public holding every quarter, all at once. It is the
first structure in this project that is not starved on the dimension that kept
killing results.

It is still ~20 quarters. Any registration must state its MDE at 20 periods and
not pretend 40,000 symbol-quarters buy more than they do when the cross-section
moves together. And holding **percentage** rises mechanically when price rises,
so "rising FII holding predicts returns" is one step from "returns predict
returns". The registered quantity has to be active change — net of price, or
entry/exit counts — or the study measures momentum and calls it institutions.

## What was built

`src/archive/shp.py`, on the pattern of `insider.py`: master per symbol (JSON,
Akamai warm-up, same source id `nse_shp_master` the 2026-09-15 proof used),
XBRL per filing (static host, `nse_shp_xbrl`), both sha256-deduped and recorded
with symbol and quarter-end. The universe is the newest archived bhavcopy's EQ
and BE series — the exchange's own list of what traded, not a hand-kept one;
SME and bonds excluded on purpose.

Guards, each with a test observed failing under perturbation:

- an empty master is `EMPTY` per symbol (new listings exist) and FAILS the run
  above 50% (the retired `/api/corporates-pit` answered `[]` for two months);
- every XBRL failing while the master succeeded FAILS the symbol (the
  green-but-empty shape from insider.py's own history);
- a master stored within 80 days is skipped unless `--force`, so the manifest
  is the checkpoint and a killed sweep resumes at the cost of one fetch;
- the XBRL budget stops detail, never the master, so every symbol's index lands
  in one run.

The first sweep started 13:50 IST by hand, sized to end before the 20:30
collector. `com.institutional-research.shp` runs nightly at 01:00 — a window in
which nothing else here touches nseindia — at 5,000 files a night until the
~60,000 backlog clears, after which the run costs seconds until a quarter rolls.
A failure pages through the same `stage_alert` path as the collector, as the
`shp` stage, classified as a dated feed: next night retries, act if it repeats.

Observed on the first sweep, first hour: 975 XBRL stored, 12 × 404 (old
filings whose XML is genuinely gone, one per symbol), and 8 network failures
all on the first symbol swept — a transient at start, re-fetched with `--force`
after the run.

## What would reverse this

- **The floor turning out to be fixed.** Then the bytes were never at risk and
  the usual order would have cost nothing. The collector is still needed for
  the quarterly top-up, so nothing built is wasted; only the urgency was.
- **The registration failing its own power analysis at 20 periods.** Then the
  archive is a record and not a study, which is also what the derivatives
  archive is under 0058. That is an acceptable end.
- **A sweep hitting NSE harder than it tolerates.** One request every two
  seconds is the project's standing rate; if masters start answering 403 in
  bulk, the nightly budget comes down before anything else changes.

## Cost accepted

- **The order of operations, once.** Collection before registration, for bytes
  only, with the reason written here. Not a precedent for looking at outcomes.
- **~60,000 small files** (~25 GB uncompressed, ~4 GB gzipped) in the archive,
  and in every backup that carries `data/raw/archive`. The nightly bundle grows
  accordingly.
- **~33 hours of polite requests** to nseindia spread over ~12 nights, and
  ~2,900 per quarter thereafter.
- **A second calendar-shaped source with no study reading it**, next to
  derivatives. Two archives waiting on registrations is the project being
  honest about what it has not yet asked, not a backlog to clear by asking
  carelessly.

## Amendment 1 — 2026-09-17 evening: the first sweep met the reversal clause

The clause read: *"A sweep hitting NSE harder than it tolerates … the nightly
budget comes down before anything else changes."* It happened on the first
run.

Measured from the manifest, by hour: 516, 910, 1,149 XBRL files stored in the
three hours from 17:30 IST — then the host slowed every response to the
45-second deadline. The run I had sized to end by 17:40 was still running at
20:57, at one file per 85 seconds, with 15 masters failed, and the 20:30
collector's deal fetch — sharing the host — took **11 minutes** instead of
twenty seconds. A separate dead stretch of three and a half hours earlier in
the run has no explanation in the log, which was buffered and lost when the
process was stopped.

The 33 `EMPTY` masters were checked before being believed: they are ETFs
(`ABSL10BANK`, `ABSLLIQUID`, …), which sit in the EQ series and do not file.
Genuine, not a throttled `200 []`.

Changed, each with a test observed failing under perturbation:

- **Wall clock** (`--max-minutes`, 150): a throttled run does not finish
  faster by continuing; it finishes later and collides with the next job.
- **Circuit breaker**: five consecutive network failures (deadline, refused,
  reset — a 404 is a fact about one file and does not count) stop the run,
  record `THROTTLED` as a FAILED run row, and page as the `shp` stage.
- **Nightly budget 5,000 → 1,500** — under an hour at the rate NSE tolerated.
- **`EMPTY` masters fresh for 7 days** — ~100 ETFs were being re-asked every
  run.
- **Buffered progress lines flushed**, so the next stopped run leaves a log.

Not changed: the 2-second rate. Three hours at that rate were tolerated; the
budget and the clock are the levers, and the rate is the last one to touch.
The first sweep landed 2,621 XBRL files across 152 symbols and quarters back
to 2015; the nightly job takes it from there.
