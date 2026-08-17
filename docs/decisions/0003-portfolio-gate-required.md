# 0003 — Every study must pass a portfolio gate, not only an event gate

**Date:** 2026-08-16
**Decided by:** Claude, forced by Finding 001
**Status:** ACTIVE

## Context
exp_001 produced a real, controlled, event-level abnormal return of −0.805% over
10 sessions at t = −3.93, surviving a random-stock control and a
volatility-matched control. Its portfolio effect was −0.022%/yr at t = −0.25.

The gap was dilution: the filter touched **1.2% of names**. A −0.8% effect on 1.2%
of a book is roughly one basis point a month.

## Decision
Two gates, both mandatory. The event gate (abnormal return vs matched control,
after correction, MDE below the plausible bound) and the portfolio gate (a
constructed book beats the identical book without the signal, net of costs on
incremental turnover, paired bootstrap CI excluding zero).

## Why
Under the original plan, portfolio construction lived in Room 5, which was out of
scope. So nothing could legitimately reach Room 5, and every gate that existed was
an event-study gate. **exp_001 would have been recorded as a PASS and shipped as a
finding.** Every statistic in its event study was correct and pointed the right
way; only building the actual book revealed it was useless.

## What would reverse this
Nothing. An event study is not a strategy test, and the distance between them is
not a detail.

## Cost accepted
Every study now requires a portfolio construction step, roughly doubling the work
per study. Many event effects will die here — correctly.
