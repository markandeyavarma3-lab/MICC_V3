# 0006 — Full 31.9M-cell rescan rather than validating the existing atlas

**Date:** 2026-08-16
**Decided by:** Owner, against my recommendation, reaffirmed when challenged
**Status:** **SUPERSEDED by [0026](0026-validate-the-atlas-not-rebuild-it.md)** on 2026-08-18

> The owner reversed this decision when the schedule rewrite showed only 1.7
> weeks of slack against the 2027-02-28 deadline. The reasoning below stands as
> the record of why the full rebuild was originally chosen; read 0026 for why
> it was given up and what validation must still prove.

## Context
MICCV2 built a seasonality atlas of 31,893,556 cells. Its own verdict: ratio 1.05
versus chance, best pattern at the 94th percentile of rotated noise. I recommended
validating that atlas in ~1 week rather than rebuilding it in ~3.

## Decision
Full rescan with new code. ~3 weeks, chunked and resumable.

## Why
My objection was that this re-derives a known answer. The owner's reasoning stands
on its own: independent confirmation and clean provenance through the DAG, rather
than trusting the predecessor's output — the predecessor whose fee model was wrong
by 10.04 bps and whose README had drifted from its own crontab.

## What would reverse this
Time pressure against the 2027-02-28 deadline ([0010](0010-project-kill-criterion.md)).
If the four institutional studies consume the budget, validating the atlas becomes
the pragmatic call.

## Cost accepted
Three weeks to re-derive an answer we already have, and which is probably "nothing
here".
