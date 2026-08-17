# 0002 — Pre-registration with cryptographic spec freezing

**Date:** 2026-08-16
**Decided by:** Claude, implementing the owner's plan §6
**Status:** ACTIVE

## Context
MICCV2 could not distinguish a hypothesis formed before seeing data from one
formed after. Every bar was therefore unfalsifiable in principle.

## Decision
An experiment's spec — hypothesis, universe, horizons, entry/exit, costs,
benchmark, pass bar, kill criteria — is hashed and written to
`experiment_registry` before the test runs. A SQLite trigger refuses edits to any
frozen field once status leaves `DRAFT`.

## Why
A pass bar set after seeing the result is not a bar. The trigger matters more than
the intention: exp_001's freeze was verified by attempting to rewrite its pass bar
and being refused, which is evidence rather than a promise.

## What would reverse this
Nothing plausible. If the trigger proves too rigid for legitimate corrections, the
fix is an explicit superseding registration, not a softer trigger.

## Cost accepted
Every study needs its bar derived before the data is seen, which is harder and
slower than deciding afterwards what counts as success.
