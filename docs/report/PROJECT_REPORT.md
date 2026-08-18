# Institutional Behaviour Research Platform — Project Report

**Author:** Markandeya Varma
**Date:** 18 August 2026
**Repositories:** `MICC` (V1) · `MICCV2` (V2) · `institutional-research` (V3, current)

---

<!--TOC-->

---

## 1. Introduction

This report describes a research system I have been building since June 2026. The
system studies the Indian stock market. Its purpose is to find out whether the
buying and selling done by large institutions — mutual funds, foreign investors,
insurance companies — can tell us anything useful about where share prices go
next.

The project has gone through three versions in about eight weeks. This report
covers all three. It explains what each version did, what it produced, why the
first two were stopped, and what the current version is doing.

I want to say clearly at the start what the honest position is, because the rest
of the report only makes sense with this in view:

> **The system has not found a way to make money. Two versions have been built
> and stopped. The current version is about 15% built. The most likely outcome,
> based on everything measured so far, is that the answer is "there is no usable
> edge here" — and the project is now deliberately designed so that it can say
> that clearly instead of avoiding it.**

That may read like failure. I would argue it is the opposite. The first two
versions could not have told me they were failing, and that is why they ran for
eight weeks. The third version is built so that it can.

### 1.1 What the system actually does

Every day, the two Indian stock exchanges publish a list of large trades. When
somebody buys or sells more than 0.5% of a company's shares in one day, the
exchange must publish it: the date, the company, the name of the buyer or seller,
the quantity, and the price. This is public information. Anybody can download it.

The research question is simple to state:

> When a large institution buys a share, does that share do better than it
> otherwise would have? And if so, is the effect big enough and reliable enough
> to be worth acting on, after costs?

The question is simple. Getting a trustworthy answer is not, and most of this
report is about why.

### 1.2 Reading this report

All numbers in this report were measured from the actual repositories and data on
17–18 August 2026. Nothing is estimated. Where a number is uncertain I say so.
Git commit hashes are given so any claim can be checked.

---

## 2. Why I am building this

### 2.1 The personal reason

I want to learn how to do quantitative financial research properly. Not how to
build a trading bot — that is the easy and useless part — but how to tell the
difference between a real pattern and a coincidence. That distinction turns out
to be the entire subject.

### 2.2 The intellectual reason

Financial markets produce enormous amounts of data, and almost all patterns found
in that data are false. If you test ten thousand ideas against past prices, some
of them will look brilliant purely by chance. This is not a small problem or a
technicality. It is the central problem of the field.

The professional literature has developed real tools for this — pre-registration,
multiple-testing corrections, out-of-sample testing, power analysis. Most amateur
work ignores them completely, finds something that looks wonderful in a backtest,
and loses money. I wanted to build something that uses the real tools.

### 2.3 The specific reason this dataset

Bulk and block deal disclosures are unusually good for this kind of study for
three reasons:

1. **They are events with a date.** You know exactly when the information became
   public, so you can measure what happened afterwards without guessing.
2. **They are free and long.** India has published them since 2006. I have
   223,450 bulk deals and 12,430 block deals going back twenty years.
3. **There is a plausible story.** Large institutions have research departments.
   If anybody has an information advantage, they should. So there is a reason to
   expect an effect, rather than just data-mining and hoping.

Point 3 matters more than it looks. Searching data with no idea of what you are
looking for is how false discoveries are made. Having a reason in advance is what
separates research from fishing.

### 2.4 What I am not building

I want to be exact about this, because it affects the design:

- **No live trading.** No code that places orders exists anywhere in the current
  repository. There is an automated test that fails the build if anybody adds
  functions named `place_order`, `modify_order` or `cancel_order`.
- **No money is at risk.** Nothing is connected to a real trading account.
- **No product.** This is not a startup or a service. It is a research project.

---

## 3. The previous versions, and proof of work

Three versions exist. Two are stopped. All three are in Git, so the history below
can be independently verified.

### 3.1 Version 1 — MICC (28 June – 8 July 2026)

**Repository:** `~/Workspace/MICC`

| Measure | Value |
|---|---|
| Commits | 67 |
| Period | 28 June 2026 → 8 July 2026 (11 days) |
| Files | 191 |
| Python code | 118 files, 23,172 lines |
| Final commit | `e27991f` — *"Portable path layer + SHP backfill completion + verification hardening"* |

First and last commits:

```
2026-06-28  2af2cb1  Initial commit
2026-06-28  ce386d8  Clean data-extraction project: data_extraction/ + data_storage/
2026-06-28  5adf4bd  Fix all extractors: bootstrap, table creation, dead URLs, parquet export
...
2026-07-07  9cf8af0  Frontend: Portfolio page, idea-card lifecycle UI, resilience/a11y/perf + tests
2026-07-08  e27991f  Portable path layer + SHP backfill completion + verification hardening
```

**What V1 was for.** V1 was a data collection project. Its job was to gather
Indian market data from public sources and store it in a usable form. It did that
job, and it did it well.

**What V1 produced.** The lasting output of V1 is a dataset of **116 tables
containing 11,276,328 rows, totalling 1.2 GB**. This still exists, and the
current version is built on it. The largest tables:

| Table | Rows |
|---|---|
| `shp_institutional_summary` | 3,565,899 |
| `shp_promoter_group` | 2,526,543 |
| `window_extremes` | 1,087,140 |
| `shp_category_summary` | 892,410 |
| `pit_universe` | 359,047 |
| `features_monthly` | 343,963 |
| `insider_trading` | 283,281 |
| `bulk_deals` | 223,450 |
| `global_indices_daily` | 212,955 |

**Why V1 stopped.** It did not fail. It was replaced because it had grown into a
mixture of data collection, a web frontend and analysis, all in one codebase,
with no clear separation. Rather than untangle it, I started V2 and carried the
data across. **This was a reasonable decision and the data has proved its value —
it is irreplaceable, because the exchanges do not serve twenty years of history
on request.**

### 3.2 Version 2 — MICCV2 (11 July – 13 August 2026)

**Repository:** `~/Workspace/MICCV2` · **Frozen at tag** `frozen-2026-08-16`

| Measure | Value |
|---|---|
| Commits | 107 |
| Period | 11 July 2026 → 13 August 2026 (34 days) |
| Files | 411 |
| Python code | 204 files, 35,762 lines |
| Tests | 45 files, 375 test functions |
| Reports generated | 136 |

**What V2 was for.** V2 was an attempt to build a complete research and paper
trading system: data warehouse, signal engines, a strategy factory that would
generate and test candidate strategies automatically, a portfolio simulator, and
a dashboard.

**The engineering was good.** This is worth stating plainly. V2 has a real data
warehouse, working data collection, 375 automated tests, and a discipline of
generating verification reports. As a piece of software engineering it is
competent work.

**The research produced nothing.** This is also worth stating plainly.

The strategy factory generated and tested candidate strategies for about five
weeks. The number promoted to live use was **zero**. This is not my
interpretation — the phrase "0 promotions" appears in **18 separate
automatically-generated verdict reports** in the repository.

The final scorecard, from `reports/p7_verdict_2026-08-15.md`:

| Metric | Portfolio | Nifty 500 TR | NIFTY 50 |
|---|---|---|---|
| Sharpe ratio | **1.10** | 0.67 | 0.39 |
| CAGR | 8.1% | 9.2% | 4.6% |
| Volatility | 7.4% | 14.9% | 13.7% |
| Max drawdown | −7.9% | −18.5% | −15.8% |

The system's own pass mark was a Sharpe ratio of 1.3. It scored 1.10. Its own
report calls this **"BELOW FLOOR"**.

Worse, and to the credit of whoever wrote that report, it says so itself:

> *"Of 648 book days, 624 are REPLAY (backtest of the champion) and 24 are inside
> the live-forward window. Of those 24 live-window days, only 9 were CAPTURED
> LIVE."*

So the 1.10 Sharpe is mostly a backtest, and the live evidence is 9 days.

**Why V2 was stopped.** Three reasons, all found during an audit in August 2026.

**Reason 1 — the cost model was wrong.** V2 calculated trading costs incorrectly
in four separate ways: it charged Securities Transaction Tax on one side of a
trade instead of both, used the wrong exchange transaction rate, and applied GST
to the wrong base. Total understatement: **10.04 basis points per round trip.**

This is not a rounding error. V2's best seasonal finding, a "turn of month"
effect, showed **+3.70 basis points** of profit. With the costs corrected it
becomes **−6.36 basis points** — a loss. The system's headline finding was an
artefact of its own accounting mistake.

**Reason 2 — it could not fail.** V2 recorded 22 killed ideas and zero
promotions, over about two years of accumulated development effort, and never
once concluded that the whole approach might not work. There was no rule anywhere
that could stop the project. A system that can only ever say "keep going" is not
performing a test.

**Reason 3 — documentation had drifted from reality.** V2's README described an
automated schedule that no longer matched the actual schedule on the machine.
Nothing checked, so nobody knew.

**The V2 audit is itself part of the work.** Finding these three things took
several days and required reading the whole system. That audit is why V3 exists
and why V3 is designed the way it is.

### 3.3 Version 3 — institutional-research (16 August 2026 – present)

**Repository:** `~/Workspace/institutional-research`

| Measure | Value |
|---|---|
| Commits | 10 |
| Period | 16 August 2026 → present |
| Python code | 3,316 lines |
| Tests | 146, all passing |
| Decision records | 18 |

V3 is deliberately much smaller than V2 and does much less. It is described in
the rest of this report.

### 3.4 Summary of the three versions

| | V1 | V2 | V3 |
|---|---|---|---|
| Duration | 11 days | 34 days | ongoing |
| Commits | 67 | 107 | 10 |
| Lines of Python | 23,172 | 35,762 | 3,316 |
| Tests | — | 375 | 146 |
| Main output | 11.3M rows of data | 136 reports, 0 promotions | discipline framework |
| Status | superseded | frozen | active |
| Honest verdict | **succeeded at its job** | **engineering good, research empty** | **too early to say** |

---

## 4. The complete action plan

The plan for V3 is written in three documents totalling about 100,000 characters
(`docs/plan/PLAN_1_FOUNDATIONS.md`, `PLAN_2_METHODOLOGY.md`,
`PLAN_3_EXECUTION.md`). This section summarises it.

### 4.1 The core idea

The plan is built around one insight from the V2 audit: **the hard part is not
finding patterns, it is not being fooled by them.** So the system is built
discipline-first. The rules that stop self-deception were built before the
research code, not after.

### 4.2 The eight phases

| Phase | What it does | Status |
|---|---|---|
| **0** | Audit V2, freeze it, decide what to carry forward | **done** |
| **0.5** | Test whether data sources actually work | **done** |
| **1** | Foundations: paths, hashing, migrations, discipline framework | **done** |
| **2** | Data collection: daily automated capture of new deals | **partly done** |
| **3** | Identity layer: match company names to companies | not started |
| **4** | Outcomes: calculate what happened after each deal | not started |
| **5** | Benchmarks: compare against similar companies | not started |
| **6** | The four studies | not started |
| **7** | Seasonality rescan | not started |
| **8** | Reporting | not started |

### 4.3 Two tracks

The project runs two research tracks in parallel. They share the discipline
machinery — registration, decision records, multiple-testing correction — and
almost nothing else, because the statistics of an event and the statistics of a
calendar pattern are genuinely different.

| | **Track D — institutional deals** | **Track S — mass pattern search** |
|---|---|---|
| Question | do disclosed institutional trades predict returns? | do *any* patterns, found by searching, survive out of sample? |
| Data | 223,450 bulk + 12,430 block deals | 21 years of prices, 4,200 stocks |
| Unit | one deal event | one calendar cell or signal combination |
| Machinery | **built** | **not built** |

**Track S was under-specified until 18 August.** It existed in configuration
files and prose but had no code and no proper design.

Worse, when the two tracks were finally checked against each other, they had
never been connected. Three faults, each of which would only have appeared once
scan code ran:

1. The search track had **no held-back data at all**, while the deal track sat
   behind a guard that refuses access.
2. A search study **could not be registered** — the checklist of required
   controls covered the deal track and left the search track, which has far more
   opportunity to fool itself, with none.
3. Two configuration files disagreed about how attempts are counted. Read
   literally, running the search once would have **raised the deal track's
   evidence bar so high that its one completed experiment would retroactively
   have failed** — and no future deal study could ever have passed.

All three are fixed. Attempts are now counted per research family rather than in
one pool, so a search charges its own budget and not another track's; the search
track has its own held-back period (2016 onward); and search studies face five
required controls of their own. A fourth fault was found inside that fix — the
new counters were declared permanent and nothing actually incremented them, which
is the same defect the whole scheme exists to prevent, one level up.

### 4.3.1 Track D — the four deal studies

The deal track comes down to four questions.

**Study 1 — Do institutional buys predict anything?**
When an institution buys, does the share beat comparable shares over the next
1, 2, 3, 5, 10 or 21 trading days?

**Study 2 — Do institutional sells predict anything?**
The same question for selling. There is a reason to think selling is more
informative: institutions buy for many reasons (money coming in, index tracking,
rebalancing) but sell for fewer. 34,270 sell events have never been examined.

**Study 3 — Does agreement between institutions mean more?**
When three or more different institutions buy the same share within 21 days, is
that stronger than one institution buying? 10,098 such events exist.

### 4.3.2 Track S — the search track

V2 scanned **31,893,556** calendar patterns and concluded the best one sat at the
94th percentile of random noise — it looked like nothing. But it only ever asked
*"is this better than chance in this sample?"*, never *"does it happen again?"*

Track S asks the second question, using expanding training windows: find a
pattern in 2005–2010, require it to repeat in 2010–2012, and so on across many
folds.

**The headline result is deliberately not a list of patterns.** It is a measured
answer to: *across all folds, how often does a pattern chosen in training
actually win in testing?* If the answer is about 50%, mass searching does not
work on this data — which is a real and useful finding, and the most likely one.
Individual surviving patterns are reported second.

That reframing matters because it turns the enormous size of the search from a
liability into an instrument: the wider you search, the more precisely you
measure how badly searching overfits.

### 4.4 The rules every study must follow

These are the heart of the plan.

**Rule 1 — Write down the answer you will accept, before you look.**
Before a study runs, its hypothesis, method, and pass mark are written to a
database and locked. A database trigger physically refuses to let them be
changed afterwards. This is verified by trying to change one and being blocked.

**Rule 2 — Exploring must be free.**
The data is split into three parts: 30% for free exploration, 20% for choosing
between candidates, 50% for final confirmation. You may look at the exploration
part as much as you like at no cost. The confirmation part may be used once per
registered study, enforced by code that raises an error.

**Rule 3 — Count everything you looked at.**
If you test 171 ideas, the best one will look good by luck alone. The system
calculates how good: with 171 attempts, pure noise produces a best result of
about t = 2.94, so the bar is set at t = 3.71. With 31.9 million attempts the bar
rises past t = 7, and for patterns measured on few observations it rises further
still. These figures were themselves corrected on 18 August — see §7.6.

**Rule 4 — Check the same list of confusions every time.**
Ten standard alternative explanations are checked automatically for every study.
Any that do not apply must be dismissed in writing.

**Rule 5 — An event study is not a strategy test.**
A finding must pass two separate gates: does the event move prices, *and* does an
actual portfolio built on it beat the same portfolio without it, after costs.
Section 7.3 explains why this rule exists.

**Rule 6 — The project can be abandoned.**
If three of the four studies fail, or if nothing has passed by 28 February 2027,
the conclusion is written up as a negative result and the project stops.

---

## 5. The data warehouse

### 5.1 Design principles

**Raw data is never changed or deleted.** Files are downloaded, hashed, stored
compressed, and never touched again. If a file is understood wrongly, it can be
re-read later. V2 stored nothing raw and had 1.2 GB of data it could not re-derive.

**Every day not collected is lost forever.** The exchange publishes today's deals
at one web address, and replaces it tomorrow. The historical service returns an
error. So collection is time-critical: about 27 trading days are already
permanently missing.

**Derived data can always be rebuilt.** Anything computed from raw data can be
deleted and regenerated. Only the raw layer is precious.

### 5.2 The layers

```mermaid
flowchart TB
  subgraph EXT["EXTERNAL SOURCES"]
    direction LR
    NSE["NSE archive<br/>bulk.csv / block.csv<br/><b>WORKS</b> — rolling daily"]
    NSEH["NSE historical API<br/><b>BLOCKED</b> — HTTP 503"]
    BSE["BSE deals API<br/><b>BLOCKED</b> — HTTP 301"]
  end

  subgraph RAW["LAYER 1 — RAW ARCHIVE (never modified)"]
    direction LR
    SEED["<b>V1 seed</b><br/>116 tables · 11,276,328 rows · 1.2 GB<br/>2005–2026 · irreplaceable"]
    ARCH["<b>Daily archive</b><br/>gzip + SHA-256 + manifest<br/>write-once, deduplicated"]
  end

  subgraph MART["LAYER 2 — MARTS (rebuildable)"]
    direction LR
    SEC["security_master<br/>symbol_history<br/>sector_history"]
    DEAL["institutional_deals<br/>raw → clean"]
    OUT["deal_forward_outcomes<br/>what happened after"]
    SEAS["seasonality_cell"]
  end

  subgraph GOV["LAYER 3 — GOVERNANCE (append-only, SQLite)"]
    direction LR
    REG["experiment_registry<br/><i>locked by trigger</i>"]
    RES["study_result"]
    DAG["artefact + artefact_edge<br/><i>provenance graph</i>"]
    TC["trial_counter"]
  end

  NSE -->|"daily 20:00 IST"| ARCH
  NSEH -.->|blocked| ARCH
  BSE -.->|blocked| ARCH
  SEED --> SEC
  ARCH --> DEAL
  SEED --> DEAL
  SEC --> DEAL
  DEAL --> OUT
  SEED --> SEAS
  OUT --> RES
  SEAS --> RES
  REG --> RES
  RES --> DAG

  classDef ok fill:#dcfce7,stroke:#16a34a,stroke-width:2px
  classDef bad fill:#fee2e2,stroke:#dc2626,stroke-width:2px
  classDef todo fill:#fef9c3,stroke:#ca8a04,stroke-width:2px
  classDef done fill:#dbeafe,stroke:#2563eb,stroke-width:2px
  class NSE,SEED,ARCH ok
  class NSEH,BSE bad
  class SEC,DEAL,OUT,SEAS todo
  class REG,RES,DAG,TC done
```

**Legend.** Green = working. Red = blocked. Blue = built. Yellow = designed but
not yet built.

### 5.3 Honest status of the warehouse

| Layer | Designed | Built | Note |
|---|---|---|---|
| Raw archive | yes | **yes** | 3 files captured so far; 16 KB |
| V1 seed carried across | yes | **no** | still sits in the V2 folder, not copied |
| Marts | yes | **no** | 0 of 7 tables exist as real schemas |
| Governance | yes | **yes** | 9 tables, live and enforcing |

**The marts are the gap.** Seven tables are described in the plan in detail, with
column lists and constraints, but none of them has been created. They exist as
prose in a document, not as a database.

### 5.4 Two data problems found by measurement

These were found on 17 August 2026 by running real queries. Both are serious and
neither was in the plan.

**Problem 1 — one third of deals cannot be matched to a price.**

Of 25,097 institutional buy events, only 16,517 could be linked to price data:

| Reason | Events | Share |
|---|---|---|
| Company not in the price database at all | 5,080 | 20.2% |
| Deal happened before price coverage begins | 1,808 | 7.2% |
| Deal happened after price coverage ends | 83 | 0.3% |
| Price data exists but not for that exact day | 1,609 | 6.4% |
| **Successfully matched** | **16,517** | **65.8%** |

The plan sets a 5% limit for unmatched records. The reality is 34.2% — seven
times over. Every result computed so far uses only the surviving two thirds.

**Problem 2 — there is no historical industry classification.**

The plan's main method for fair comparison requires knowing what industry a
company was in at the time of the deal. The only industry data available covers
**1,415 companies out of 4,200 (33.7%)**, and it is a single snapshot taken
between 30 June and 2 July 2026. Applying 2026 industry labels to a 2005 event
means using information that did not exist yet — the exact error the whole
project is designed to avoid.

**This is currently an unsolved problem, not a task.** I do not have a source for
it.

---

## 6. The system architecture

### 6.1 Overview

```mermaid
flowchart TB
  subgraph COLLECT["1 · COLLECTION"]
    direction LR
    C1["stopgap.py<br/><b>BUILT</b><br/>fetch → hash → store"]
    C2["full collector<br/><i>not built</i><br/>parse · holidays · retries"]
    CRON["cron<br/>20:00 · 22:30 · 08:00 IST"]
  end

  subgraph STORE["2 · RAW STORAGE"]
    direction LR
    S1["raw archive<br/><b>BUILT</b><br/>write-once + SHA-256"]
    SEEDN["V1 seed<br/>11.3M rows"]
  end

  subgraph IDENT["3 · IDENTITY"]
    direction LR
    I1["name → company<br/><i>not built</i><br/>34.2% currently unmatched"]
    I2["HFT detection<br/><i>not built</i><br/>rule: ≥95% same-day"]
  end

  subgraph MARTS["4 · MARTS"]
    direction LR
    S2["DuckDB marts<br/><i>not built</i><br/>0 of 7 tables"]
  end

  subgraph GOVN["GOVERNANCE (side-car)"]
    S3["SQLite governance<br/><b>BUILT</b><br/>append-only + triggers"]
  end

  subgraph RESEARCH["5 · RESEARCH ENGINE"]
    direction LR
    R1["power.py<br/><b>BUILT</b><br/>can we even see it?"]
    R2["split.py<br/><b>BUILT</b><br/>explore / select / confirm"]
    R3["multiplicity.py<br/><b>BUILT</b><br/>how much did we look?"]
    R4["design.py<br/><b>BUILT</b><br/>is this study allowed?"]
  end

  subgraph GATES["6 · THE TWO GATES"]
    direction LR
    G1["EVENT GATE<br/>does it move prices?"]
    G2["PORTFOLIO GATE<br/>does a real book<br/>beat the same book<br/>without it?"]
  end

  subgraph OUT["7 · OUTPUT"]
    direction LR
    O1["PASS · FAIL<br/>UNDERPOWERED"]
    O2["decision record<br/>+ provenance"]
    O3["FINAL_VERDICT.md<br/>if project is killed"]
  end

  CRON --> C1 --> S1
  C2 -.-> S1
  S1 --> I1
  SEEDN --> I1
  I1 --> I2 --> S2
  S2 --> R1
  R2 --> R4
  R3 --> R4
  R1 --> R4
  R4 -->|"design approved"| G1
  G1 -->|"passes"| G2
  G1 -->|"fails"| O1
  G2 --> O1 --> O2
  S3 -.->|"locks specs"| R4
  O2 -.->|"writes back"| S3
  O2 -.-> O3

  classDef built fill:#dbeafe,stroke:#2563eb,stroke-width:2px
  classDef notbuilt fill:#fef9c3,stroke:#ca8a04,stroke-width:2px,stroke-dasharray:4 3
  classDef gate fill:#fce7f3,stroke:#db2777,stroke-width:2px
  classDef seed fill:#dcfce7,stroke:#16a34a,stroke-width:2px
  class C1,S1,S3,R1,R2,R3,R4 built
  class C2,S2,I1,I2 notbuilt
  class G1,G2 gate
  class SEEDN seed
```

### 6.2 How a study flows through the system

```mermaid
sequenceDiagram
  participant A as Researcher
  participant D as design.py
  participant G as governance DB
  participant S as split.py
  participant P as power.py
  participant R as Result

  A->>D: propose a study
  D->>D: has it a mechanism?
  D->>D: a prediction that could fail?
  D->>P: what is the smallest<br/>effect we could detect?
  P-->>D: MDE per horizon
  D->>D: are ALL horizons blind?
  Note over D: refuse if yes
  D-->>A: design accepted
  A->>G: register + lock spec
  G-->>A: spec_hash frozen
  A->>S: read EXPLORE data
  Note over S: free · uncharged
  A->>S: read CONFIRM data
  S->>S: registered? used before?
  S-->>A: allowed once only
  A->>R: event gate
  R->>R: portfolio gate
  R->>G: write result + trial count
  Note over G: append-only
```

### 6.3 Why the architecture looks like this

Each part exists because of a specific V2 failure.

| Component | The V2 failure it prevents |
|---|---|
| Explicit environment (`paths.py`) | V2's checker defaulted to "dev", failed there, and rebuilt the *production* warehouse while reporting on dev |
| Read-only snapshots | V2 served its dashboard from the live database; 7 of 12 pages returned errors whenever anything was writing |
| Write-once raw archive | V2's raw folders were all zero bytes — data went straight into the warehouse and could not be re-derived |
| Locked experiment specs | V2 could not tell a prediction from an explanation made afterwards |
| Trial counter that sets bars | V2 counted attempts and never used the count for anything |
| Two gates | V2 had no portfolio test at all, so a finding could pass on event evidence alone |
| Documentation drift test | V2's README described a schedule that had changed |
| Provenance graph | V2 could not answer "which numbers came from this data?" |

---

## 7. What is completed

### 7.1 The discipline framework — complete and working

This is the substantial achievement so far. 146 automated tests, all passing.

**Power analysis (`power.py`, 311 lines).** Answers "could this study have seen
the effect even if it were there?" before running. If the answer is no, the
verdict is UNDERPOWERED — reported as *silence*, not as evidence of absence.
This distinction did not exist in V2.

**Data split (`split.py`, 237 lines).** Divides companies into three groups by a
mathematical hash of their ISIN code. Exploration is free; confirmation is
enforced by code that raises an error.

The choice of ISIN rather than company symbol was driven by measurement:

| Finding | Value |
|---|---|
| ISINs with more than one symbol over time | 276 |
| Those symbols appearing in deal data | 459 |
| Deal records affected | 26,046 (**11.04%**) |

Real examples: `CADILAHC` became `ZYDUSLIFE`; `PRISMCEM` became `PRSMJOHNSN`. If
the split used symbols, those companies would sit in the exploration group under
one name and the confirmation group under the other — contaminating the
confirmation set for 11% of the data, with nothing looking wrong in any output.

**Multiple testing (`multiplicity.py`, 186 lines).** Converts "how many things did
we try" into a required standard of evidence:

| Attempts | Best result from pure noise | Required standard |
|---|---|---|
| 10 | t = 1.90 | t = 2.80 |
| 171 | t = 2.94 | **t = 3.71** |
| 1,000 | t = 3.45 | t = 4.31 |
| 31,893,556 | t = 5.63 | **t = 7.04** |

*(Corrected 18 August. The figures first published were lower — see §7.6.)*

**Design gate (`design.py`, 275 lines).** Refuses to let a study exist unless it
has a mechanism, a prediction that could fail, computed detectability, and a plan
for all ten standard confusions.

The test that proves this is worth having is that **it rejects the project's own
first experiment.** More on that in 7.3.

### 7.2 Documentation that cannot silently rot

Eighteen decision records, each recording what was decided, by whom, why, **what
would reverse it**, and what it costs. An automated test fails the build if any
record is missing those fields.

A second test compares the plan documents against the configuration files. On its
first run it found three real errors: the plan still advertised abandoned time
horizons, never mentioned the portfolio gate, and never mentioned the data split.
All three were fixed.

### 7.3 A completed experiment, and why it matters

One full experiment has been run start to finish: `exp_001`.

**The hypothesis.** A portfolio of the largest 500 Indian companies which
*avoids* any company that had an institutional buy in the last 10 trading days
will do better than the same portfolio without that rule.

**The sequence, which is the point.** The prediction and the pass mark were
written to the database and locked in commit `f25608d`. The test was run
afterwards. The result was recorded in commit `c31e128`. **The registration is
earlier in the Git history than the result**, so it cannot have been written to
fit the answer.

**What happened at the event level.** The effect was real and survived three
attempts to kill it:

| Check | Result |
|---|---|
| vs random companies, same dates | −0.860% specific to the event |
| vs companies of similar volatility | **−0.805%, t = −3.93** |
| Is it just price reversal? | No — correlation +0.008, pattern not monotonic |

**What happened at the portfolio level.**

| Half of the data | Annual difference | t | Verdict |
|---|---|---|---|
| First half | +0.237% | +3.11 | FAIL |
| Held-back half | **−0.022%** | **−0.25** | FAIL |

**Why it died.** The rule only excluded **1.2% of companies** at any time. A
−0.8% effect applied to 1.2% of a portfolio is about one basis point a month —
nothing.

**This is the most valuable thing learned so far.** Every statistic in the event
study was correct and pointed the same way. The study was still useless. Only
building the actual portfolio revealed it. **An event study is not a strategy
test**, and the gap between them is not a technicality.

Under V2's design this would have been recorded as a success.

### 7.4 A measurement that corrected me

On 17 August I stated that all the project's detectability calculations were too
optimistic because they treated companies as independent. **This was wrong**, and
I found it wrong within hours by measuring it:

| Method | Detectable effect |
|---|---|
| Treating 16,445 events as independent | 0.076% ← never actually done |
| What the code actually does (monthly grouping) | 0.621% |
| With the correction that *was* missing | **0.660%** |

The eight-fold penalty was already being applied. The real gap was a different
and smaller one — correlation between months, worth 6–27%, not a factor of three.

This is recorded in decision record 0017 rather than quietly edited out. I include
it here because a report that only lists successes is not a report.

### 7.5 Daily data capture — running

A collector runs automatically at 20:00, 22:30 and 08:00 IST. On its first night
it captured 100 bulk deals and 4 block deals, verified by hash. Files are
compressed, hashed, never overwritten, and duplicates are detected.

### 7.6 Four errors of my own, found by verification

On 18 August I was asked simply *"are you sure about the whole thing?"* Checking
found four errors in work committed within the previous day. I record them
because a report listing only successes is not a report, and because how they
were found matters more than that they existed.

**Error 1 — a statistic that measured itself.** I reported that removing the
market's overall movement from returns made stocks statistically independent, and
built a design on it. In fact the calculation I used *forces* that answer no
matter what the data contains. Feeding it a strongly-linked dataset and a
completely random one produced the same result. It measured the arithmetic of the
operation, not the market.

**Error 2 — a question with no possible answer.** Worse, the way I had defined
"market-relative" meant that the quantity I proposed to study is exactly zero for
every day by construction. I had designed a measurement incapable of producing a
number. The correct approach — comparing *rankings* of stocks rather than their
average — was in the plan as one option among several. It is in fact the only
one.

**Errors 3 and 4 — the significance bar was too low, twice.** The tool that sets
how strong evidence must be had two independent faults, and both made results
*easier* to pass:

| Fault | Effect |
|---|---|
| Measured one direction of movement while being applied to both | every bar understated |
| Assumed a bell curve where the true distribution has heavier tails | a further 23% understatement for small samples |

Corrected, the bar for the deal track rises from t = 3.62 to **t = 3.71**. The
one completed experiment still clears it, so **no recorded verdict changes.**

**Why they survived 146 tests.** The tests compared the tool against *its own
output*, pinned as expected values. A test asserting that code agrees with itself
proves nothing. The replacement tests compare against independent simulation,
which is the standard the originals should have met.

**What this says about the project.** The framework caught none of these — a
person asking a direct question did. The safeguards are real and they are not
sufficient, and I would rather state that than present a system that appears to
police itself.

---

## 8. What is going on now

### 8.1 Measuring whether there is anything to find

The current activity is establishing what size of effect this data can possibly
reveal. Results from 17 August, on 16,445 real institutional buy events:

| Horizon | Observed effect | Smallest detectable | Conclusion |
|---|---|---|---|
| 1 session | **+0.691%** | 0.191% | detectable |
| 5 sessions | −0.010% | 0.423% | nothing |
| 10 sessions | −0.603% | 0.660% | **below the floor** |
| 21 sessions | **−1.061%** | 0.968% | detectable but implausibly large |

**Two things stand out.**

**The sign flips.** Shares rise 0.691% on the first day, then fall, ending
1.061% down after 21 days. This is the classic signature of a temporary price
push that then reverses — consistent with the finding that **54.8% of bulk deals
are the same party buying and selling on the same day**, which is market-making
activity, not investment.

**The earlier finding weakens.** The 10-session effect of −0.603% is *smaller*
than the 0.660% we can reliably detect. The −0.805% found in `exp_001` came from
comparing against companies of similar volatility, and it was that tighter
comparison that provided the sensitivity — not the effect being robust to any
comparison.

### 8.2 An unresolved question that affects everything

The system judges whether a study is worth running by comparing what it can
detect against what size of effect is realistic. That threshold is currently a
single number — 0.5% per month.

**The problem:** this number is compared against every time horizon, but it is
only dimensionally correct at about 21 sessions. Comparing a one-day result
against a monthly threshold is a units error.

The fix depends on an unanswered question about how the effect should behave:

- **If a disclosure causes a single one-off price adjustment**, a fixed threshold
  is right and the table above stands.
- **If institutions have persistent skill that accrues over time**, the threshold
  must scale with the horizon — and then **every row in the table becomes
  undetectable**, including the two marked otherwise.

This is recorded as open decision 0018. **Until it is resolved, no result in this
project should be quoted as final.** It is the single most important open item.

---

## 9. What is pending

### 9.1 Build status, measured

| Component | Status |
|---|---|
| Environment, paths, hashing, migrations | **built** |
| Discipline framework | **built** |
| Daily capture (basic) | **built** |
| Trading calendar | not built |
| V1 data copied into the project | **not done** |
| Reconciliation check | **never run** |
| Full collector | not built |
| Company identity matching | not built |
| Institution name normalisation | not built |
| Outcome calculation | not built |
| Cost model in code | config only |
| Benchmark construction | config only |
| The four deal studies (Track D) | not built |
| **Track S — walk-forward folds** | **not built** |
| **Track S — calendar scan** | **not built** |
| **Track S — signal combinations** | **not built** |
| **Track S — the procedure test** | **not built** |
| Provenance graph populated | **0 rows** |

**Seven of seven core data tables do not exist, and all seven Track S modules
are unwritten.** The project folder currently
holds 16 KB of data.

**About 15% of the system is built**, and the completed portion is the framework
rather than the research machinery.

### 9.2 Three things in the plan that cannot be built as written

**1. No historical industry data (Section 5.4).** The plan's main comparison
method needs it. It covers 33.7% of companies and is a single 2026 snapshot.
There is no known source. **This is a genuine blocker, not a task.**

**2. Company matching is unspecified.** The plan sets a 5% limit and gives no
method for reaching it. Measured reality is 34.2%.

**3. The seasonality rescan has no time estimate.** "About three weeks" is an
assertion; no single unit of the calculation has ever been timed, and a later
decision roughly quadrupled the work.

### 9.3 Risks

| Risk | Status |
|---|---|
| **No backup of any kind** | **open** — no remote repository, no external drive. Captured trading days cannot be re-obtained at any price |
| Data lost each uncollected day | reduced — collector now runs, but ~27 days already lost |
| BSE data unavailable | open — all routes return errors |
| Historical backfill impossible | open — service returns error 503 |
| No detectable effect exists | **the most likely outcome** |

### 9.4 Timeline

| Date | Milestone |
|---|---|
| 30 November 2026 | Checkpoint — if no study has reached even the first gate, stop early |
| 28 February 2027 | Deadline — if nothing has passed, write the negative result and stop |

---

## 10. What this is currently used for

I want to be accurate here rather than flattering.

### 10.1 What it is used for today

**Nothing financial.** No money is invested. No orders are placed. No
recommendations are produced.

The system currently has three real uses:

1. **Daily data capture.** It is preserving Indian institutional deal data that
   would otherwise be permanently lost. This has value regardless of whether the
   research succeeds.
2. **A method for testing ideas honestly.** The framework — pre-registration,
   split data, multiple-testing correction, two gates — is general. It applies to
   any field where you search data for patterns.
3. **Learning.** I now understand why most quantitative research fails, because
   I have made the mistakes and measured them.

### 10.2 What it is not used for

- Not trading, and not connected to any account
- Not advising anyone
- Not producing predictions
- Not producing any validated finding — **zero results have passed both gates**

### 10.3 What it could be used for if it works

If a study passes both gates and survives the deadline, the output would be a
documented, reproducible finding about Indian institutional behaviour, with its
provenance recorded. Whether that would be worth trading is a separate question
requiring capital, execution and risk management that do not exist here.

**Based on the evidence so far I would put the probability of a tradable finding
below 20%.** The signals point the wrong way: the effect reverses across
horizons, most bulk-deal activity is market-making rather than investment, the
one completed experiment failed, and the detectability question in Section 8.2
may render the whole range unusable.

### 10.4 The most likely honest outcome

The most likely result is a well-documented negative: *public institutional deal
disclosure in India does not contain a tradable edge for a retail participant
after realistic costs.*

That is a legitimate result. It is also unpublishable in most amateur settings,
which is precisely why so much amateur work reports positives.

---

## 11. Conclusion

### 11.1 What has been achieved

In roughly eight weeks I have built three versions of a market research system,
audited two of them to destruction, and produced:

- A dataset of 11.3 million rows spanning 2005–2026, still in use
- A working data warehouse and collection system (V2), now frozen
- A discipline framework with 222 tests that enforces honest research
- One complete experiment, correctly rejected by its own pre-registered rule
- Eighteen decision records with reversal conditions
- Four material measurements that changed the plan: a 10.04 bp cost error, 54.8%
  market-making contamination, a 34.2% matching failure, and a missing industry
  history

### 11.2 What has not been achieved

- **No validated finding.** Zero results have passed both gates.
- **No profitable strategy.** V2 promoted zero strategies in five weeks.
- **The V3 system is ~15% built.** No core data table exists.
- **Two plan components have no data source.**
- **One critical question is unresolved** and may invalidate every current result.

### 11.3 The honest assessment

If this project is judged on "did you find a way to beat the market", the answer
is no, and probably will remain no.

If it is judged on "did you build something that can tell the difference between a
real finding and a lucky one", the answer is yes, and that is the harder problem.

The difference between V2 and V3 is not sophistication — V2 has ten times the
code. It is that V2 could not fail and V3 can. V2 ran for five weeks producing
zero promotions and never concluded anything was wrong. V3 has a written rule
that stops the project on 28 February 2027 if nothing works, and a first
experiment that was killed by its own pre-registered standard within ninety
minutes of looking promising.

### 11.4 What I have learned

**Most patterns in financial data are false.** With 171 attempts, noise alone
produces a t-statistic of 2.94 — which most people would report as highly
significant.

**Being able to fail is a feature.** V2's real defect was not any single bug. It
was that no possible result would have caused it to stop.

**Statistics that are individually correct can be collectively useless.**
`exp_001`'s event study was correct in every particular and the strategy was
worthless, because the rule touched 1.2% of the portfolio.

**Measurement beats assumption, including about yourself.** Four significant
errors were found by measuring rather than reasoning — including one of my own,
made and corrected within hours on 17 August.

### 11.5 Next steps

1. **Answer the detectability question** (decision 0018) — one judgement, gates
   everything else
2. **Copy the data in and run the reconciliation check** — nothing can be trusted
   until it passes
3. **Establish whether the industry-history problem is solvable** — if not, the
   comparison method must change
4. **Arrange a backup** — currently a single disk failure loses irreplaceable data
5. **Then, and only then, run Study 2** — 34,270 institutional sell events,
   never examined

---

## Appendix A — How to verify this report

```bash
# Version 1
cd ~/Workspace/MICC && git rev-list --count HEAD          # 67
git log --reverse --format='%ad %h %s' --date=short | head -1

# Version 2
cd ~/Workspace/MICCV2 && git rev-list --count HEAD        # 107
git tag                                                   # frozen-2026-08-16
grep -l "0 promotions" reports/*.md | wc -l               # 18
sed -n '1,30p' reports/p7_verdict_2026-08-15.md

# Version 3
cd ~/Workspace/institutional-research
RESEARCH_ENV=dev python -m pytest tests/ -q               # 146 passed
git log --oneline
ls docs/decisions/                                        # 18 records

# The pre-registration ordering — registration BEFORE result
git log --oneline --reverse | grep -E "f25608d|c31e128"
```

## Appendix B — Key files

| File | Purpose |
|---|---|
| `src/research/power.py` | Can this study see anything? |
| `src/research/split.py` | Explore / select / confirm partition |
| `src/research/multiplicity.py` | How much did we look? |
| `src/research/design.py` | Is this study allowed to exist? |
| `src/archive/stopgap.py` | Daily capture |
| `configs/*.yml` | All parameters — single source of truth |
| `docs/decisions/` | 18 decision records |
| `docs/plan/PLAN_[1-3]_*.md` | The full plan |

## Appendix C — Glossary

| Term | Meaning |
|---|---|
| **Bulk deal** | A trade above 0.5% of a company's shares in one day; must be disclosed |
| **Block deal** | A large pre-arranged trade in a separate exchange window |
| **MDE** | Minimum detectable effect — the smallest effect a study could reliably find |
| **t-statistic** | How many standard errors a result is from zero; above ~2 is conventionally "significant" |
| **Sharpe ratio** | Return divided by volatility; higher is better |
| **Basis point** | One hundredth of a percent |
| **Pre-registration** | Writing down predictions and pass marks before looking |
| **Point-in-time** | Using only information that existed on the date in question |
| **Provenance** | A record of which data and code produced a number |
| **UNDERPOWERED** | The study could not have detected the effect either way — silence, not evidence |
