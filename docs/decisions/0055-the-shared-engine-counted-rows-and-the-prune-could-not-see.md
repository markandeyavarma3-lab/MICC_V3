# 0055 — The shared engine counted rows, the prune could not see, and 6.3 froze the mart

**Date:** 2026-09-10
**Decided by:** Me. The owner asked for a sweep of every file for bugs. Four of
the five findings below are defects with one correct answer. The fifth — that
every published figure in the project is restated — is a consequence, not a
choice, and 0034's recorded verdict is deliberately NOT edited.
**Status:** accepted
**Supersedes:** the retry mechanism added by
[0053](0053-an-alert-that-cannot-be-cleared-and-a-retention-that-never-ran.md),
whose diagnosis was wrong.

## 1. The horizon bug was in the shared engine, not in one module

[0054](0054-a-twelve-month-label-on-a-nine-year-holding-period.md) found that
`LEAD(close, 252)` counts **rows**, not sessions, and fixed it in `outcomes.py`
alone. `measure._returns_sql` is imported by **six** modules — `measure`,
`consensus`, `selling`, `insider_power`, `confounds`, `delisting` — so every
power verdict and every effect estimate this project has published came through
the unfixed copy.

The guard now lives in `measure.max_span_days` and has exactly one definition;
`outcomes.py` and `delisting.py` import it rather than restating it. `delisting.py`
had quietly become the worst case: its market leg came from the corrected engine
while its own classifier still used raw row counts, so the event population and
the benchmark it was measured against disagreed about which events exist.

**Every headline figure moves. No verdict changes.**

| figure | before | after |
|---|---|---|
| 12-month MDE (power grid) | 13.2701% | **11.5374%** |
| 12-month verdict | 2.21x short | **1.92x short** |
| EXPLORE sell effect | −30.30% (n=1,145) | **−22.68% (n=1,115)** |
| liquidity: top100 | −25.43% | **−17.09%** |
| liquidity: off500 | −60.32% | **−54.66%** |
| promoter buy 12m | n=24,835, MDE 9.07% | n=24,169, MDE **8.06%** |
| promoter sell 12m | n=12,829, MDE 7.53% | n=12,231, MDE **7.81%** |

The sell effect moved 7.6pp, not the 0.71pp I estimated in 0054. That estimate
removed suspensions from the *event population* only; the market leg is built
from the same engine, so both sides of the demeaning moved. **I quoted the
smaller number before measuring the thing it described.**

Promoter sell is the only figure that got **worse** (1.25x → 1.30x short), and
it was the closest to its bound. Reporting only the improvements would have been
a selective read of a change I made.

`0034`'s recorded 5.5572% is not edited. It records what was decided and on what
basis, and the conclusion — nothing is registrable — is unchanged.

## 2. Populating step 6.3 froze the clean mart for five days

`deal_forward_outcomes` carries a foreign key to `institutional_deals_clean`.
`clean.py` rebuilds by `DELETE FROM institutional_deals_clean`, which succeeded
while that table was empty. The moment 6.3 filled it on 2026-09-05, **every
scheduled mart rebuild failed**:

```
_duckdb.ConstraintException: Violates foreign key constraint because
key "deal_id: 6" is still referenced by a foreign key in a different table
```

The collector reported `mart=1` three times a day for five days, exited non-zero
every time, and **767 collected deals never reached the mart**. The alerting
added in 0053 covers *collection* staleness, not *derived-table* staleness, so
health stayed green while the pipeline behind it was stopped.

`clean.py` now deletes the derived outcomes in FK order and reports the count,
because an outcome is a forward return computed from a mart row and a rebuilt
mart makes every one stale by construction. Emptying a 52,000-row table silently
would be worse than the breakage it replaces.

## 3. The prune could not see the directory, and 0053 guessed wrong

0053 diagnosed the empty listing as an iCloud FileProvider lag and added a
ten-attempt retry. **That was wrong.** Measured 2026-09-10 — same script, same
path, same minute:

| context | glob | `ls` entries | stat a known path |
|---|---|---|---|
| interactive | 26 | 78 | OK |
| **launchd** | **0** | **1** | **OK** |

`~/Library/Mobile Documents` is TCC-protected on macOS. A launchd job without
Full Disk Access may stat a path it already knows but **may not enumerate the
directory**, and the denial is silent — `readdir` returns empty rather than an
error. That is why `mv` into the destination and `du` on explicit paths both
succeed on the lines either side of a prune that believes the directory is empty.

Retrying a permission denial produces more denials. The backup went from 11
generations to **26 (2.5 GB)** while the log reported the fix was in.

Retention is now driven by a local index under `logs/`, on ordinary disk, and
deletes by explicit path only. Where enumeration *does* work the index is
reconciled against reality first, so a stale index heals rather than pruning the
wrong set. Verified against `chmod 300` — write and traverse permitted, listing
denied, which is the faithful reproduction of what launchd sees. `chmod 100` is
not: it also denies unlink, and produced a false failure on the first attempt.

## 4. Four more instances of the NULL-count trap, in the file that documented it

`confounds.py` reported `COUNT(*)` beside `avg(ab)` in the size, momentum,
liquidity and time-concentration confounds — the exact defect its own baseline
comment describes, four lines further down the same file. Every published tier n
was the row count while every published effect was the non-null count; the
liquidity tiers read 514/432/129 against the true 464/396/87.

Also fixed: `_survivorship` asserted "recovery factor is NOT applied — step 6.4
unbuilt" for two days *after* 6.4 was built, because a status claim hardcoded in
prose cannot notice that it came true.

## 5. Housekeeping found on the way

- **7.1 GB of orphaned DuckDB spill** in `.tmp/`, left by an OOM-killed suite
  run, untracked and **not gitignored** — one `git add -A` from the repository.
- `ruff` had never been run: it is pinned in `pyproject.toml` and was not
  installed, so no lint result had ever appeared in this project's reporting.
  38 findings, 24 auto-fixed, the rest reviewed by hand. Two were real file
  handles left to the garbage collector in the ingest path.
- A test I wrote on 2026-09-05 was **time-fragile** and began failing five days
  later: its fixture's latest session was `_days_ago(2)`, exactly
  `STALE_SESSIONS`, so `alerting` fired on staleness rather than on the
  condition the test names.

## What would reverse this

The span rule would be reversed by evidence that 1.5x-plus-ten-days excludes
legitimate windows; the current split is 634 suspensions against 49,950 horizons.
The prune's index would become unnecessary if Full Disk Access were granted to
the launchd job, which is the owner's call and the only fix that would let the
directory be read directly — the index does not need it.

## Cost accepted

`TRACK_D_DEALS` 191 → 203. `confounds` (+8) and `delisting` (+4) were re-run
because their published numbers came from a defective engine; per 0035 a
re-measurement is a measurement. No other module charges.
