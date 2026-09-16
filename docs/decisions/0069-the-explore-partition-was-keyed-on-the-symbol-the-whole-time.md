# 0069 — The EXPLORE partition was keyed on the symbol the whole time

**Date:** 2026-09-16
**Decided by:** Me, finishing the `security_id` migration that
[0061](0061-studies-join-prices-on-security-id.md) left half-done across
`confounds`, `delisting` and `insider_power`. The partition finding was not
sought; it fell out of passing the ISIN to a function that had always accepted
one.
**Status:** accepted
**Supersedes:** the EXPLORE population figures in 0051, 0052, 0055 and 0068 §5.
Their verdicts stand; their numbers were measured on the wrong stratum.

## 1. What the migration found

`configs/split.yml`, line 57: **"THE KEY: ISIN, NEVER THE SYMBOL."**
`split.assign(symbol, isin=None)` honours that when it is given the ISIN and
falls back to the ticker when it is not.

`confounds._explore_symbols` — which I wrote on 2026-09-03 and which
`delisting` imported — called `split.assign(s)` with the symbol alone. **Every
name fell to the fallback.** All 967 securities in the sell population carry an
ISIN; none was ever used. The partition every confound, every delisting
treatment and every null calibration ran on was the one the design document
explicitly forbids, for the reason the design document gives: renamed
companies land in one stratum under the old ticker and another under the new.

| EXPLORE keyed on | securities | in both |
|---|---:|---:|
| SYMBOL (as run, 09-03 → 09-16) | 282 | |
| ISIN (as specified) | 272 | **84** |

Only 84 securities are in both. These are, in effect, **two different random
30% samples.** Two external audits and my own re-reads did not catch it,
because nothing looked wrong: `split.assign` returned a valid stratum every time.

## 2. The sell effect on the registered partition

| | 0068 (symbol-keyed) | **0069 (ISIN-keyed)** |
|---|---|---|
| EXPLORE sell events | 1,080 | **1,025** |
| raw 12-month effect | −20.49% | **−9.37%** |
| vol-matched residual | — | −10.95% |
| top100 / top500_ex100 / off500 | −16.56 / −20.24 / −52.74% | **−8.88 / −7.51 / −34.07%** |
| sign across four eras | consistent | **INCONSISTENT — 2006–10 is +4.93%** |
| delisting recovery, rf 0.0 / 0.5 | −25.34 / −23.67% | −10.83 / −9.45% |

**The effect is a third of what was published, and it changes sign in the
earliest era.** 0044 framed the project's live question as "the sell effect is
4× the plausible bound — either 0011's bound is miscalibrated or the result is
confounded." On the registered partition it is 1.6× the bound, sign-unstable,
and still concentrated in the tier nobody can trade. The confound reading stands
and the puzzle that motivated it mostly dissolves.

**The two tradeable tiers are now indistinguishable** — −8.88% on n=445 and
−7.51% on n=335 — and their order flipped. Two tests had pinned a strict
`off500 < top500_ex100 < top100`. That ordering was never the finding; the
finding is that off500 is four times worse than anything you could buy, and
that is what is pinned now. `VERDICT.md`'s claim survives; its footnote did not.

## 3. What else the migration moved, and the accounting

**`delisting` and `confounds` agree again: 1,025.** 0068 §6 recorded them at
1,115 and 1,080. `delisting._classify_sql` was the project's third copy of the
horizon window, partitioned by symbol. It now consumes
`measure.identified_px_ctes` — the `px → ident → sec` chain extracted from
`_returns_sql` so there is exactly one definition of which security a price
row belongs to. The extraction is behaviour-preserving: the 12-month power grid
is bit-identical before and after (n=4,630, MDE 10.8496%).

**Insider filings: 23,616 → 16,327 buys, 11,972 → 9,284 sells.** The seed
carries no ISIN, so filings now resolve through `symbol_history` at the filing
date by the mart's own rule. The drop decomposes:

| stage | promoter buys |
|---|---:|
| filings resolving to a security_id | 23,451 |
| … with an identified price row on the filing date | 19,150 |
| … with a 12-month return inside the span guard | **16,327** |

Identity resolution itself loses ~165. The rest: 2,123 filings fall on
non-session dates (weekends, holidays — a filing on a Saturday currently gets
no return rather than the next session's, which is a design choice worth
revisiting), and the balance are symbol-string matches to price rows that, under
identity resolution, belong to a different security. MDE *improved* despite
fewer events — the dropped matches were noise. **Promoter sell is now 1.13×
short of its bound, the closest any population has ever been.** Still not
powered.

## 4. Two collector fixes from the same session

**Retention executed end-to-end for the first time since 2026-09-01.** The
index-driven prune from 0055 was correct but one `rm` on an iCloud file
returned *Operation not permitted* under launchd, and `set -e` ended the run:
four pruned, twenty-three untouched, index five ahead of disk. `rm` may now
fail per file; what decides the index is whether the file is still there, which
`stat` can answer under TCC when `unlink` cannot. Reconciled interactively:
**27 → 3 generations.** Pinned with `chflags uchg`, watched failing.

**Empty block days are dated — from tonight.** 0066's fix was committed at
10:16 IST; the morning collector ran at 08:30 IST. The 09-16 record is the last
`session=None` one. Verified the branch fires on the real sentinel body.

## What would reverse this

For the partition: nothing — the ISIN key is what split.yml specified from the
start. For the sell effect: a measurement on CONFIRM, which no diagnostic may
touch. For the insider filings: mapping non-session filing dates to the next
session, which would recover ~2,100 events and is a registration decision, not a
code fix.

## Cost accepted

`TRACK_D_DEALS` +12: `confounds` (+8) and `delisting` (+4) re-run on the
registered partition. Per 0035 a re-measurement is a measurement, and these are
the first measurements of the sell effect on the stratum the design specified.
