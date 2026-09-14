# 06 — Rebuild prompt

Paste everything below into a fresh Claude Code session (or any coding agent)
pointed at a clone of this repository, to continue the project without
re-deriving context from scratch.

---

## PROMPT START

You are continuing an existing, mature research project called **MICC_V3 /
"institutional-research"**. Do not propose a new architecture, do not delete
or rewrite working modules, and do not restart the research question — it has
already been answered. Read `handover/00_TREE.md` through
`handover/04_WHAT_IS_MISSING.md` in this repo before doing anything else; they
are a complete, code-derived map of what exists. This prompt summarizes them.

### What this project is

A solo research platform testing whether disclosed institutional activity in
Indian equities (NSE/BSE bulk & block deals, FII/DII cash flow, F&O
participant open interest) contains repeatable, tradeable information. No
live trading, no order-placement code anywhere, no broker integration — it is
a measurement instrument, not a strategy. Python 3.14, DuckDB (derived
research marts) + SQLite (append-only, trigger-enforced governance ledgers),
pandas/numpy/scipy, local parquet. No frontend, no server, no API.

### The headline result — already delivered, do not re-litigate it

`docs/reports/VERDICT.md` (2026-09-10) closes the primary research question:
**no registrable finding at any horizon, for any population, by any
participant.** 0 of 15 (population, horizon) pairs reach their pre-registered
power bound. The one large-looking effect (institutional sells, −22.7%/yr at
12 months) is confounded — it lives in the least-tradeable third of the
market and fails the survivorship check. The one "statistically significant"
participant is a passive ETF measured over two months, a leaderboard
artifact, not skill. A second track (seasonality / "Engine 2") was
independently killed on pure power arithmetic on 2026-09-12
(`docs/reports/SEASONALITY_POWER.md`) — a calendar cell fires once a year, so
21 years of history structurally cannot reach the observation count any
multiplicity-corrected bar requires. **Do not propose "just collect more
seasonality data" or "just re-run the deal study" without reading that memo
and `VERDICT.md` first — both verdicts are arithmetic, not data-gap
problems.**

### What is genuinely strong and must not be rebuilt from scratch

- `src/research/power.py`, `multiplicity.py`, `design.py` — MDE-before-fit,
  monthly-cohort collapse as the primary estimator, Bartlett-kernel serial
  correction with a label-overlap-aware lag, Gumbel best-of-N noise bars with
  a degrees-of-freedom correction. This killed the project's own original
  headline finding, which is why the rest of its negative results are
  trustworthy. **This is the best code in the repository — read it before
  touching any statistics.**
- The governance layer (`src/governance/`, migrations `0001`–`0003` sqlite) —
  write-once, trigger-enforced ledgers for provenance, trial counting, and
  experiment registration. A 2026-09-12 commit closed a real
  `INSERT OR REPLACE` bypass of the frozen-specification guarantee — this is
  recent, careful, adversarial work against the project's own scripts. Do not
  weaken it to make a script "just work."
- 58 decision records in `docs/decisions/`, each with Context / Decision /
  Why / What-would-reverse-this / Cost-accepted. This is the project's actual
  memory — read the relevant ones before changing a config value that looks
  arbitrary; it almost certainly isn't (e.g. the horizon grid, the
  participation ceiling, the ISIN-keyed split are all load-bearing decisions
  with measured numbers behind them, not defaults).
- The 2.5 GB predecessor seed (`data/raw/v1_export`, `data/raw/v1_increments`)
  is **irreplaceable** — the source repositories it came from were deleted
  2026-09-01, and NSE's historical endpoint returns 503 (only the current-day
  rolling file is fetchable). If you ever have write access to the machine
  holding this data, confirm it has an independent cold backup before doing
  anything that could touch it.

### What is known to be missing or was last known broken — verify before trusting

Read `handover/04_WHAT_IS_MISSING.md` in full. The single highest-priority
item to check first, if continuing the deals research: **whether
`src/research/measure.py`, `consensus.py`, and `selling.py` join price
history on the point-in-time-resolved `security_id` or on the raw deal
symbol.** A 2026-09-02 external audit found they used the raw symbol,
defeating the entire purpose of the identity layer (a recycled ticker could
silently attribute one company's deal to another's prices). This was not
independently re-confirmed as fixed or still-broken for this handover — it
directly affects whether `VERDICT.md`'s numbers can be trusted, so check it
before extending or re-running any study.

### Standing rules (from README.md, and the reason each exists is a documented predecessor defect — see docs/decisions/0001)

1. No order-placement code. Not in tests, not commented out.
2. Raw files are never overwritten or deleted.
3. Verification is read-only. A verify command that writes is a bug.
4. `RESEARCH_ENV` must be explicit; unset fails loudly (`src/common/paths.py`
   raises `EnvironmentNotSet` — do not add a default).
5. Every study is pre-registered, with its pass bar and kill criteria fixed
   *before* the code that computes a result runs (`scripts/register_*.py`,
   the frozen-spec triggers in `migrations/0001`+`0003` sqlite).
6. The trial counter only increases (`family_charge`, append-only, monotonic
   trigger-enforced) — applies to incumbents too, not just new studies.
7. A fix is done when its test has been watched failing against the
   unpatched code first, then passing.
8. UNKNOWN beats inference — see the `confidence` columns throughout the
   schema (`security_master.confidence`, `institutional_deals_clean.available_from_confidence`,
   etc.) and the `NOT_APPLICABLE` skip policy in `configs/confounds.yml`.

### Working environment

`data/` and `db/` are gitignored and were **absent from the container this
handover pack was generated in** — you may be in the same situation. If so:
1. Everything in `src/` can still be read, and the `unit`-marked test tier
   (`RESEARCH_ENV=dev python -m pytest tests -m unit -q`) runs with no data.
2. You cannot verify any research number, run the warehouse rebuild, or run
   the `data`/`research`/`regression` test tiers without the real `data/` and
   `db/` from the project owner's machine. Say so plainly rather than
   fabricating results — this project's entire culture (documented across 58
   decision records) is built around not doing that.
3. `handover/schemas.sql` has the full DuckDB + SQLite schema (final state,
   all migrations applied) if you need to reason about table shapes without
   a live database.
4. `handover/07_CONFIG_SNAPSHOT.yaml` and `handover/code_map.json` give a
   structured index of every config value and every module's public
   interface, if you need to work without re-reading the full `configs/` and
   `src/` trees.

### If asked to add a new study or engine

Read `configs/split.yml` (the EXPLORE/SELECT/CONFIRM partition, ISIN-keyed,
sha256-bucketed) and `configs/trials.yml` (hierarchical trial families) first.
A new study must: declare its trial family *before* touching CONFIRM data,
register a frozen spec via the governance layer before computing any result,
run the full confound checklist in `configs/confounds.yml` (or mark each
inapplicable one `NOT_APPLICABLE` with a written reason), and pass *both* the
event gate and the portfolio gate in `configs/research.yml` before being
reported as a finding — an event-level effect that doesn't survive
construction into an actual book is exactly what killed the project's
original headline finding (Finding 001), and the portfolio gate exists
specifically because of that.

## PROMPT END
