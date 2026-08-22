# 0031 — Consensus is the single critical-path study

**Date:** 2026-08-23
**Decided by:** Owner
**Status:** ACTIVE

## Context

`PLAN_3` §3.2 reduces the critical path to **one** outcome study — *"one study
answered beats four half-answered"* — and never names which one. The surrounding
documents then implied two different answers, and nobody noticed until the report
was audited on 2026-08-22:

- **§1.4** locks four studies "in descending order of expected value" and numbers
  them 1 Consensus, 2 Selling, 3 Blocks, 4 Bulk buys.
- **§3.3** lists the extensions as *"**studies 2–4** | institutional selling
  first"*. If the extensions are studies 2–4, study 1 is the critical-path study,
  and study 1 is Consensus.
- **Report §11.5** said the one study was **Selling**, which reads like
  "institutional selling first" being taken as *first study* rather than *first
  among the extensions*.

Grepped 2026-08-22: **no decision record mentioned either study.** The ordering
had never been decided, only implied.

## Decision

**Consensus** — do 3+ unrelated institutions buying the same name within 21
sessions predict outperformance? — is the study on the critical path. Selling,
Blocks and Bulk buys are extensions, in that order, and Selling leads them.

## Why

It is what §1.4's numbering already implied, and that ranking carried a stated
reason rather than a preference: single-participant skill is not measurable at
this sample size — SBI Mutual Fund has 80 buys in twenty years, where skill and
luck are indistinguishable — whereas **a pooled convergence event requires no
individual institution to be smart.** Consensus is the only one of the four whose
statistical power does not depend on any single participant being good.

Selling is the strongest rival and stays first among the extensions: 34,270
events never examined anywhere, with an asymmetry behind it — institutions buy
for many reasons (inflows, index tracking, rebalancing) and sell for fewer.

The alternative was to keep the report's Selling and treat §1.4's numbering as
stale. Rejected: §1.4 is an owner decision of 2026-08-16 with reasoning attached,
and overriding it by inference from an ambiguous phrase in a different section is
the failure mode this repository exists to prevent.

## What would reverse this

Consensus proving unbuildable at the measured event counts. `participants.yml`
records 10,098 events at the primary definition (3 institutions, 21 sessions)
against Selling's 34,270, and consensus events overlap heavily — if the
independent count after overlap adjustment is too thin to register, Selling
becomes the critical-path study and this record is superseded.

## Cost accepted

- Consensus has **fewer events** than Selling (10,098 vs 34,270) and its triggers
  overlap, so its independent sample is smaller still. It is chosen on the
  strength of its mechanism, not on sample size.
- **Selling — the single largest unexamined block of evidence in the project —
  does not run on the critical path**, and under the cut order it runs only if
  the critical path lands on time.
- The ordering is, for now, academic: decision
  [0028](0028-plausible-bound-scales-with-horizon.md) blinded every horizon, so
  neither study can be registered until characteristic matching raises power. This
  record settles *which* study, not *when*.
