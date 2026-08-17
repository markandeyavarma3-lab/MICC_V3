# 0001 — Abandon MICCV2, rebuild in a new public repo

**Date:** 2026-08-16
**Decided by:** Owner (Markandeya Varma), against my recommendation
**Status:** ACTIVE

## Context
An audit of MICCV2 found the engineering sound — 486 tests passing, a real
warehouse, working ingestion — and the research empty: zero promotions, 22 KILLs,
a champion with full-sample Sharpe 1.52 and trailing-24m Sharpe 0.11.

## Decision
Freeze MICCV2 at tag `frozen-2026-08-16`. Rebuild research-only in
`~/Workspace/institutional-research`. No engines, no live trading, ever.

## Why
I recommended keeping MICCV2 and rebuilding the research layer inside it, on the
grounds that 486 passing tests are expensive to recreate. The owner overrode this:
the codebase carries assumptions that were never true (the fee model alone was
wrong by 10.04 bps per round trip), and inheriting the schema means inheriting
those assumptions in places nobody would think to look.

## What would reverse this
Discovering that a MICCV2 component is genuinely irreplaceable and cannot be
ported. So far only the trading calendar and the 1.2 GB `v1_export` seed qualify,
and both are being copied rather than depended on.

## Cost accepted
486 tests, a working ingestion layer, and a warehouse — rewritten from scratch.
Weeks of work discarded deliberately.
