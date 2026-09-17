# exp_004 — Quarterly institutional holding change as a cross-sectional signal

**Status: DRAFT / PROPOSED. Nothing registered, nothing computed.**
Written 2026-09-17 for the owner to argue with. On acceptance it becomes
decision 0075, `scripts/register_exp004.py` (plain INSERT, hashed), a
`TRACK_H_HOLDINGS` family in `trials.yml`, and a dispersion-only power run on
the pattern of `oi_power.py` — in that order, before any forward return is read.

Blanks marked `[sweep]` are filled from the completed SHP sweep (0074) before
the spec is hashed. They are counts, not choices.

---

## 1. The question

**Does a quarter-over-quarter change in a stock's institutional holding — foreign
(FPI) and mutual-fund (MF) separately — predict that stock's abnormal return over
the following quarter, across the cross-section of listed companies?**

Unit: one symbol at one quarter-end. ~2,900 symbols × ~20 quarters.

## 2. What it is not

- **Not the deals question.** Deals are events an institution chose on a day;
  this is a level reported on a date. It is closer to Gompers–Metrick /
  Nofsinger–Sias than to anything Track D tested.
- **Not FII/DII flow.** `fii_dii_cash` is market-level daily flow; this is
  stock-level quarterly ownership. Different object, different family.
- **Not a promoter study.** Promoter holding is reported in the same filing and
  is explicitly excluded from the primary — a promoter is not an institution,
  and `roles.py` already says so.

## 3. Why the shape is different, and why it is still thin

Every study here died on the same number: independent monthly cohorts. Deals
have 249 and a handful of events in each. This has ~20 quarters and **the entire
listed universe in each** — the first structure in this project not starved on
the cross-section.

The honest arithmetic, before any data: a diversified long–short decile spread
of ~290 stocks a side has a quarterly SD on the order of 4%. At 20 periods,
80% power, 5% two-sided, `power.mde` gives roughly **2.5% per quarter**. The
standing plausible bound (0028: 0.5%/month) is **1.5% per quarter**. If those
guesses hold, the study is **UNDERPOWERED by construction** and the landing is
"cannot yet be distinguished from zero at 20 quarters", not a hint in either
direction. It reaches the bound at ~56 quarters — fourteen years — unless the
realised SD is lower than the guess. **The dispersion-only run decides this
BEFORE the pass bar is applied, and the owner is told the number first.**

Registering a study that may land UNDERPOWERED is the project's standing
practice (0067 registered exp_003 with the same warning). What is not standing
practice is raising the plausible bound after seeing the SD. The bound is fixed
here, now, at 0028's number.

## 4. The confound, stated correctly

I told the owner on 2026-09-17 that holding percentage "rises mechanically when
price rises". **That is wrong for this data**: the reported figure is a share of
shares outstanding, not of value. If FPIs hold 10% of a company's shares and the
price doubles, they hold 10%.

The real confound is **selection, not mechanics**: institutions buy what has
risen, so ΔFPI% correlates with past return, and past return predicts future
return through momentum. Without a control, the study measures momentum and
calls it institutions. The control is the one this project already has:
**CHAR_MATCHED** (`benchmarks.yml`, `char_panel` with size / momentum /
volatility buckets, rebuilt nightly since 0055). The abnormal return is
measured against the stock's own characteristic bucket, so a stock that rose
because it had momentum is compared to stocks that also had it.

Secondary confounds, each reported: share-count changes (buybacks / issuance
move every category's % together — the denominator, reported as a flag from
`NumberOfSharesOnFullyDilutedBasis…`); index-inclusion events (a stock entering
an index gets passive FPI/MF buying for a non-informational reason —
`nifty500_constituents` is a single snapshot today, so this is reported as a
limitation, not controlled); and delisting (0052's policy applies unchanged).

## 5. Point-in-time, or the study is invalid

The quarter-end is `date`; the filing reaches the public at **`broadcastDate`**,
typically two to four weeks later, sometimes more. A position opened at the
quarter-end would be trading on information not yet public. **Entry is the next
session's OPEN after `broadcastDate`**, per stock. Each symbol-quarter's holding
period therefore starts on its own date; a "quarterly cohort" is the set of
symbols whose filings broadcast in that quarter's filing window, and cohorts are
non-overlapping at the primary horizon. `available_from` is HIGH confidence
from the first row, as it is for insider filings, because the timestamp is
observed.

Revised filings (`revisedStatus`, `revisedDate`) are excluded from the primary
and counted; the original broadcast is the point-in-time fact.

## 6. Frozen specification (the registry row is this, hashed)

| field | value |
|---|---|
| experiment_id | `exp_004_holdings_change` |
| engine_id | `ENGINE_H_HOLDINGS` |
| trial_family | `TRACK_H_HOLDINGS` — new, counter 0, `selection_happens_within: true` |
| hypothesis | The top decile of quarter-over-quarter change in a stock's FPI (primary) or MF (secondary) holding, ranked within quarter, earns a higher CHAR_MATCHED abnormal return over the next 63 sessions than the bottom decile, after multiplicity. |
| prior_belief | Weak-to-moderate. The literature finds a short-horizon effect for active institutions; Indian evidence is thin, the panel is 20 quarters, and the honest expectation is UNDERPOWERED against 0028's bound. |
| data_version | SHP XBRL `[sweep: N symbols, Q quarters, first→last]`, source `nse_shp_xbrl` (0074); prices `price_spine_adj` as of `[sweep date]`; `char_panel` as of same; identity by **ISIN** (0069), never symbol. |
| universe_definition | Every ISIN with (a) a non-revised XBRL filing at quarter q and q−1, (b) a spine price on the entry session, (c) a CHAR_MATCHED bucket. Series EQ/BE at filing. Counts of exclusions reported per reason. |
| signal_definition | **Primary**: Δ`ShareholdingAsAPercentageOfTotalNumberOfShares` under `InstitutionsForeignMember`, q−1→q. **Secondary**: same under `MutualFundsOrUTIMember`. **Robustness (reported, not tested)**: Δ`NumberOfShareholders` under the same members — an entry/exit count one large holder cannot dominate. |
| interpretation_mode | CROSS_SECTIONAL — ranks are within-quarter; the estimator is the mean over quarters of the decile-spread return. |
| holding_period | Primary 63 sessions (one quarter). Reported: 21, 63, 126, 252. A quarterly signal held for 252 sessions overlaps 3 of 4 cohorts; declared here as the departure from research.yml's 12-month primary, for the same reason 0067 declared 21. |
| entry_policy | Next session's OPEN after `broadcastDate`, per symbol. Never the quarter-end. |
| exit_policy | Close of entry + h sessions; 0052 delisting policy; no same-day close. |
| cost_policy | Portfolio gate: long top decile / short bottom decile, equal-weight within side, rebalanced per quarter, full `costs.yml` stack at the pessimistic level, participation cap applied per name. |
| benchmark_policy | **CHAR_MATCHED** (primary — it is the momentum control, see §4). Market-relative (NIFTY 500 TRI) reported alongside. Swapping the primary re-registers. |
| training_period | **None.** Within-quarter decile ranks have no fitted parameter; there is nothing to hold out and nothing to leak. |
| validation_period | none |
| final_test_period | `[sweep: first quarter with q−1 available]` → `[sweep: last quarter whose 63-session horizon has matured]`. Touched once. |
| search_space_definition | ONE specification, no free parameters. Deciles within quarter. Estimator = mean across quarters of (top − bottom) CHAR_MATCHED abnormal return at 63 sessions, Newey–West with lag from `power.nw_lag` on the quarterly series. |
| test_count | **2** (FPI, MF) × 1 primary horizon. |
| multiple_testing_policy | Benjamini–Hochberg FDR 5% across the 2 tests, declared here. Robustness horizons and the count signal reported, never tested. |
| permutation_policy | Moving-block bootstrap over quarters, block = 2 quarters, 10,000 draws, seed 20260917. Within-quarter label permutation (1,000) as the null calibration, per `nullcal.py`'s method. |
| pass_bar | Event gate: decile spread at 63 sessions clears the serial-corrected MDE **and** the plausible bound (0.5%/month × 3) at BH-FDR 5%; **and** portfolio gate (0003): the long–short beats CHAR_MATCHED net of costs on the evaluation period. Both. |
| kill_criteria | (1) MDE at 63s > plausible bound → **UNDERPOWERED**, reported as such, no fitting. (2) Spread survives only above the participation cap → liquidity, not information. (3) Spread present in the raw-return version and absent in CHAR_MATCHED → momentum, not institutions. (4) Spread driven by the denominator flag (share-count change) → corporate action, not holding. |
| confounds | momentum APPLICABLE (controlled by CHAR_MATCHED; raw vs matched reported — kill 3); share-count APPLICABLE (flagged — kill 4); index inclusion APPLICABLE, NOT controlled (constituents are one snapshot) — stated limitation; delisting APPLICABLE (0052); size/liquidity APPLICABLE (tiers reported; participation cap — kill 2); industry NOT CONTROLLED (`sector_history` is Phase 3; same degradation `char_panel` already declares). |
| exploratory_prior_run | none. No forward return has been joined to any SHP row. The sweep (0074) archived bytes; this draft was written from element names in one XBRL and the manifest's counts. |

## 7. What would make me not register it

- The dispersion-only run puts the MDE at more than ~3× the bound. Then 20
  quarters cannot say anything and registering is theatre; the archive keeps
  accruing four quarters a year and the question waits.
- The point-in-time join loses most of the universe — e.g. `broadcastDate`
  missing or unparseable on a large share of filings. Then the entry date is a
  guess and §5 fails.
- The XBRL category members prove inconsistent across years (the 2018 filings
  are pre-format-change for some symbols). Then the signal is not one series
  and the panel starts where consistency does.

## 8. What happens on acceptance, in order

1. `trials.yml` gains `TRACK_H_HOLDINGS` (carried 0).
2. `scripts/register_exp004.py` writes this table, plain INSERT, hashed.
3. A parser lands the XBRL categories as a table — **percent and count per
   (ISIN, quarter, category), with `broadcastDate`** — and nothing else.
4. `src/research/holdings_power.py` computes the quarterly decile-spread SD
   and n only, refuses to run without the hash, and prints the MDE against the
   bound. **The owner reads that number before step 5 exists.**
5. Only then: the study.
