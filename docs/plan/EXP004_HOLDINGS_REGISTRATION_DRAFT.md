# exp_004 — Quarterly institutional holding change as a cross-sectional signal

**Status: DRAFT / PROPOSED — revision 2, 2026-09-18. Nothing registered.**
Written 2026-09-17 for the owner to argue with; revised after their answers
and after a PRELIMINARY dispersion run (`docs/reports/HOLDINGS_POWER_PRELIMINARY.md`,
no signal read, nothing frozen) on the first 220 companies. On acceptance it becomes
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

**Measured, not guessed (2026-09-18, preliminary, 220 companies, 18 matured
quarters, random deciles, market-relative):** the within-quarter cross-sectional
SD of a 63-session market-relative return is **33%**, the 1st/99th percentiles
are **−45% / +74%**, and the MDE of the decile spread is **12.05% per quarter —
8× the bound**. Winsorised at those percentiles the MDE is **4.89% — 3.3× the
bound**. A handful of micro-caps that tripled or collapsed inside a quarter
carry most of the dispersion.

Scaling to the full universe cuts the within-quarter term by at most √10 ≈ 3.2×
(less, because stocks move together within a quarter): unclipped ≈ 3.8%, still
short; **winsorised ≈ 1.5% — at the bound.** So the study is feasible only
with a tail rule, and that rule has to be chosen NOW, before any signal is
read, or it becomes a knob. Two candidates, one to be picked in §6:

- **winsorise the outcome at 1st/99th** (keeps every name; clips the effect of
  the extremes), or
- **restrict the universe by liquidity** — the `costs.yml` participation cap
  already implies one; a spread that exists only in names the cap excludes
  fails kill criterion 2 anyway.

The dispersion-only run on the FULL panel decides between "at the bound" and
"still short" before the pass bar is applied, and the owner is told the number
first. The bound is fixed at 0028's number and is not raised after seeing the SD.

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
| hypothesis | The top decile of filing-over-filing change in a stock's institutional holding — FPI (Cat I + II), all foreign institutions, and mutual funds, each a separate test — ranked within quarter, earns a higher CHAR_MATCHED abnormal return over the next 63 sessions than the bottom decile, after multiplicity. |
| prior_belief | Weak-to-moderate. The literature finds a short-horizon effect for active institutions; Indian evidence is thin, the panel is 20 quarters, and the honest expectation is UNDERPOWERED against 0028's bound. |
| data_version | SHP XBRL `[sweep: N symbols, Q quarters, first→last]`, source `nse_shp_xbrl` (0074); prices `price_spine_adj` as of `[sweep date]`; `char_panel` as of same; identity by **ISIN** (0069), never symbol. |
| universe_definition | Every ISIN with (a) a non-revised XBRL filing (`revised = false`, per the master's `revisedStatus`) and a prior filing, (b) a spine price on the entry session, (c) a CHAR_MATCHED bucket, (d) `identity_total` within 1pt of 100. Series EQ/BE at filing. **Off-cycle filings are kept as observations (owner decision 2026-09-18)**: the signal is the change since the PREVIOUS filing, whatever its date, and the interval in days is carried on every row and reported by bucket; a change over 3 weeks and a change over 3 months are both observations, and the robustness section shows the calendar-only result. Counts of exclusions reported per reason. |
| signal_definition | Three tested signals, each Δ`pct_shares` (percent, scale-normalised — see `src/ingest/shp.py`) since the previous filing. **FPI** = `FPI_Cat1` + `FPI_Cat2` + `FPI_Undivided` — three taxonomies map to one series: undivided `InstitutionsForeignPortfolioInvestorMember` (2020–22), `…Catergory…` (NSE's own typo, 2022–24), `…Category…` (2025+); they never co-occur. **All foreign institutions** = `ForeignInst_Total` (`InstitutionsForeignMember`, which ALSO holds FDI, FVCI and sovereign funds — the parser's first label, "FPI_Total", was wrong and is corrected); no counterpart exists in the old taxonomy, so this signal starts in 2022 and is NULL before. **MF** = `MutualFund`. **A category absent from a filing is zero within that filing's taxonomy** — V1.1+ omits zero holdings, and a fund's exit is a signal. **Robustness (reported, not tested)**: Δ`num_shareholders` under the same members. Depth measured 2026-09-18 on 8% of the universe: FPI and MF from 2021Q3, FOREIGN from 2022Q2. |
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
| test_count | **3** (FPI, all-foreign, MF) × 1 primary horizon. Owner's choice 2026-09-18, knowing each extra test costs power. |
| multiple_testing_policy | Benjamini–Hochberg FDR 5% across the 3 tests, declared here. Robustness horizons, the count signal and the calendar-only variant reported, never tested. |
| outcome_tail_rule | **CHOSEN 2026-09-18: the participation cap.** A name is in the primary universe only if 5 sessions × 5% of ADV20 (costs.yml's pessimistic level) can build its equal-weight share of one side of a **₹100 crore** long–short book, decided per cohort. One declared parameter (the notional), the same cost model the project already imposes, and a spread that exists only in untradeable names fails kill 2 anyway. Winsorisation at 1st/99th is reported as robustness. `holdings.tradeable()`. |
| revised_policy | **DECIDED 2026-09-18 (a): keep revised filings, entering on the revised broadcast date.** NSE's master replaces the original with the revision and keeps no copy — 598 of 4,137 filings on the sample. The revision is the only version that exists; its `broadcast_date` is when the corrected figures became public, so entering after it is point-in-time honest and later than an original would have been. The `revised` flag is carried and reported by cohort. |
| interval_policy | **DECIDED 2026-09-18 (a): cap at 200 days.** A change spanning more than 200 days between filings is a resumption after a filing gap (20 changes spanned 400–1,096 days on the sample), not a quarterly signal. Excluded from the primary, counted. Every ordinary quarter and every off-cycle filing that follows one is kept. |
| permutation_policy | Moving-block bootstrap over quarters, block = 2 quarters, 10,000 draws, seed 20260917. Within-quarter label permutation (1,000) as the null calibration, per `nullcal.py`'s method. |
| pass_bar | Event gate: decile spread at 63 sessions clears the serial-corrected MDE **and** the plausible bound (0.5%/month × 3) at BH-FDR 5%; **and** portfolio gate (0003): the long–short beats CHAR_MATCHED net of costs on the evaluation period. Both. |
| kill_criteria | (1) MDE at 63s > plausible bound → **UNDERPOWERED**, reported as such, no fitting. (2) Spread survives only above the participation cap → liquidity, not information. (3) Spread present in the raw-return version and absent in CHAR_MATCHED → momentum, not institutions. (4) Spread driven by the denominator flag (share-count change) → corporate action, not holding. |
| confounds | momentum APPLICABLE (controlled by CHAR_MATCHED; raw vs matched reported — kill 3); share-count APPLICABLE (flagged — kill 4); index inclusion APPLICABLE, NOT controlled (constituents are one snapshot) — stated limitation; delisting APPLICABLE (0052); size/liquidity APPLICABLE (tiers reported; participation cap — kill 2); industry NOT CONTROLLED (`sector_history` is Phase 3; same degradation `char_panel` already declares). |
| exploratory_prior_run | `docs/reports/HOLDINGS_POWER_PRELIMINARY.md` (2026-09-18): forward market-relative returns were joined to 3,092 stock-quarters to measure their DISPERSION under random deciles. No holding percentage, holder count or category was read (`tests/test_holdings_power.py` parses the module's SQL for the signal columns and refuses them). Nothing charged to a family. |

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

## 8. What is built (2026-09-18) and what happens on acceptance

Built, tested, pushed: `src/research/holdings.py` — `signals()` runs now (a
parse); `panel()` and `run()` refuse without a registration. `scripts/
register_exp004.py` refuses below 95% sweep coverage; both policies are now set,
so coverage is the only remaining gate. `TRACK_H_HOLDINGS` is in `trials.yml` at
counter 0. Nothing has read a signal against a return.

On acceptance, in order:

1. `trials.yml` gains `TRACK_H_HOLDINGS` (carried 0).
2. `scripts/register_exp004.py` writes this table, plain INSERT, hashed.
3. A parser lands the XBRL categories as a table — **percent and count per
   (ISIN, quarter, category), with `broadcastDate`** — and nothing else.
4. `src/research/holdings_power.py` computes the quarterly decile-spread SD
   and n only, refuses to run without the hash, and prints the MDE against the
   bound. **The owner reads that number before step 5 exists.**
5. Only then: the study.
