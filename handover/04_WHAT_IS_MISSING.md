# 04 — What is missing / broken / open

Combines `docs/STATUS.md` (472dfa8), `docs/HEALTH.md` (2026-09-11),
`AUDIT_README.md` (2026-09-02, commit f79ac5d — **flagged items should be
re-verified against current HEAD before acting**, since 20 commits have
landed since and at least 2 of its CRITICAL findings read as fixed in the
later STATUS.md), and the last 3 commit messages.

## A. Confirmed still-open, as of the most recent artefacts (2026-09-11/12)

1. **`fno_spine` is 28 days STALE** (`docs/DATA_INVENTORY.md`). Decision 0058
   resumed *collecting* participant-OI and F&O bhavcopy bytes but nothing
   parses them into the warehouse yet — deliberate, to avoid opening a second
   analysis front while Workstream 3 (the deals verdict) is still live. If
   the derivatives data is ever going to be used, this parser is the next
   piece of work, plus a column-mapping between the legacy 16-column
   `fno_spine` schema and the new 34-column UDiFF format (flagged, not built,
   in decision 0058 §3).
2. **`docs/HEALTH.md` reports 2 sources STALE** at generation time
   (2026-09-11 08:16 UTC): `nse_bulk_deals` and `nse_block_deals`, each with
   acknowledged permanent losses layered on top of the staleness count.
3. **Backup lag** — latest STATUS.md snapshot flagged 73 archived sessions not
   yet in the off-machine backup.
4. **Three permanently lost sessions**, architectural rather than fixable:
   `nse_bulk_deals` 2026-08-19 & 2026-08-27, `nse_block_deals` 2026-08-19,
   `fii_dii_cash` 2026-08-19. NSE's historical endpoint returns 503 with or
   without a session cookie; only the rolling current-day file is fetchable,
   so a missed day is gone forever. This is why the collector is described in
   the project's own docs as "the most time-sensitive work" — every future
   missed session is equally permanent.
5. **BSE bulk/block deals — never collected.** `sources.yml` status
   `UNPROVEN`; the documented API route returns a 301 to an error page even
   with the required `Origin`/`Referer` headers.
6. **Sector history, participant aliases, promoter entities all 0 rows.**
   Blocks: the industry dimension of `CHAR_MATCHED`, the sector-concentration
   confound check, the promoter-related-transaction flag, and any fund-house
   consolidation of consensus counts.
7. **`configs/sources.yml` (241 lines) and `configs/scan.yml` (365 lines)
   confirmed unparsed by any code** at the last audit — values exist only as
   documentation or duplicated as Python literals elsewhere. Re-verify if a
   new engineer is tempted to "just edit the config" expecting it to change
   behavior.
8. **`NIFTY500_TR` (the config's declared broad-market headline benchmark)
   has no source table and is unbuildable** — `warehouse.benchmark_n500tr`
   does not exist. Every benchmarked result in the project lacks this
   comparison; 5 of 6 declared benchmarks are actually used.
9. **Track S (mass pattern search / seasonality) machinery is entirely
   unbuilt** — `src/scan/` does not exist, `seasonality_cell` holds 0 rows,
   folds/nulls/procedure-test/CPCV/PBO are all SPECIFIED-only. **This is now
   moot as a research question** — Engine 2 was killed on pure power
   arithmetic on 2026-09-12 (`docs/reports/SEASONALITY_POWER.md`): a calendar
   cell fires once a year, so 21 years of data can never supply enough
   observations at any multiplicity correction, and pooling across the
   4,200-name universe only buys the information of ~4.25 independent names
   at the measured autocorrelation. If someone wants to resurrect Track S,
   read that memo first — the conclusion is arithmetic, not a data gap that
   more collection would fix.
10. **Duplicate deal grouping (NSE/BSE cross-listing), five-day round-trip
    flag, internal-transfer flag, promoter-related flag** — all declared
    columns in `institutional_deals_clean`, all FALSE/NULL on every row as of
    the last audit. Schema exists, population does not.
11. **Three-scheme walk-forward (anchored + rolling + CPCV) and PBO from
    CPCV** — SPECIFIED only, not built. Relevant only if a new study is
    registered against CONFIRM data; the current VERDICT.md closes the
    project's primary question via power analysis before reaching this stage.

## B. Historical findings from the 2026-09-02 audit — status uncertain, re-verify before relying on either the "broken" or "fixed" read

These were CRITICAL/HIGH findings in `AUDIT_README.md` at commit `f79ac5d`.
20 commits and 10 days separate that audit from the current HEAD. Two of them
(the `land()` crash and the `status.py` self-reference bug) show strong
circumstantial evidence of being fixed in the STATUS.md snapshot used
throughout this handover pack — but that inference was not confirmed by
re-running the actual code, because this container has no `data/`/`db/` to
test against.

1. **`land()` raising `_csv.Error` on real archive PRICE/INSIDER files**
   (audit BUG-1). Evidence of fix: `land` now appears in
   `scripts/collect_daily.sh`'s pipeline (with an explicit comment explaining
   *why* it's there now, referencing the original 2-day outage), and
   STATUS.md step 2.1 reads VERIFIED with no crash noted. **Not
   independently re-run.**
2. **`status.py` self-referential predicates** inflating step grades
   (Romano-Wolf reading VERIFIED from a zero-implementation string match).
   Evidence of fix: the current STATUS.md's step 6.8 note cites decision 0056
   and a real (tiny) participant leaderboard by name, which reads as a
   substantive, non-self-referential grade. **Not independently re-run.**
3. **Governance guards (`ConfirmationGuard`, `StudyDesign`,
   `commit_charge`) with zero production call sites; `family_charge` = 0
   rows.** Evidence against "still fully broken": `family_charge` now has 5
   rows (`docs/DATA_INVENTORY.md`, 2026-09-11) and a real append-only,
   monotonic schema (migration 0002 sqlite). **Whether the three study
   modules (`measure.py`, `consensus.py`, `selling.py`) actually construct a
   `StudyDesign` and call `charge()` — as opposed to some other code path
   populating `family_charge` — was not confirmed.** Check these three files
   directly before claiming the guards are wired.
4. **Two divergent PROP_HFT classifier implementations**
   (`eligibility.py` vs `clean.py`, ~0.5% divergence in row counts). No
   evidence found either way — check both files if participant classification
   correctness matters for new work.
5. **`security_id` computed but not used to join prices** — `measure.py`,
   `consensus.py`, `selling.py` historically joined returns on raw
   `UPPER(TRIM(symbol_raw))` instead of the point-in-time-resolved
   `security_id`, defeating the identity layer's entire stated purpose (a
   recycled ticker could attribute one company's deal to another's prices).
   **No evidence of a fix found in the newer artefacts read for this
   handover — this is the single highest-value thing to check first** if
   continuing the deals research, since `VERDICT.md`'s numbers depend on it.
   Corroborating (not conclusive) evidence from a static import scan:
   `src/research/measure.py`, `consensus.py`, and `selling.py` import
   **only** `power`/`measure` and `src.common.paths` — none of them imports
   `src.identity.master`. That is consistent with either (a) they still join
   on the raw symbol, or (b) they correctly read the `security_id` column
   that `mart/clean.py` already resolved and stored on
   `institutional_deals_clean` — which would NOT require importing
   `identity.master` directly. **Read the actual SQL in these three files
   (the `_events_sql`/`_returns_sql` functions) to settle which case holds —
   the import list alone does not prove it either way.**
6. **9 unexplained >35% price discontinuities in `price_spine_adj`**
   (budget 12), 4 of them ETF units decision 0040 says should have left the
   universe. No evidence of a fix found.
7. **Undeclared benchmark** — at audit time, every study result was actually
   measured against an unweighted `avg(ret)` cross-sectional mean baked into
   `measure.py`, not any of the 6 declared benchmarks. Given `VERDICT.md`
   (2026-09-10) discusses `CHAR_MATCHED` coverage explicitly in its
   limitations section, this may have been at least partially resolved for
   the final verdict computation — but the underlying `measure.py` behavior
   was not re-checked.
8. **Test suite quality**: at audit time the two flagship study modules
   (`consensus.py`, `selling.py`) were covered only by substring-assertion
   tests that never executed a real query, and mocks in `test_ingest.py` hid
   the 2-day `land()` outage. No evidence these test-quality issues were
   addressed (as opposed to the underlying bugs they failed to catch).

## C. What a new session must do before trusting any number from this project

1. **Get `data/` and `db/` populated** (from the owner's machine — see
   `06_REBUILD_PROMPT.md` and the "irreplaceable seed" warning in
   `02_DATA_DICTIONARY.md`). Nothing in `src/research/` can be verified
   without them; the unit test tier (CI) exercises none of the actual
   statistics.
2. **Re-run `python -m src.monitor.status`** to regenerate `docs/STATUS.md`
   fresh against current code and current data, rather than trusting the
   472dfa8 snapshot bundled in this repo.
3. **Grep `measure.py`, `consensus.py`, `selling.py` for the join column**
   used against price history — confirm `security_id` vs. raw symbol before
   trusting any effect-size number.
4. **Confirm whether `StudyDesign`/`charge()` are actually constructed** by
   the three study modules, or whether `family_charge`'s 5 rows come from
   somewhere else (e.g. the two `register_*.py` scripts calling
   `commit_charge` directly rather than the studies themselves doing it).
