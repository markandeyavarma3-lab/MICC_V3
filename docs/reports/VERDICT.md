# Does disclosed institutional activity in Indian equities contain repeatable information?

**No answer is available from this data, and that is the finding.**

**Author:** Markandeya Varma · **Date:** 2026-09-10 · **Repository:** `MICC_V3`
**Status:** the question is closed. What follows is the evidence for closing it.

---

## 1. The question, and why it was worth asking

SEBI requires Indian exchanges to publish every *bulk deal* (≥0.5% of a
company's shares in a session) and every *block deal*, naming the client, the
stock, the side, the quantity and the price. Twenty years of these disclosures
are public and free. The question is whether they contain information a
disciplined observer could have acted on: does a stock behave differently after
a large institution is disclosed to have bought or sold it?

It is a reasonable thing to ask. It is also a question where the literature is
thin for India specifically, the data is unusually granular, and — critically —
where an earlier attempt by the same author had produced an apparent positive
result. That result is the reason this project exists, and §2 is about why it
could not be believed.

## 2. Why the question was asked *again*

A predecessor system (MICCV1/V2) reported a bulk-deal avoidance edge of
**+0.237%/yr**. Decision [0013](../decisions/0013-rerun-exp001-reproducibly.md)
records what happened when someone tried to reproduce it:

> The registration was correctly ordered and the spec genuinely frozen, but the
> analysis code was never committed, and the holdout is recorded as prose — "the
> complementary half of names" — with no seed and no rule. **Nobody can
> regenerate +0.237%/yr, including me.**

That number was not wrong so much as *unfalsifiable*. It had no code, no seed,
no reproducible partition. This project was built to answer the same question in
a way that could be checked — and, more importantly, in a way that could come
back negative and be believed when it did.

**That constraint shaped everything.** A system that can only say yes is not a
measurement device.

## 3. What was built

Counts below are **as of 2026-09-10** and grow daily as collection continues;
the structural findings in §4 do not, and a test binds them to live data.

| | |
|---|---|
| Deal records ingested | 239,480 raw → 239,480 clean, 2006-01-02 to present |
| Price history | 7,792,635 point-in-time rows, split/dividend adjusted |
| Eligible research events | 5,944 after size, liquidity and round-trip filters |
| Forward outcomes | 52,365 across 9 horizons |
| Benchmarks | 5 of 6 specified (one is unbuildable — §7) |
| Automated tests | 540 |
| Decision records | 56 |

Raw and clean are equal by design: every ingested deal reaches the mart with an
explicit eligibility reason, and a test fails if the two ever diverge. **Nothing
is dropped silently** — the predecessor's habit of doing so is the reason this
project exists.

Governance the results depend on: pre-registration with cryptographic spec
freezing; an EXPLORE/SELECT/CONFIRM partition keyed on ISIN so exploratory work
cannot touch confirmatory data; an append-only trial ledger; a content-addressed
provenance graph; and a status page derived from the database rather than
asserted by hand.

## 4. The answer

**Nothing is registrable. No horizon, no population, no participant.**

### 4.1 The power ceiling

An effect must be large enough to see before it can be found. The plausible
effect bound was fixed in advance at 0.5%/month
([0011](../decisions/0011-plausible-effect-bound.md)) and scales with horizon
([0028](../decisions/0028-bound-scales-with-horizon.md)). Against it:

| horizon | events | cohorts | MDE | bound | verdict |
|---|---|---|---|---|---|
| 1 month | 5,644 | 241 | 2.13% | 0.50% | **4.27× short** |
| 3 months | 5,433 | 239 | 4.67% | 1.50% | **3.11× short** |
| 12 months | 4,673 | 230 | 11.54% | 6.00% | **1.92× short** |

Twelve months is the closest and is still nearly twice its own detection floor.
The same arithmetic on every other population — consensus buys, sells, promoter
transactions, pledge events — returns the same verdict: **0 of 15 (population,
horizon) pairs reach their bound.**

**This is not a statistical failure. It is arithmetic.** There were ~6,000
eligible disclosure events in twenty years; collapsed to monthly cohorts to
avoid counting overlapping events as independent, that is ~230 observations. No
estimator creates more disclosures than actually occurred.

### 4.2 The one effect that looked real

Sells showed a −22.7% twelve-month abnormal return — roughly four times the
plausible bound. That is either a large real effect or a confound. The standing
nine-item checklist was run against it
([0051](../decisions/0051-the-sell-effect-is-confounded-not-a-miscalibrated-bound.md),
[0052](../decisions/0052-delisting-is-not-the-load-bearing-assumption-here.md)):

- **Microstructure** — control stocks on identical dates: −0.00%. Explains none.
- **Volatility** — vol-matched peers: −0.06%. Explains none.
- **Momentum reversal** — correlation −0.006, non-monotonic. Rejected.
- **Time concentration** — sign consistent across four eras.
- **Liquidity — fails.** top100 −17.1%, top500_ex100 −25.1%, off500 **−54.7%**.
  The effect is *strongest where it cannot be traded*, and the gradient widens
  once delistings are priced honestly.
- **Survivorship — fails.** 31% of events sit on names that later stopped
  trading.
- **Sector — unmeasurable.** Point-in-time sector data does not exist (§7).

**Verdict: confounded.** An effect that lives in the names you cannot buy is not
an effect you can act on.

### 4.3 No participant is skilled, and the question cannot be asked anyway

The specified procedure ranks participants with a Romano-Wolf stepdown at 5%
family-wise error, then re-runs identically on labels shuffled within date
([0056](../decisions/0056-the-participant-study-cannot-be-run-and-the-machine-does-not-invent-findings.md)).

Real data: **0 supported**, smallest adjusted *p* = 0.62.

But the deeper result is that the study is unrunnable. Eligible participants
have almost no *months*: five of ten appear in exactly one, median two. Since
overlapping events within a month are collapsed to one observation, **only 7
participants in the entire dataset have ≥12 months of activity**, and 1–3 also
clear the event threshold. You cannot rank three candidates.

One horizon did produce a "supported" participant at *p* = 0.0039. It is
`ISHARES MSCI INDIA SMALL-CAP ETF` — a **passive index tracker** — measured over
**two months**. At that same horizon the procedure produces a false positive
11.3% of the time. Across all testable pairs, correlation(months, adjusted *p*)
= **+0.337**: the *less* evidence a name has, the more significant it looks.

**The leaderboard ranks sparsity, not skill.**

And the population is wrong regardless. Six of the seven eligible names are
passive ETFs; the rest are custodians, broker-dealers, and one entity literally
named `GOLDMAN SACHS BANK EUROPE SE - ODI` (an offshore-derivative issuer). **The
participant field identifies vehicles and intermediaries, not decision-makers.**
Asking whether an index tracker has skill is a category error, and it is the
only question this field permits.

## 5. What would change the answer

Stated in advance, so this verdict can be overturned by evidence rather than
by argument:

| condition | why it would matter |
|---|---|
| Materially more disclosure events | The binding constraint is n≈230 monthly cohorts. Nothing else. |
| A participant identity layer resolving to beneficial owners | Would make §4.3 a real question rather than a category error. |
| Point-in-time sector data | Would close the one confound that could not be measured. |
| An effect surviving in `top100` alone | Would answer the liquidity confound, the strongest objection. |

None is available now. All are checkable.

## 6. What this project actually delivers

Not a trading edge. It delivers:

1. **A defensible negative result** — a specific, falsifiable "no" with the
   confounds enumerated, the power arithmetic shown, and the bound fixed before
   the test rather than after.
2. **A clean point-in-time dataset** — twenty years of Indian equity prices,
   institutional deals, corporate actions and flows, each traceable to source.
   Reusable for a different question.
3. **A calibrated measurement instrument.** Under labels carrying no
   information, the pipeline produced a false positive in 1.8% of 1,000
   permutations against a nominal 5%. It does not manufacture findings — which
   is the only reason the "no" above is worth anything.

## 7. Limitations, stated rather than buried

- **`NIFTY500_TR` cannot be built.** Its source table has never existed. It is
  the configuration's own declared broad-market headline, so every benchmarked
  result lacks that comparison.
- **`NIFTY50_TR` is a price index** despite being declared total-return — it
  understates the benchmark by ~1.2%/yr, roughly a fifth of the 12-month bound,
  in the direction that flatters a long-side result.
- **`CHAR_MATCHED` covers 74%** of outcomes and is missing its industry
  dimension entirely.
- **`MERGED` cannot be distinguished from `DELISTED`** — corporate-action
  reasons are unknown on every row, so a merger is priced as a total loss.
- **~26 sessions from 2026-07-09 are permanently lost.** The historical endpoint
  answers 503; the working route serves only the current day.
- **Three lost sessions** (2026-08-19, 2026-08-27) are acknowledged and
  unrecoverable for the same reason.

## 8. What was wrong along the way

Kept because a result is only as good as the errors found before it:

- A **twelve-month label on a 9.6-year holding period.** The forward return
  counted *rows*, not sessions, so a name suspended for years and relisted
  supplied its "252nd session" years later. Fixing it moved every published
  figure and changed no verdict ([0055](../decisions/0055-the-shared-engine-counted-rows-and-the-prune-could-not-see.md)).
- **Three corrupt price partitions** that `COUNT(*)` reported as healthy —
  DuckDB answers that from metadata without decoding a row group.
- **Populating the outcomes table froze the mart for five days** via a foreign
  key, while the collector reported the failure three times a day and nothing
  acted on it.
- **A backup retention policy that never ran once**, because a launchd job
  cannot enumerate a TCC-protected directory and the denial is silent.

The recurring shape is the same: *the signal existed and nothing carried it.*
Seven instances are catalogued across the decision records. That pattern, not
the market result, is what this project is actually about.

---

**Bottom line.** Twenty years of disclosed institutional activity in Indian
equities do not support a registrable finding at any horizon, for any
population, by any participant. The one effect large enough to matter lives in
the least tradeable third of the market and does not survive its confounds. The
one participant that looked skilled is a passive index fund measured over two
months.

The honest answer is *no*, and the instrument that produced it has been checked
against noise and does not invent findings.
