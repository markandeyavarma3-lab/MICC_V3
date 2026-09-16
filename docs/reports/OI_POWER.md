# OI_POWER.md — exp_003 landing: UNDERPOWERED in every category

**Generated 2026-09-16 by `python -m src.research.oi_power` against the
registered spec (decision 0067, `spec_hash 9390d07e…`). Dispersion and n
only. No mean return, tercile, sign or direction was computed. Derivatives
positioning, not cash flow.**

## The landing

Every category — FII, DII, Pro, Client — is **UNDERPOWERED at the primary
horizon (21 sessions): the two-arm MDE is 2.025% against a bound of 0.50%,
4.05× short**, and at every other horizon from 1 to 252 sessions (6.79× to
3.17× short). Per 0067 kill criterion 1, **no fit is run**. The bound is not
loosened. `TRACK_O_POSITIONING` stays at `trials_before = 0` and this table
charges nothing: nothing here estimates an effect.

**Why the four rows are identical.** Power for a signal study depends on the
dispersion of the *outcome* and the number of observations, not on the
signal. Here the outcome is the same series for every category (the NIFTY
50's own forward return) and each category has the same ~3,045 sessions
and 150 monthly cohorts. The study is underpowered as a *design*: no
participant category could clear the bar with this outcome series and this
much history, whatever its ΔOI does.

**How far short.** MDE scales as 1/√cohorts. Reaching the bound at 21
sessions needs 4.05² ≈ 16× the cohorts — about 2,400 months of daily
positioning data against 150 in hand. The series grows by one session a
day. This is not a study that waits; per 0067's reversal clause it is
**closed as unaskable at the project's plausible bound**, which is the same
class of landing as 0038 (bulk buys) and 0043 (consensus).

**What would have to change for it to be askable** — each is a new spec, not
a loosening: a less noisy outcome (a hedged or market-neutral index
position rather than the raw NIFTY — cohort SD at 21 sessions is 3.96%); a
denser observation unit than the day (the file is daily; there is none); or
a plausible bound argued from positioning economics rather than reused
from the deal studies — and 0011/0028 fixed that bound for the project.

| category | sessions | n obs | cohorts | cohort SD | infl | MDE 1-arm | MDE 2-arm | bound | verdict |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| FII | 1 | 3,065 | 151 | 0.355% | 1.00 | 0.081% | 0.162% | 0.02% | UNDERPOWERED (6.79x short) |
| DII | 1 | 3,065 | 151 | 0.355% | 1.00 | 0.081% | 0.162% | 0.02% | UNDERPOWERED (6.79x short) |
| Pro | 1 | 3,065 | 151 | 0.355% | 1.00 | 0.081% | 0.162% | 0.02% | UNDERPOWERED (6.79x short) |
| Client | 1 | 3,064 | 151 | 0.355% | 1.00 | 0.081% | 0.162% | 0.02% | UNDERPOWERED (6.79x short) |
| FII | 2 | 3,064 | 151 | 0.564% | 1.00 | 0.129% | 0.257% | 0.05% | UNDERPOWERED (5.40x short) |
| DII | 2 | 3,064 | 151 | 0.564% | 1.00 | 0.129% | 0.257% | 0.05% | UNDERPOWERED (5.40x short) |
| Pro | 2 | 3,064 | 151 | 0.564% | 1.00 | 0.129% | 0.257% | 0.05% | UNDERPOWERED (5.40x short) |
| Client | 2 | 3,063 | 151 | 0.564% | 1.00 | 0.129% | 0.257% | 0.05% | UNDERPOWERED (5.40x short) |
| FII | 3 | 3,063 | 151 | 0.780% | 1.00 | 0.178% | 0.356% | 0.07% | UNDERPOWERED (4.98x short) |
| DII | 3 | 3,063 | 151 | 0.780% | 1.00 | 0.178% | 0.356% | 0.07% | UNDERPOWERED (4.98x short) |
| Pro | 3 | 3,063 | 151 | 0.780% | 1.00 | 0.178% | 0.356% | 0.07% | UNDERPOWERED (4.98x short) |
| Client | 3 | 3,062 | 151 | 0.780% | 1.00 | 0.178% | 0.356% | 0.07% | UNDERPOWERED (4.98x short) |
| FII | 5 | 3,061 | 150 | 1.152% | 1.00 | 0.264% | 0.527% | 0.12% | UNDERPOWERED (4.43x short) |
| DII | 5 | 3,061 | 150 | 1.152% | 1.00 | 0.264% | 0.527% | 0.12% | UNDERPOWERED (4.43x short) |
| Pro | 5 | 3,061 | 150 | 1.152% | 1.00 | 0.264% | 0.527% | 0.12% | UNDERPOWERED (4.43x short) |
| Client | 5 | 3,060 | 150 | 1.152% | 1.00 | 0.264% | 0.527% | 0.12% | UNDERPOWERED (4.43x short) |
| FII | 10 | 3,056 | 150 | 2.043% | 1.13 | 0.496% | 0.993% | 0.24% | UNDERPOWERED (4.17x short) |
| DII | 10 | 3,056 | 150 | 2.043% | 1.13 | 0.496% | 0.993% | 0.24% | UNDERPOWERED (4.17x short) |
| Pro | 10 | 3,056 | 150 | 2.043% | 1.13 | 0.496% | 0.993% | 0.24% | UNDERPOWERED (4.17x short) |
| Client | 10 | 3,055 | 150 | 2.042% | 1.13 | 0.496% | 0.992% | 0.24% | UNDERPOWERED (4.17x short) |
| FII | 21 | 3,045 | 150 | 3.959% | 1.25 | 1.012% | 2.025% | 0.50% | UNDERPOWERED (4.05x short) |
| DII | 21 | 3,045 | 150 | 3.959% | 1.25 | 1.012% | 2.025% | 0.50% | UNDERPOWERED (4.05x short) |
| Pro | 21 | 3,045 | 150 | 3.959% | 1.25 | 1.012% | 2.025% | 0.50% | UNDERPOWERED (4.05x short) |
| Client | 21 | 3,044 | 150 | 3.959% | 1.25 | 1.012% | 2.025% | 0.50% | UNDERPOWERED (4.05x short) |
| FII | 63 | 3,003 | 148 | 7.741% | 2.39 | 2.754% | 5.509% | 1.50% | UNDERPOWERED (3.67x short) |
| DII | 63 | 3,003 | 148 | 7.741% | 2.39 | 2.754% | 5.509% | 1.50% | UNDERPOWERED (3.67x short) |
| Pro | 63 | 3,003 | 148 | 7.741% | 2.39 | 2.754% | 5.509% | 1.50% | UNDERPOWERED (3.67x short) |
| Client | 63 | 3,002 | 148 | 7.742% | 2.39 | 2.755% | 5.509% | 1.50% | UNDERPOWERED (3.67x short) |
| FII | 126 | 2,940 | 144 | 10.863% | 4.12 | 5.144% | 10.288% | 3.00% | UNDERPOWERED (3.43x short) |
| DII | 126 | 2,940 | 144 | 10.863% | 4.12 | 5.144% | 10.288% | 3.00% | UNDERPOWERED (3.43x short) |
| Pro | 126 | 2,940 | 144 | 10.863% | 4.12 | 5.144% | 10.288% | 3.00% | UNDERPOWERED (3.43x short) |
| Client | 126 | 2,939 | 144 | 10.862% | 4.12 | 5.144% | 10.288% | 3.00% | UNDERPOWERED (3.43x short) |
| FII | 252 | 2,814 | 138 | 15.919% | 6.35 | 9.508% | 19.017% | 6.00% | UNDERPOWERED (3.17x short) |
| DII | 252 | 2,814 | 138 | 15.919% | 6.35 | 9.508% | 19.017% | 6.00% | UNDERPOWERED (3.17x short) |
| Pro | 252 | 2,814 | 138 | 15.919% | 6.35 | 9.508% | 19.017% | 6.00% | UNDERPOWERED (3.17x short) |
| Client | 252 | 2,813 | 138 | 15.921% | 6.34 | 9.510% | 19.020% | 6.00% | UNDERPOWERED (3.17x short) |


## Verdict at the primary horizon (21 sessions), verbatim from the module

- **FII**: UNDERPOWERED (4.05x short) — MDE two-arm 2.025% vs bound 0.50%, 150 cohorts, inflation 1.25
- **DII**: UNDERPOWERED (4.05x short) — MDE two-arm 2.025% vs bound 0.50%, 150 cohorts, inflation 1.25
- **Pro**: UNDERPOWERED (4.05x short) — MDE two-arm 2.025% vs bound 0.50%, 150 cohorts, inflation 1.25
- **Client**: UNDERPOWERED (4.05x short) — MDE two-arm 2.025% vs bound 0.50%, 150 cohorts, inflation 1.25

**Every category is UNDERPOWERED at the primary horizon. No fit is run;
this is the landing (0067 kill criterion 1). The bound is not loosened.**

