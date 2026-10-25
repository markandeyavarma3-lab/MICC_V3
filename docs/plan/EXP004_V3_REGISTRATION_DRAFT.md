# exp_004 v3 — quarterly institutional holding change, on the quarters no one has read

**Status: OPTION C CHOSEN (owner, 2026-10-25, decision 0092) — NOT REGISTERED. The clean quarters wait; the A/B tail rule is still open.**
Written 2026-10-25 for the owner to choose from. Two versions are set side by
side in §4; they differ in ONE rule — whether extreme returns are capped. The
owner picks A, B, or neither (§7). Nothing is registered until the owner writes
"approve" for a named version.

---

## 1. In plain words

**The question** (unchanged from v1 and v2): when mutual funds or foreign
portfolio investors raise their stake in a company over a quarter, does that
stock beat similar stocks over the next three months?

**Why there is a v3 at all.** v2 was registered and run on 9 October 2026
(decision 0076) and landed **UNDERPOWERED**. It could only use quarters from
2021-Q3 on, because before then too few companies had filings in the archive.
Since then the BSE backfill brought in shareholding filings for 2016 – 2021
(35,719 files; the 2016-2017 ones were read only from 2026-10-25, when a
parser gap was fixed). That opens **21 earlier quarters**.

**The rule that shapes everything below.** v2's results were seen: the
spreads (FPI +0.77%, all-foreign −0.10%, MF +0.65%), their confidence
intervals, and 36 robustness lines including the capped (winsorised)
version. A design chosen after seeing results is not a test. So **v3 may only
be tested on quarters v2 never read: 2016-Q2 to 2021-Q2.** The quarters from
2021-Q3 on are spent, for both versions.

**The honest landing.** On those 21 clean quarters, neither version reaches the
power target (§3). The capped version is closer (1.47× short) than the
uncapped one (4.76× short). Registering either now would most likely end
UNDERPOWERED and cost the family two more trials.

## 2. What changed since v2

| | v2 (registered, closed) | v3 (this draft) |
|---|---|---|
| test period | 2021-Q3 → 2026-Q2 (18 matured cohorts) | **2016-Q2 → 2021-Q2** (21 quarters), never read |
| signals tested | 3: FPI, all foreign institutions, MF | **2: FPI, MF**. "All foreign institutions" (`InstitutionsForeignMember`) does not exist in filings before 2022, so it cannot be tested on this period |
| source of filings | NSE XBRL | BSE XBRL (2016-06-23 and 2018-03-31 schemas), NSE from 2021-09 |
| tail rule | participation cap; winsorised reported only | **A: participation cap + outcome capped at 1st/99th percentile** · **B: participation cap only (= v2's rule)** |
| family trials before | 0 | **3** (`TRACK_H_HOLDINGS` was charged 3 by v2): the bar is stricter |
| everything else | §6 of `EXP004_HOLDINGS_REGISTRATION_DRAFT.md` | **unchanged** (entry, exit, CHAR_MATCHED, costs, kill criteria 2-4) |

## 3. The power numbers (measured 2026-10-25, dispersion only)

`src/research/holdings_power.py`: random deciles, market-relative 63-session
returns, ≥ 100 names a quarter, 2,000 permutation draws, rows in a fixed
order so the figure reproduces exactly (fixed 2026-10-25). **No holding change
was set against any return** (`tests/test_holdings_power.py` refuses the
signal columns). Nothing charged.

| period | quarters | stock-quarters | MDE, no cap | MDE, capped 1st/99th | bound |
|---|---:|---:|---:|---:|---:|
| **2016-Q2 → 2021-Q2 (clean)** | **21** | **31,684** | **7.13% — 4.76×** | **2.20% — 1.47×** | 1.50% |
| 2021-Q3 → 2026-Q2 (read by v2) | 20 | 34,895 | 2.67% — 1.78× | 1.49% — 0.99× | 1.50% |
| all 41 quarters (not allowed) | 41 | 66,579 | 3.91% — 2.61× | 1.32% — 0.88× | 1.50% |

**Read the last row as a warning, not an option.** It is the only one inside
the bound, and only because it reuses the 20 quarters whose answer v2 already
showed. A test that includes them is not confirmatory.

**Two caveats on the clean row**, both making it, if anything, optimistic:
(1) these runs use all names and a market-relative return; the registered
primary is CHAR_MATCHED on the tradeable names (participation cap), which is
fewer names; (2) the early quarters are thinner (1,366 names in 2018-Q1
against 2,079 in 2026-Q1). The registration-day dispersion check reruns the
number on the exact primary before the hash, as §8 of the v2 draft did.

## 4. The two versions, side by side

| | **Version A — capped** | **Version B — uncapped** |
|---|---|---|
| tail rule | Participation cap (as v2) **and** each stock's 63-session abnormal return clipped at the pooled 1st and 99th percentiles (today about −54% and +119%) before the decile spread | Participation cap only — every return counts in full (v2's rule exactly) |
| what it measures | "Do the stocks institutions bought beat those they sold, **for a typical stock**?" | "Do they beat them, **counting every crash and every multibagger in full**?" |
| power on the clean period | MDE 2.20% vs 1.50% → **1.47× short** | MDE 7.13% vs 1.50% → **4.76× short** |
| likely landing if registered now | UNDERPOWERED (kill 1), less badly | UNDERPOWERED (kill 1), clearly |
| when it could reach the bound | ~2.2× the clean quarters (§6): about 2032 with forward quarters | ~23× the clean quarters: not this decade |
| protects against | a few freak quarters (data glitches, illiquid spikes) deciding the answer | a rule that hides real extreme outcomes |
| costs | real huge moves count less than they were | the answer is hostage to a handful of names |
| standard in the literature | yes — 1/99 winsorisation is the common default | also used; less common for small-cap-heavy panels |
| changed from v2 | yes: a new rule, so it must be justified on its merits, not on power | no |

**Why the choice cannot be made on the power row.** Picking A *because* it is
nearer the bound would make the cap a knob turned toward an answer. The
choice has to rest on which question the owner thinks is the right one — the
"typical stock" question (A) or the "every rupee" question (B). Both are
legitimate. The v2 draft already argued the tail had to be chosen before any
signal was read (§3 there); the same holds here.

## 5. The frozen specification (what would be hashed)

Fields not listed are **identical to v2's registered row** (`exp_004_holdings_change_v2`,
spec `2b5811c1…`): engine, universe, entry, exit, cost, benchmark, revised and
interval policies, permutation policy, confounds, kill criteria 2-4.

| field | Version A | Version B |
|---|---|---|
| experiment_id | `exp_004_holdings_change_v3` | `exp_004_holdings_change_v3` |
| hypothesis | The top decile of filing-over-filing change in FPI, and separately in MF, holding — ranked within quarter — earns a higher CHAR_MATCHED abnormal return over the next 63 sessions than the bottom decile, after multiplicity, **on quarters 2016-Q2 to 2021-Q2** | same |
| prior_belief | Weak. v2's MF spread (+0.65%, CI [−0.31%, +1.86%]) and FPI spread (+0.77%) were positive but not significant on the later period; that is disclosed, and it is why this period is the test. The likeliest landing is UNDERPOWERED. | same |
| final_test_period | quarter-ends 2016-06-30 → 2021-06-30, each entered at the next open after its own broadcast; touched once | same |
| signal_definition | ΔFPI (`InstitutionsForeignPortfolioInvestorMember` in both BSE schemas; the three NSE taxonomies from 2021-09), ΔMF (`MutualFund`); percent, scale-normalised | same |
| test_count | 2 | 2 |
| multiple_testing_policy | BH-FDR 5% across the 2 tests; the family bar from `families.py` with trials_before 3 | same |
| **outcome_tail_rule** | **participation cap (₹100 cr book) AND outcome winsorised at the pooled 1st/99th percentiles of the test period, computed before ranking** | **participation cap (₹100 cr book); winsorised reported, never tested** |
| pass_bar | event gate (|spread| clears the serial-corrected MDE AND 1.50%/63 sessions at BH-FDR 5%) AND portfolio gate (net of costs) | same |
| kill_criteria | (1) MDE > bound → UNDERPOWERED; (2)-(4) as v2 | same |
| exploratory_prior_run | v2's registered result (decision 0076, `HOLDINGS_VERDICT.md`) on 2021-Q3 → 2026-Q2 — **the reason the test period excludes it**; `HOLDINGS_POWER_PRELIMINARY.md` dispersion runs, random deciles only | same |
| trials_before | 3 | 3 |
| family charge on the read | +2 → `TRACK_H_HOLDINGS` 5 | +2 → 5 |

## 6. Option C — wait, and keep the clean quarters clean

Every quarter that ends after v2's data date is also unread: its returns had
not matured when v2 ran. So the clean pool is the 21 past quarters **plus**
every new quarter from 2026-Q3 on, four a year. MDE falls roughly with the
square root of quarters:

| clean quarters | year reached | capped (A) | uncapped (B) |
|---:|---|---:|---:|
| 21 | now | 1.47× | 4.76× |
| 33 | ~2029 | ~1.17× | ~3.8× |
| 46 | ~2032 | ~0.99× | ~3.2× |

Waiting costs nothing in trials and keeps the 21 past quarters unread. The
yearly re-measure (`configs/remeasure.yml`) reports the number as it moves.

**Not on the table, and why:** testing MF alone (one test, a lower bar) would
add power, but MF is the signal v2 showed nearest to its bound. Choosing it
now would be choosing by a seen result.

## 7. What the owner decides

1. **Version A** (capped) — register now; most likely UNDERPOWERED at 1.47×; 2 trials charged.
2. **Version B** (uncapped) — register now; almost certainly UNDERPOWERED at 4.76×; 2 trials charged.
3. **Neither yet (Option C)** — register nothing; the clean pool grows; choose A or B when the number reaches the bound.

The choice between A and B can be made now and written down (a decision
record) without registering — that fixes the rule before any further number
is seen, and keeps the trials uncharged.

**My recommendation: 3, with the A/B rule chosen and recorded now.** Not
because of which version wins, but because a test whose own kill rule already
says "underpowered" spends two trials to learn nothing new.

## 8. On approval, in order

1. A decision record (0092) states the version chosen and, for A or B now, why.
2. `scripts/register_exp004.py` gains a v3 spec builder; check-only by default,
   `--rehearse` against a copy, `--register` typed only after "approve".
3. Registration-day dispersion check on the exact primary (CHAR_MATCHED,
   tradeable names, the chosen tail rule), clean period only. If it puts the
   MDE above the bound, the owner is told before the hash.
4. Only then: the one read, on 2016-Q2 → 2021-Q2.
