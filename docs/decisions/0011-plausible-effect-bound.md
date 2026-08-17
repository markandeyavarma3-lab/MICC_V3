# 0011 — The plausible effect bound stays at 0.5%/month

**Date:** 2026-08-17
**Decided by:** Owner, confirming a value I had chosen
**Status:** ACTIVE

## Context
`configs/research.yml` carried `plausible_effect_bound_monthly: 0.005`. That number
was mine, unmeasured, and it governs every UNDERPOWERED verdict in the project —
the rule being that MDE above the bound yields silence regardless of the p-value.

It sat in a config for a day looking like a measurement before anyone asked where
it came from.

## Decision
Retain 0.5%/month = 6%/yr abnormal, project-wide.

## Why
6%/yr is around the upper end of what a genuine, persistent institutional
information edge plausibly delivers from a public disclosure feed. Raising it to
1%/month would mostly buy permission to report noise; lowering it to 0.25% would
render essentially every current design underpowered.

The consequence is uncomfortable and is the honest reading: at 1 month MDE is
1.52%, and 1.05% even after characteristic matching. **Both exceed the bound.**
Most currently-designed studies can only detect implausibly large effects.

## What would reverse this
A literature estimate or a measured distribution of abnormal returns around
institutional disclosure in Indian equities. This is a prior standing in for a
measurement, and it should be replaced by one when available.

## Cost accepted
A real effect between 0.5% and 1.5% per month would be stamped UNDERPOWERED rather
than detected. Preferred to the alternative error.
