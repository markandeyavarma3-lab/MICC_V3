# 0052 — Delisting is not the load-bearing assumption here, and censoring was the bigger drop

**Date:** 2026-09-03
**Decided by:** Me, building the reversal test 0051 named for itself. The owner
asked to continue; which step to take was my call, and so is the conclusion that
the result does not reverse. The framing error in 0051 is mine and is corrected
here rather than edited there.
**Status:** accepted
**Supersedes:** nothing. **Answers:** the reversal condition set by [0051](0051-the-sell-effect-is-confounded-not-a-miscalibrated-bound.md).
**Step:** Plan 3 step 6.4.

## The question 0051 asked

0051 closed with a named reversal condition:

> Step 6.4 built, delisting recovery factors applied at all three levels, and
> the effect surviving in `top100` alone at a magnitude that still exceeds the
> bound. The top100 tier is already the weakest at −25.43%; the test is whether
> it holds once dying names are priced honestly.

**That framing was wrong, and it was wrong in a way worth recording.** It
assumed pricing dead names would *weaken* the effect. A sell followed by a
delisting priced at total loss is a −100% return; including it makes the sell
effect larger. The silent drop was flattering the null, not the finding.

I wrote that sentence yesterday. The arithmetic that contradicts it was
available at the time.

## What the events actually were

Of 1,255 EXPLORE sell events at the twelve-month horizon, 110 had no exit price
and were dropped from the mean while still being counted in `n` — `COUNT(*)`
counts NULLs and `avg()` does not, so `confounds.py` reported "n=1,255, raw
effect −30.30%" from two different populations. Those 110 turned out to be
three unrelated things:

| reason | n | share | treatment |
|---|---|---|---|
| `HORIZON` | 1,145 | 91.2% | real exit at the horizon |
| `CENSORED` | 76 | 6.1% | **excluded** — still trading, horizon runs past the data |
| `STOPPED` | 31 | 2.5% | **priced** at last close × recovery factor |
| `NO_BENCHMARK` | 3 | 0.2% | **excluded** — no market leg exists at that date |

`CENSORED` is 2.5× more numerous than the delistings. These are live companies
whose twelve-month window has not finished yet. Pricing them at a recovery
factor would have invented a delisting for each, and the error does not run in
the conservative direction. **The bigger of the two drops was never a delisting
problem at all.**

`NO_BENCHMARK` was found by a test, not by reading the code — see below.

## The measurement

Headline recovery factor 0.0, per Plan 2 §3.4. All three factors reported.

| stratum | base | +priced | rf=0.00 | rf=0.25 | rf=0.50 |
|---|---|---|---|---|---|
| ALL | −30.30% (n=1,145) | +31 | **−32.11%** | −31.63% | −31.16% |
| top100 | −25.43% (n=464) | +5 | **−26.54%** | −26.36% | −26.18% |
| top500_ex100 | −32.98% (n=402) | +13 | **−34.41%** | −34.36% | −34.31% |
| off500 | −60.32% (n=105) | +13 | **−65.51%** | −61.68% | −57.85% |

## Three findings

**1. The recovery factor is not load-bearing on this population.** Plan 2 §3.4
calls it "the single most consequential assumption in the study" — on 6,574 of
30,771 full-universe events, 21%. On EXPLORE sells at twelve months it is 31 of
1,255, 2.5%, and the three factors span 0.95pp on the headline. The plan's
claim is correct about the study it describes and wrong about this population.
Repeating it here would have been borrowed alarm, so a test pins the span and
fails if it ever becomes consequential.

**2. The liquidity gradient widens.** 0051's central finding is that the effect
is strongest in the names you cannot trade. Delisting concentrates in those same
names, and honest pricing pushes them further apart: the top100-to-off500 span
goes from 34.89pp to 38.97pp. The ordering is unchanged. **This strengthens
0051's verdict rather than reversing it.**

**3. The reversal condition is technically met and materially irrelevant.**
`top100` survives at −26.54%, far exceeding the 6% twelve-month bound. But 0044
and 0050 already established the effect exceeds its bound by ~4× and that *no
population is powered*. 6.4 does not touch power. An unpowered effect that grew
slightly is still an unpowered effect.

**0011's bound is not revised. The sell effect remains confounded.**

## What the test found that I did not

The first version of `test_censored_events_are_excluded_not_priced` asserted
only counts. Deleting the `CENSORED` filter outright left it **green** while 76
live companies were priced at −100%. Adding `n_rf` — the row count the recovery
mean is actually taken over — made it fail under that perturbation, and on the
*unperturbed* code too: 1,176 rows against 1,145 + 34 expected.

The three missing rows were `STOPPED` events on dates inside 252 sessions of
the cutoff, where the cross-sectional market mean is undefined. They were being
dropped exactly the way the original 110 were — LEFT JOIN keeps the row, `avg()`
skips it, the count does not move. **Same bug, one layer down, in the module
written to fix that bug.** They are now a declared `NO_BENCHMARK` category.

This is the sixth instance of the project's standing pattern: the signal existed
and nothing carried it. It is the first one caught by a test written in the same
sitting rather than by an audit weeks later.

## Declared limitations

- **MERGED and SUSPENDED cannot be separated from DELISTED.**
  `security_master.delisting_reason` is `UNKNOWN` on every row — Plan 1 step 3.3
  is BUILT, not finished, because the distinction needs corporate actions that
  are not collected. Every `STOPPED` event is priced as `DELISTED`. A merger
  priced at 0.0 is a real overstatement; at 31 events it cannot move the
  headline more than the 0.95pp the factor span already bounds.
- **Nothing is persisted.** `deal_forward_outcomes` holds 0 rows because step
  6.3 is unbuilt. This is a measurement, not a stored outcome, and step 6.4 is
  graded with that stated rather than marked complete.
- **EXPLORE only**, per `split.yml`. CONFIRM is not spent on a diagnostic.

## What would reverse this

Step 3.3 finished, so mergers roll into the acquirer instead of being written to
zero; and step 6.3 built, so the treatment applies to all nine horizons rather
than the one. Neither changes the power verdict, which is what actually decides
whether any of this becomes a finding.

## Cost accepted

Charged `TRACK_D_DEALS` +4 trials (four strata) → 191. Per 0035, pricing an
event changes an effect estimate, so it spends the family.
