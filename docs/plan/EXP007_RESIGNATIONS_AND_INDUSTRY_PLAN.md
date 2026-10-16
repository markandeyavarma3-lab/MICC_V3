# Plan: a governance-resignation study (exp_007) and industry in the matched benchmark

**Status: PLAN, 2026-10-16.** Owner: "yeah lets do both, but think deep and do
proper research and then plan and then start doing things". Nothing here is
registered; registration needs the owner's explicit "approve" on a frozen spec.

## Part 1 — what the research found

### 1.1 The data (measured 2026-10-16)

- **NSE serves announcements back to at least 2014** (one week each of 2014,
  2016, 2019 and 2022 fetched: 536–1,357 filings a week). The archive held
  2023 onward; the 2014–2022 backfill is running.
- **NSE's own category is not stable over time.** "Resignation" holds about 1
  filing a week in 2014 and 2016 and 17–24 a week from 2019; earlier
  resignations were filed under "Change in Director(s)", "Updates" and others.
  From 2023 NSE added role categories ("Resignation of Independent director",
  "Resignation of Statutory Auditor", "Resignation of Director/KMP/SMP").
  **A study keyed on the category would measure NSE's taxonomy changing.** The
  event must be defined from the filing text, across all categories.
- **The text is regular:** "<Company> has informed the Exchange regarding
  Resignation of <name> as <role> w.e.f. <date>". The role is readable for
  most filings; "Resignation of Director/KMP/SMP" (~1,700 since 2023) names no
  role and is classed UNKNOWN, never guessed.
- **Power (event_power.py, 2023–2026 only, NSE's category):** resignations are
  POWERED at 63 sessions (MDE 1.34% vs 1.50%) and 1.29x short at 21. The
  governance subset is smaller and must be re-measured on the full backfill
  before a design is fixed (dispersion only, 0035).

### 1.2 What is known

- **Independent-director resignations, India:** about -1.3% cumulative
  abnormal return over the four days around the announcement in the wave after
  the Satyam fraud, larger for audit-committee members with business
  expertise (Chakrabarti, Subramanian & Tung, SSRN). Single governance cases
  are far larger (PTC India Financial Services -18% in a day, 2022; YES Bank
  -6%, 2018). A 2024 Indian study reports ID resignations up 45% in 2020 over
  2019.
- **CFO exits (secondary source, method unverified):** about -1% the next day
  and a further -2% over 30 days, recovering by about 180 days.
- **Statutory-auditor resignations:** SEBI circular CIR/CFD/CMD1/114/2019 (18
  October 2019) forces disclosure of the reasons — most often "non-
  cooperation" and "non-receipt of information". No published return study was
  found; this is a gap.

### 1.3 What that means for the design

This project enters at the **open of the session after the filing**, so the
announcement-day reaction — what the literature measures — is mostly already
in the price. The question a study here can ask is the **drift after it**:
does the market finish adjusting on day one, or does a governance-signal
resignation keep losing value over the next one to three months? That is the
pattern the CFO evidence hints at and the one disclosure-based investors would
care about. Routine resignations (company secretary, compliance officer,
chief information officer) carry no such story and dilute any effect, so they
are excluded by definition, before any return is read.

## Part 2 — the proposed study, exp_007 (a draft to argue with)

| field | proposal |
|---|---|
| question | After a listed company discloses the resignation of an independent director, its statutory auditor, or its CEO/MD/CFO, does its stock underperform comparable stocks over the following 63 sessions? |
| event | the first such resignation filed by a company in any 21-session window (clusters of several directors leaving together are one event), classified from the filing text by a frozen rule; UNKNOWN roles excluded |
| entry / exit | open of the session after the filing (the shared `measure._returns_sql`); 63 sessions primary, 21 reported |
| benchmark | CHAR_MATCHED (size x momentum x volatility), primary; CHAR_MATCHED_IND (Part 3) and NIFTY 500 TRI reported |
| direction | one-sided, negative — stated by the literature before any mean here |
| split | **EXPLORE 2014–2018**: subtype counts, power, rule debugging, means allowed and reported. **CONFIRM 2019 to the data date**: untouched until the read. The SEBI auditor circular (Oct 2019) falls inside CONFIRM, a known regime change, reported as a sensitivity |
| tests | primary: the pooled governance population at 63 sessions. Reported, not tested: each role alone, 21 sessions |
| family | a new family, TRACK_E_EVENTS (corporate-event disclosures), carried 0; one test |
| bar | t <= -1.645 one-sided on the monthly-cohort mean, serial-corrected (0033), AND mean <= -0.5% (a third of the 1.5% bound) |
| kill | the governance population is UNDERPOWERED at the 1.5% bound on CONFIRM (measured on EXPLORE dispersion before registration) |

Open for the owner before the hash: whether CFO/CEO belong in the pooled
primary or only as a reported subgroup; whether the split should be 2014–2018
/ 2019+ as proposed.

## Part 3 — industry in the matched benchmark

### 3.1 What was measured

The current CHAR_MATCHED sorts every stock into 5 x 5 x 5 = 125 cells; its
median cell holds 12 names and 83% of names sit in cells of at least 10.
Industry, from the fund-portfolio labels mapped onto NSE's 22 index sectors:

| construction | median cell | names in cells >= 10 |
|---|---:|---:|
| sector alone | 10 | 90% |
| sector x size (5) | 3 | 51% |
| sector x size (3) | 4 | 66% |
| sector x size x momentum | 1 | 8% |

**Industry cannot be a fourth intersecting dimension** — a 4-way cell holds one
name, and every match would fall down the ladder. The literature's DGTW uses
broad sectors for the same reason.

### 3.2 The proposal

- **CHAR_MATCHED is not changed.** Every quoted figure keeps its benchmark.
- A new benchmark, **CHAR_MATCHED_IND**: the event's return against stocks of
  the same NSE sector and size tercile where that cell holds >= 10 names; else
  the same sector; else the existing CHAR_MATCHED ladder. The rung used is
  recorded on every event, as now.
- Sector = the fund-portfolio industry label (point in time, from 2016-01)
  mapped onto NSE's sector by the majority of stocks the two sources share;
  rare unmatched labels mapped by hand and listed. Before 2016, and for names
  no covered fund holds, there is no sector and the ladder falls through —
  declared, never imputed.
- It enters exp_007 as a **reported sensitivity**, not the primary.

## Part 4 — the order of work

1. **Collect:** announcements 2014–2022 (running). Re-parse.
2. **Classify:** `src/research/resignations.py` — the frozen text rule, with
   tests built from real filings of every role; a table of counts by role and
   year.
3. **Measure power** on EXPLORE (2014–2018), dispersion only, for the pooled
   governance population and each role, at 21 and 63 sessions, market-relative
   and CHAR_MATCHED.
4. **Build CHAR_MATCHED_IND:** the label-to-sector map as a reviewed config
   file, the benchmark, its tests, its coverage by year.
5. **Explore** (2014–2018 only): means allowed, reported in full.
6. **Freeze the draft spec** with what 3–5 found; owner reviews; "approve"
   registers.

## Part 5 — what steps 1–3 found (2026-10-16), and a changed recommendation

- **Announcements 2014–2026 collected** (668 weekly windows, 1.41 M records).
  Governance resignations after de-clustering: auditor 465, CEO/MD 1,785, CFO
  1,793, independent director 4,265 (`docs/reports/EXP007_POWER.md`, by year).
- **Power, dispersion only, pooled governance population, CHAR_MATCHED:**

  | sample | months | 63 sessions | 21 sessions |
  |---|---:|---:|---:|
  | EXPLORE 2014–2018 | 60 | 1.60x short | 2.35x short |
  | CONFIRM 2019–2026 | 90 | **1.00x — at the bound** | 1.48x short |
  | FULL 2014–2026 | 150 | **0.88x — POWERED** | 1.26x short |

  Each role alone is 2–7x short; only the pooled population can be tested.
- **CHAR_MATCHED_IND** matches 26% of events at sector x size and 5% at sector;
  it changes the cohort SD by under 1% (5.74% vs 5.79%). Industry is a
  check on the benchmark's honesty here, not a power lever.

**The recommendation changes: no EXPLORE; one test on the whole 2014–2026
sample.** The plan split the data so a look at 2014–2018 could shape the
design. Nothing needs shaping from returns: the event (governance
resignation), its direction (negative drift) and its rule (the frozen text
classifier) come from the literature and the filings, and no mean has been
read for any period. Spending 2014–2018 on a look leaves CONFIRM exactly at
its bound, a coin flip; not looking leaves the whole sample powered.
`resignation_study.py explore` has NOT been run and should not be.
