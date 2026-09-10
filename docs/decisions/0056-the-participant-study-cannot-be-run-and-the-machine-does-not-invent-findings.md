# 0056 — The participant study cannot be run, and the machine does not invent findings

**Date:** 2026-09-10
**Decided by:** Me, on the owner's instruction to build step 6.9. The finding
below — that Plan 2 §6.3 is unrunnable on this data — is measured, not chosen.
The one judgement call is that I did **not** repair §6.3 by adding a minimum-
months eligibility rule after seeing the output, and that refusal is the whole
point of the file it lives in.
**Status:** accepted
**Step:** Plan 3 steps 6.8 and 6.9.

## What was asked

Plan 2 §6.3 fixes a participant-ranking procedure and then adds the check that
makes it honest:

> "run the identical procedure on randomly-relabelled participants (permute the
> participant column within date). If the real data yields a similar number of
> 'supported' participants as the shuffled data, there is no participant skill
> in this dataset — only variance. **That comparison is the headline finding,
> not the leaderboard.**"

Step 6.8 (Romano-Wolf stepdown) had to be built first: "identical procedure"
forbids substituting a different correction.

## Result 1 — the machine does not manufacture findings

Under participant labels shuffled within date, where the answer is "nothing" by
construction, the procedure produced a supported participant in **1.8% of 1,000
permutations** at the twelve-month horizon, against the 5% family-wise error
rate Romano-Wolf claims. Calibrated, and on the conservative side.

That matters more than any single verdict this project has reached. **Every
conclusion so far is a negative one resting on this pipeline**, and a pipeline
that invents findings from noise cannot produce a trustworthy "no". It does not.

The real data gives **0 supported participants**, smallest FWER-adjusted
*p* = **0.6222** — not marginal, not close.

## Result 2 — but the study cannot be run at all, and that is the real finding

Across all nine horizons:

| horizon | matured events | eligible | supported | min adj *p* | shuffled rate |
|---|---|---|---|---|---|
| 1s | 4,288 | 10 | 0 | 0.6159 | 1.3% |
| 2s | 4,285 | 10 | 0 | 0.3894 | 9.4% |
| 3s | 4,278 | 10 | 0 | 0.3387 | 0.1% |
| 5s | 4,251 | 10 | 0 | 0.5324 | 3.1% |
| 10s | 4,197 | 10 | 0 | 0.6382 | 0.0% |
| 21s | 4,171 | 10 | 0 | 0.2697 | 1.1% |
| **63s (3m)** | 4,087 | 10 | **1** | **0.0039** | **11.3%** |
| 126s (6m) | 3,978 | 9 | 0 | 0.2981 | 0.0% |
| 252s (12m) | 3,516 | 7 | 0 | 0.6222 | 1.8% |

**One horizon produced a "supported" participant at adjusted p = 0.0039 — and
at that same horizon the procedure produces one from pure noise 11.3% of the
time.** Without the null calibration this would have been reported as the
project's first positive finding. With it, it is an artefact of a correction
that is unreliable at that horizon. This is exactly what step 6.9 exists for.

### Why the calibration is erratic, and why §6.3 is unrunnable

The eligible participants have almost no **months**:

```
horizon 252s   months present per eligible participant: [1, 1, 1, 1, 2, 3, 24]
```

Five of the ten eligible names at the short horizons appear in **exactly one
month**; the median is two. Plan 2 §6.1 requires the monthly-cohort collapse so
that overlapping events are not counted as independent observations — so a
participant with 30 events concentrated in one month contributes **one**
observation, and its studentised statistic is undefined and scores zero.

Counting participants who could support a monthly-cohort statistic at all:

| threshold | 21s | 252s |
|---|---|---|
| ≥2 distinct months | 334 | 298 |
| ≥6 months | 34 | 20 |
| ≥12 months | 9 | 7 |
| **≥12 months AND ≥30 events** | **2** | **1** |
| ≥36 months | 0 | 0 |

**One participant in the entire dataset could support the specified test at the
primary horizon.** You cannot rank one candidate, and a bootstrap over two to
four monthly observations is what makes the FWER swing from 0.0% to 11.3%.

So the honest verdict is not "no participant skill was found". It is: **the
study specified in Plan 2 §6.3 cannot be run on this data.** §6.1 and §6.3 are
in direct conflict — one requires monthly collapse, the other sets eligibility
on events — and nothing reconciles them at this sample size.

### And the population is not what the plan imagined either

§6.3 expects ≥30 matured events to reduce 27,417 names "to a few hundred". It
reduces them to seven. Of those seven, six are passive index vehicles — iShares
MSCI India Small-Cap, iShares Core MSCI EM, iShares India 50, iShares MSCI EM,
iShares MSCI India, PowerShares India Portfolio — and the seventh is a
broker-dealer. At the short horizons the list adds `GOLDMAN SACHS BANK EUROPE SE
- ODI`, an offshore-derivative issuer, and a pension-fund custodian.

**The participant field does not identify decision-makers.** It identifies ETFs,
custodians, and P-note issuers. Asking whether a passive index tracker has skill
is a category error, and it is the only question this field can be asked.

Name fragmentation compounds it but is not the binding constraint: 310 names
collapse onto 135 entities across 1,060 eligible deals — Goldman Sachs
Investments (Mauritius) I alone appears under six spellings — and normalising
them moves exactly one entity across the eligibility bar. Plan 1 step 3.6 would
fix the spelling and would not fix the question.

## What I did not do

I did not add a minimum-months eligibility rule and re-run. It would raise N,
stabilise the bootstrap, and probably deliver a well-calibrated 5%. It would
also be a change to a pre-specified procedure made **after seeing its output**,
which is the failure this entire project was built to refuse. `MIN_MONTHS` is
defined and reported, and applied to nothing. A future pre-registration should
set eligibility on months rather than events; this one did not, and it runs as
written.

## Two things found while building it

- **Three corrupt `price_spine` partitions** (`_y=2006/2007/2008`). Decision
  0049's failure mode, recurring. Repaired by rebuild from intact sources; the
  reconciliation gate caught it, and the row counts matched exactly afterwards.
- **`COUNT(*)` on a parquet file proves nothing.** My first corruption scan read
  every file with `COUNT(*)` and reported all 359 healthy. DuckDB answers that
  from parquet metadata without touching a row group. The corruption only
  surfaced under `sum(hash(COLUMNS(*)))`, which forces every column to decode.
  A health check that cannot see a destroyed row group is a health check that
  will pass over a destroyed warehouse.
- **The mart rebuild now cascades into `deal_forward_outcomes`** (0055), so
  every collector run empties it. `collect_daily.sh` rebuilds outcomes
  immediately after the mart — 97 seconds — because a table that is empty
  between nightly runs while grading as BUILT is the worse failure.

## Amendment, 2026-09-10 (same day, before any work rested on it)

The owner asked whether I was sure. Three checks; the verdict is unchanged and
stronger, and two figures above were overstated. Recorded here rather than
edited away, and the original text is left standing.

**1. "One participant in the entire dataset could support the specified test"
is benchmark-specific, and I did not say so.** It is one under CHAR_MATCHED,
which covers 74% of outcomes. Under EW_TOP500, which covers 100%, it is three.
The benchmark-independent figure — the one that should have been quoted — is
that **7 participants have ≥12 months of activity at all**, of which 3 also
clear 30 events. The conclusion holds either way; the number I chose happened to
be the most dramatic one available, which is not how a number should be chosen.

**2. "The procedure is calibrated" is true at seven of nine horizons, not all
nine.** Rates: 0.0%, 0.1%, 1.1%, 1.3%, 1.8%, 3.1%, **9.4%**, **11.3%**. Two
horizons are roughly double the nominal 5%. The honest statement is that the
correction is calibrated where participants have months and unreliable where
they do not, which makes the miscalibration and the unrunnability the same
phenomenon rather than two findings.

**3. The 63s artefact is confirmed, and the mechanism is now explicit.** The
"supported" participant is `ISHARES MSCI INDIA SMALL-CAP ETF` — a passive
small-cap index tracker — with **223 events across TWO months**, adjusted
p = 0.0039. Meanwhile `SOCIETE GENERALE`, the only name in the family with a
usable history at **29 months**, sits at p = 0.539.

Across all 33 testable (participant, horizon) pairs:

    correlation(months present, FWER-adjusted p) = +0.337

**Positive is backwards.** More evidence should mean a smaller p. Here the
fewer months a participant has, the more significant it looks, because a
studentised mean over two observations has no stable denominator. The
leaderboard ranks sparsity, not skill, and the one apparent finding in nine
horizons is the sparsest name in its family.

## What would reverse this

A participant identity layer that resolves to beneficial owners rather than
custodians, or enough additional history that some real manager accumulates
three years of monthly activity. Neither is available. If `testable` in
`nullcal.py` ever rises above two, the test guarding it fails and this verdict
needs revisiting — which is the intended trigger.

## Cost accepted

No trials. The null calibration is a property of the procedure, not an estimate
of an effect, and the leaderboard it produces is reported as variance rather
than registered as a result.
