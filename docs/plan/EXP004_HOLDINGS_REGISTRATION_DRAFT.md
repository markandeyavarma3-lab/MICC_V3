# exp_004 — Quarterly institutional holding change as a cross-sectional signal

**Status: DRAFT / PROPOSED — revision 5, 2026-10-02 (the registration rehearsal, §9). Nothing registered.**
Written 2026-09-17 for the owner to argue with; revised after their answers
and after two PRELIMINARY dispersion runs (`docs/reports/HOLDINGS_POWER_PRELIMINARY.md`,
no signal read, nothing frozen) — the first on 220 companies, the second on
449 with the market leg moved to the NIFTY 500 total return (0077). On acceptance it becomes
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

**Measured, not guessed (preliminary, random deciles, market-relative).** Run
twice as the sweep brought companies in:

| | 2026-09-18 | 2026-09-19 | 2026-09-28 | **2026-09-29, floor 100** |
|---|---|---|---|---|
| companies / matured quarters | 220 / 18 | 449 / 19 | 1,147 / 21 | 1,309 / 19 (2021-Q3 on) |
| market leg | seed NIFTY 50 price (ends 2026-07-07) | NIFTY 500 total return (0077) | same | same |
| within-quarter cross-sectional SD | 33% | 47% | 39% | 36% |
| 1st / 99th percentile | −45% / +74% | −44% / +93% | −44% / +89% | −43% / +90% |
| MDE of the decile spread | **12.05%/quarter — 8.0× the bound** | **9.36% — 6.2×** | **10.14% — 6.8×** | **3.89% — 2.6×** |
| winsorised at those percentiles | **4.89% — 3.3×** | **3.39% — 2.3×** | **5.20% — 3.5×** | **1.95% — 1.3×** |

**The minimum quarter size, decided 2026-09-29 before registration: 100 names**
(ten a decile), up from 20 (two a decile). The first three runs admitted the
2018 – 2021-Q2 quarters, whose 13–40 early filers set the MDE. At 50, 100 and 200
the MDE is identical, because nothing sits between 40 names and the 829 of
2021-Q3, so the floor is the principled one, not a number tuned to the answer.
The study now starts at 2021-Q3.

**The third run, on 2.5× the companies, came out slightly worse, not better**: the
shared within-quarter movement does not average away as names are added, and
the widened panel brings in a thin 2021-Q1 cohort (23 names). Full coverage
is therefore unlikely to change the landing. A handful of micro-caps that
tripled or collapsed inside a quarter carry most
of the dispersion, and the second run's wider SD is those names arriving: the
sweep reaches down the size distribution, so the cross-section gets more
dispersed even as the MDE falls.

Scaling to the full universe from the second run cuts the within-quarter term
by at most √6.4 ≈ 2.5× (less, because stocks move together within a quarter):
unclipped ≈ 3.7%, still short; **winsorised ≈ 1.3% — at the bound.** So the study is feasible only
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
| universe_definition | Every ISIN with (a) an XBRL filing (revised ones KEPT — see revised_policy) and a prior filing, (b) an EQ spine session after broadcast (the entry) — **survival to the horizon NOT required (owner decision 2026-10-02; see exit_policy)**, (c) a CHAR_MATCHED bucket, (d) `identity_total` within 1pt of 100. Series EQ/BE at filing. **Off-cycle filings are kept as observations (owner decision 2026-09-18)**: the signal is the change since the PREVIOUS filing, whatever its date, and the interval in days is carried on every row and reported by bucket; a change over 3 weeks and a change over 3 months are both observations, and the robustness section shows the calendar-only result. Counts of exclusions reported per reason. |
| signal_definition | Three tested signals, each Δ`pct_shares` (percent, scale-normalised — see `src/ingest/shp.py`) since the previous filing. **FPI** = `FPI_Cat1` + `FPI_Cat2` + `FPI_Undivided` — three taxonomies map to one series: undivided `InstitutionsForeignPortfolioInvestorMember` (2020–22), `…Catergory…` (NSE's own typo, 2022–24), `…Category…` (2025+); they never co-occur. **All foreign institutions** = `ForeignInst_Total` (`InstitutionsForeignMember`, which ALSO holds FDI, FVCI and sovereign funds — the parser's first label, "FPI_Total", was wrong and is corrected); no counterpart exists in the old taxonomy, so this signal starts in 2022 and is NULL before. **MF** = `MutualFund`. **A category absent from a filing is zero within that filing's taxonomy** — V1.1+ omits zero holdings, and a fund's exit is a signal. **Robustness (reported, not tested)**: Δ`num_shareholders` under the same members. Depth measured 2026-09-18 on 8% of the universe: FPI and MF from 2021Q3, FOREIGN from 2022Q2. |
| interpretation_mode | CROSS_SECTIONAL — ranks are within-quarter; the estimator is the mean over quarters of the decile-spread return. |
| holding_period | Primary 63 sessions (one quarter). Reported: 21, 63, 126, 252. A quarterly signal held for 252 sessions overlaps 3 of 4 cohorts; declared here as the departure from research.yml's 12-month primary, for the same reason 0067 declared 21. |
| entry_policy | Next session's OPEN after `broadcastDate`, per symbol. Never the quarter-end. |
| exit_policy | **Revised 2026-10-02 (owner decision).** HORIZON: close of the name's own h-th EQ session after entry. MOVED: it left EQ but still traded at the calendar exit date — as a new ISIN on the same symbol (adjusted spine) or in another series such as BE/BZ (0082; raw bhavcopy, against the raw entry) — exit at its last close on or before that date. STOPPED: traded nowhere on or after the exit date — 0052, last close × 0.0 headline, 0.25 and 0.50 reported. CENSORED: the window runs past the data — excluded, counted. Market leg over the calendar window. No same-day close. `holdings.price_exits()`. |
| cost_policy | Portfolio gate: long top decile / short bottom decile, equal-weight within side, rebalanced per quarter, full `costs.yml` stack at the pessimistic level, participation cap applied per name. |
| benchmark_policy | **CHAR_MATCHED** (primary — it is the momentum control, see §4; one definition in `charmatch.py`, consumed by `outcomes.py` and `holdings.py` alike). Market-relative reported alongside, against the **NIFTY 500 total return** (`collected:index_tri`, benchmarks.yml's `headline_index`, decision 0077) — not a price index: the ~0.3%/quarter dividend leg is a fifth of this study's own bound. Swapping the primary re-registers. |
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
| kill_criteria | (1) MDE at 63s > plausible bound → **UNDERPOWERED**, reported as such, no fitting. (2) Spread survives only above the participation cap → liquidity, not information. (3) Spread present in the raw-return version and absent in CHAR_MATCHED → momentum, not institutions. (4) Spread driven by the denominator flag → corporate action, not holding: shares outstanding moved by more than **5%** between the two filings (`SHARE_CHANGE_FLAG`, fixed 2026-10-02 — the draft said "abnormal" and named no number), and the spread falls below half the bound without those rows. |
| confounds | momentum APPLICABLE (controlled by CHAR_MATCHED; raw vs matched reported — kill 3); share-count APPLICABLE (flagged — kill 4); index inclusion APPLICABLE, NOT controlled (constituents are one snapshot) — stated limitation; delisting APPLICABLE (0052); size/liquidity APPLICABLE (tiers reported; participation cap — kill 2); industry NOT CONTROLLED (`sector_history` is Phase 3; same degradation `char_panel` already declares). |
| exploratory_prior_run | `docs/reports/HOLDINGS_POWER_PRELIMINARY.md`, run four times (2026-09-18: 3,092 stock-quarters; 2026-09-19: 6,749; 2026-09-28: 17,451 — all at a floor of 20 names a quarter; 2026-09-29: 20,013 at the registered floor of 100): forward market-relative returns were joined to them to measure their DISPERSION under random deciles. No holding percentage, holder count or category was read (`tests/test_holdings_power.py` parses the module's SQL for the signal columns and refuses them). Nothing charged to a family. |

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

## 9. The registration rehearsal (revision 5, 2026-10-02)

`scripts/register_exp004.py --rehearse` registers into a throwaway copy of the
governance db, reads the row back, recomputes the hash, and deletes the copy.
Run before the sweep reaches 95% so that registration day is one command. The
real registry was checked byte-identical before and after. It found:

1. **Six spec fields would have been hashed and not stored.** The script kept
   only fields with a registry column: `tail_rule`, `signal_definition`,
   `confounds`, `revised_policy`, `interval_policy` and `trial_family` would
   have vanished, leaving a hash nobody could recompute and none of the rules
   the study turns on. Fixed: they ride in `configuration_json`, and the
   insert is committed only if the stored row reproduces the hash.
2. **Survivorship in the universe.** (b) required 63 sessions after entry
   while exit_policy cited 0052. 111 of 26,443 filing pairs stopped in EQ
   inside the window: 105 moved to BE/BZ and kept trading, and 6 stopped. The
   owner chose to price them (exit_policy above). This is counted only: no
   return was read.
3. **Seven promised outputs that the code never computed:**
   - the horizons 21, 126 and 252;
   - the holder-count signal;
   - the winsorised variant;
   - the market-relative variant;
   - the recovery-factor variants;
   - the block-bootstrap CI;
   - kill criterion 4.

   All are now in `holdings.run()`, and a test reads its source for each one.
4. **Exclusions were dropped, not counted.** 705 filings had no security for
   the ISIN. Further filings had no EQ session after broadcast, or were
   censored. All are now counted per reason.
5. **The draft contradicted itself** on revised filings (this table said
   "non-revised"; the 2026-09-18 decision keeps them). The script always
   followed the decision, and the draft now does too.
6. **Guards added:** registration refuses with uncommitted code (the
   recorded commit must be the code that runs), and refuses if any named
   input cannot be read. Seven inputs are opened and counted.

Spec hash at rehearsal: `bc4b2d8d8baf…`. It will differ on registration day,
because `data_version` carries the coverage then.


### 9a. Plumbing run on real data (2026-10-04)

`scripts/exp004_plumbing.py` runs the whole registered analysis
(`holdings.run`) on the real warehouse, with every tested signal replaced by
seeded random noise. Nothing about the real signal-return link is read, and
it prints counts and timings only.

**First run: a defect.** `listing_history.closes()` crashed on the one corrupt
2022 price file. It caught errors on opening a file, not while reading it.
exp_004 would have failed on registration day at the first stock that left
EQ. The fix and a test that bites when it is removed are in.

**Second run: every stage ran, in 112 s.**

- **Filings:** 31,008 filing pairs.
- **Exits:** 26,965 HORIZON, 280 MOVED, 7 STOPPED, 2,012 CENSORED.
- **Exclusions counted:** 927 no security; 817 no EQ session after
  broadcast; 3,159 no CHAR_MATCHED cell; 11 cohorts under 100 names.
- **Panel:** 27,252 rows; 16,765 tradeable.
- **Outputs:** 3 primary tests, 12 robustness lines.
