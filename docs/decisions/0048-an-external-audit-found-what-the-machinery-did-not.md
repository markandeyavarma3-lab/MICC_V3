# 0048 — An external audit found three defects this project's own machinery was built to catch

**Date:** 2026-09-02
**Decided by:** Owner commissioned a deep external audit; the findings are theirs,
the defects are mine
**Status:** ACTIVE

## Context

`AUDIT_README.md` is an independent technical audit of the whole repository at
commit `f79ac5d`. It reported three dominant findings. **All three reproduce.**
All three are mine, and all three are instances of the exact error this
repository's thesis names — *"the artefact exists" is not "the step works"*.

## 1. The deal pipeline had been silently broken for a day

`python -m src.ingest.land` raised an unhandled `_csv.Error` on the first `PRICE`
file. Reproduced.

`parse.iter_archive` did `base.rglob("*.gz")`, which was correct while the
archive held only deal CSVs. On 2026-09-01 I added three collectors — PRICE
(`.csv.zip.gz`), INSIDER (`.xml.gz`), CORPACT (`.json.gz`) — and the glob
swallowed all of them. `parse_csv` met a gzipped ZIP and died.

**Nothing noticed**, because `land.py` is not in `collect_daily.sh` and nothing
else calls it. The collectors kept reporting success, `health.py` stayed green,
the gate stayed 20/20 — and no collected deal reached the database after
2026-08-28. `parse_archive` already knew the answer: it defaults anything
outside `("BULK","BLOCK","FII_DII")` to report type `UNKNOWN`. The knowledge sat
one function away from where it was needed.

Fixed: `DEAL_REPORT_TYPES` is declared and `iter_archive` walks only those.
Recovered on the same run — 9 files, 692 rows, `institutional_deals_raw` 237,340
→ 238,032 and current through 2026-09-02.

## 2. The honesty instrument was grading itself

Fourteen `status.py` predicates were written as:

```python
built=lambda c: "romano" in "".join(c.src_text.values()).lower()
```

`src_text` includes **`status.py` itself**. The word `romano` appears in `src/`
exactly once — in step 6.8's own description and its own predicate. So the check
matched its own text, and 6.8 "Romano-Wolf stepdown" read **VERIFIED** while
`romano_wolf` existed nowhere in `src/research/`.

The same for `corwin`, `vix`, `cpcv`, `pbo`, `hansen`, `shuffl`, `rotation`,
`near_duplicate`, `pessimistic`, `recovery`, `newey`, `min_obs`, `sqrt`.

I wrote these on 2026-09-01, in the same commit that corrected the status page
for *under-reporting* phases 4–7. Widening the ledger without checking the
predicates replaced one distortion with the opposite one.

`Ctx.mentions()` now excludes `status.py` from its own scan. The ledger moves:

| | before | after |
|---|---:|---:|
| BUILT | 17 | **7** |
| SPECIFIED | 16 | **27** |

Ten steps were grading themselves. The audit predicted 28 unbuilt; the true
number is 27.

## 3. An effect estimate was computed outside the guard

[0035](0035-power-may-use-the-full-universe-effects-may-not.md) is explicit:
*"Any estimate of an effect must go through the guard: means, medians, hit
rates, t-statistics ... and every one of them charges its family."*

`selling.py` computed `mean_ab=float(cohorts.mean())` on the full universe and
printed it. It charged nothing; `family_charge` holds **0 rows**.

`measure.py`'s docstring states the rule one file away — *"The moment this file
computes a mean return it must move behind the ConfirmationGuard and charge a
trial family"* — and measure.py obeys it. `selling.py` was written afterwards
and did not.

Removed. The module now reports dispersion only.

## Decision

All three are fixed, and `AUDIT_README.md` is kept in the repository unedited.
An audit that found what the project's own instruments missed is evidence about
those instruments, and deleting it once acted upon would remove the only record
that they missed it.

## What would reverse this

Nothing about the fixes. But the *lesson* — that `status.py` cannot audit itself
— argues for a second, independent grader rather than a repaired predicate. That
is not built and this record does not pretend otherwise.

## Cost accepted

- **[0044](0044-selling-is-underpowered-but-the-bound-is-now-the-question.md)'s
  numbers were produced in violation of 0035.** The −23.80% mean, −32.36%
  median and 24.0% hit rate were effect estimates on the full universe, taken
  outside the guard, charging no family. The record is not edited — it says
  plainly that nothing in it is a finding — but a registration must now disclose
  both that the outcome was seen first **and** that it was seen improperly.
- **The trial counter still under-counts.** Five studies have been measured and
  `family_charge` has 0 rows. Fixing the guard's plumbing is Phase 6 work and is
  not done here.
- **The audit's own headline stands: roughly 50% complete.** With the false
  positives removed, 36 of 73 steps are wired or better. Phases 5, 6, 7 and
  Track S are configuration and prose.
- **This project's machinery did not find any of the three.** 411 tests, a
  20/20 gate, a derived status page and a data inventory — and the pipeline was
  broken for a day, the status page was inflating itself, and a decision was
  being violated by the file next to the one that states it.
