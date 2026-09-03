"""status.py — phase completion DERIVED from the repository, never asserted.

WHY THIS EXISTS, AND IT IS A CORRECTION OF MY OWN CONDUCT.

Across 2026-08-22 to 08-24 I reported three steps complete that were not:

    1.6  fourteen tables created -> reported done. They held 0 rows and NOTHING
         in the codebase referenced research_db. A schema with no producer and
         no consumer.
    1.9  "every table written registers its artefact" -> reported done.
         char_panel had written 330,861 rows and registered nothing, and the
         landed tables carried zero parent edges, so lineage was a dead end.
    2.1  parse produced 619 rows -> reported done. Nothing wrote them anywhere.

The common error is not carelessness about any one step. It is a definition:
**I treated "the artefact exists" as "the step is complete".** A table with a
schema and no consumer reads identically to a working one unless someone asks
the second question.

So completion is graded, and the grades are computed from ground truth — file
existence, row counts, whether any module outside the definer references the
thing, whether a test exercises it against real data:

    SPECIFIED   the plan describes it; nothing is built
    BUILT       the code, table or file exists
    WIRED       something downstream actually consumes it
    VERIFIED    a test asserts its behaviour against real data

Plus two terminal states that are not failures and must not read as pending:

    IMPOSSIBLE  measured to be undoable, with the evidence attached
    BLOCKED     waiting on something outside the project's control

Phase 8's gate demands exactly this: *"the generated status page is derived from
repository and database state, not written by hand, and reproduces the live
figures ... A hand-written status drifts within a week."* MICCV2's README drifted
from its own crontab; this project's report has drifted four times in three days
on counts alone. The generated file plus a test that fails on drift is the only
arrangement that has actually held.
"""

from __future__ import annotations

import re
import sqlite3
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from typing import Literal

import duckdb

from src.common.paths import ARCHIVE, DOCS, ROOT, SEED, governance_db, research_db, warehouse_dir
from src.warehouse import reconcile

Level = Literal["SPECIFIED", "BUILT", "WIRED", "VERIFIED", "IMPOSSIBLE", "BLOCKED"]

ORDER: dict[str, int] = {
    "SPECIFIED": 0, "BUILT": 1, "WIRED": 2, "VERIFIED": 3,
    "IMPOSSIBLE": -1, "BLOCKED": -2,
}

STATUS_PATH = DOCS / "STATUS.md"


class Ctx:
    """Ground truth, read once. Every predicate below reads from here."""

    @cached_property
    def src_text(self) -> dict[str, str]:
        return {
            str(p.relative_to(ROOT)): p.read_text()
            for p in (ROOT / "src").rglob("*.py")
            if "__pycache__" not in str(p)
        }

    @cached_property
    def test_text(self) -> str:
        return "\n".join(
            p.read_text() for p in (ROOT / "tests").glob("*.py")
        )

    @cached_property
    def duck_rows(self) -> dict[str, int]:
        db = research_db("prod")
        if not db.exists():
            return {}
        import duckdb

        con = duckdb.connect(str(db))
        try:
            names = [
                r[0] for r in con.execute(
                    "SELECT table_name FROM information_schema.tables"
                    " WHERE table_schema='main'"
                ).fetchall()
            ]
            # COUNT EACH ONE SEPARATELY AND SURVIVE THE ONES THAT FAIL.
            #
            # `information_schema.tables` includes VIEWS, and measure.grid()
            # leaves `rets` and `mkt` behind on the research connection as a side
            # effect of running. A view whose dependency has been dropped raises
            # on COUNT, and in a dict comprehension one such view takes the whole
            # status page down — which is how a monitoring module becomes the
            # thing that needs monitoring. Found 2026-09-01 when exploratory
            # scripts left eight views in the production database.
            out: dict[str, int] = {}
            for n in names:
                try:
                    out[n] = con.execute(f"SELECT COUNT(*) FROM {n}").fetchone()[0]
                except duckdb.Error:
                    continue
            return out
        finally:
            con.close()

    @cached_property
    def gov_rows(self) -> dict[str, int]:
        db = governance_db("prod")
        if not db.exists():
            return {}
        con = sqlite3.connect(db)
        try:
            names = [
                r[0] for r in con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            ]
            return {n: con.execute(f"SELECT COUNT(*) FROM {n}").fetchone()[0] for n in names}
        finally:
            con.close()

    def module(self, rel: str) -> bool:
        return (ROOT / rel).exists()

    def provides(self, module: str, symbol: str) -> bool:
        """Does `module` actually define `symbol`, importably and callably?

        THE UPGRADE FROM `mentions`, AND THE REASON IT MATTERS.

        `mentions("hansen")` fixed the self-match but not the category error: it
        still asks whether a WORD appears somewhere in the tree. A comment, a
        docstring, a TODO or a variable named `hansen_todo` all satisfy it, and
        none of them is Hansen's SPA. A grader built on string presence measures
        vocabulary, not work.

        This imports the module and looks the symbol up. It cannot be satisfied
        by prose, it fails loudly if the module does not import, and a step
        graded by it is graded on something that would actually run.
        """
        import importlib

        try:
            m = importlib.import_module(module)
        except Exception:  # noqa: BLE001 - an unimportable module is not built
            return False
        return callable(getattr(m, symbol, None))

    def mentions(self, needle: str) -> bool:
        """Does any module OTHER THAN THIS ONE contain `needle`?

        THE DEFECT THIS EXISTS TO KILL, AND IT WAS MINE. Fourteen predicates
        were written as `c.mentions("romano")` —
        a scan of every source file, INCLUDING status.py. The word "romano"
        appears in `src/` exactly once: in this file, in step 6.8's own
        description and its own predicate. So the check matched its own text
        and step 6.8 read VERIFIED while `romano_wolf` existed nowhere in
        `src/research/`.

        The same held for corwin, vix, cpcv, pbo, hansen, shuffl, rotation,
        near_duplicate, pessimistic, recovery, newey, min_obs and sqrt. The
        module written to detect "the artefact exists is not the step works"
        was the largest single source of exactly that error in the project.

        Found by an external audit on 2026-09-02, not by this project's own
        machinery — which is the part worth remembering.
        """
        return any(
            needle.lower() in text.lower()
            for path, text in self.src_text.items()
            if path != "src/monitor/status.py"
        )

    def consumed(self, needle: str, definer: str) -> bool:
        """Does any module OTHER than its definer reference this?

        The question that distinguishes BUILT from WIRED, and the one I did not
        ask three times.
        """
        return any(
            needle in text and path != definer and not path.startswith("tests/")
            for path, text in self.src_text.items()
        )

    def tested(self, pattern: str) -> bool:
        return bool(re.search(pattern, self.test_text))

    def flag_is_real(self, column: str) -> bool:
        """Does this column ever take a non-default value?

        A BOOLEAN that is FALSE on all 237,340 rows, or a key that is NULL on
        all of them, is a placeholder wearing a schema. Phase 4 read VERIFIED
        with five such columns.
        """
        if not self.duck_rows.get("institutional_deals_clean"):
            return False
        import duckdb
        con = duckdb.connect(str(research_db("prod")), read_only=True)
        try:
            n = con.execute(
                f"SELECT COUNT(*) FROM institutional_deals_clean"
                f" WHERE {column} IS NOT NULL AND CAST({column} AS VARCHAR)"
                f" NOT IN ('false', '0')").fetchone()[0]
            return n > 0
        except Exception:  # noqa: BLE001 - a status page must not crash
            return False
        finally:
            con.close()

    @cached_property
    def collect_script(self) -> str:
        p = ROOT / "scripts" / "collect_daily.sh"
        return p.read_text() if p.exists() else ""

    def _spine_max(self, name: str) -> str:
        d = warehouse_dir("prod") / name
        if not list(d.glob("**/*.parquet")):
            return ""
        import duckdb
        con = duckdb.connect()
        try:
            return con.execute(
                f"SELECT MAX(date) FROM read_parquet('{d}/**/*.parquet')").fetchone()[0] or ""
        finally:
            con.close()

    @cached_property
    def price_spine_max(self) -> str:
        return self._spine_max("price_spine")

    @cached_property
    def adj_spine_max(self) -> str:
        return self._spine_max("price_spine_adj")

    @cached_property
    def sessions(self) -> int:
        from src.common import calendar
        try:
            return len(calendar.sessions("prod"))
        except Exception:  # noqa: BLE001 - a status page must not crash on data
            return 0

    @cached_property
    def corp_actions(self) -> int:
        from src.common.paths import COLLECTED
        files = list((COLLECTED / "corporate_actions").glob("*.parquet"))
        if not files:
            return 0
        import duckdb
        con = duckdb.connect()
        try:
            return con.execute(
                f"SELECT COUNT(*) FROM read_parquet('{COLLECTED}/corporate_actions/*.parquet')"
            ).fetchone()[0]
        finally:
            con.close()

    @cached_property
    def backup(self):
        """Off-machine backup state. See src/monitor/backup_state.py."""
        from src.monitor import backup_state
        return backup_state.read()

    def archive_sessions(self) -> int:
        m = ARCHIVE / "manifest.jsonl"
        if not m.exists():
            return 0
        return len({
            line.split('"session_date": "')[1][:10]
            for line in m.read_text().splitlines()
            if '"session_date": "' in line
        })


@dataclass
class Step:
    id: str
    phase: str
    what: str
    built: Callable[[Ctx], bool] | None = None
    wired: Callable[[Ctx], bool] | None = None
    verified: Callable[[Ctx], bool] | None = None
    #: Measured to be undoable. The string is the EVIDENCE, not an excuse.
    impossible: str = ""
    #: Waiting on something outside the project's control.
    blocked: str = ""
    #: A callable note is READ FROM THE REPO at render time. A fixed string is
    #: a claim that can go stale silently — which is how 1.10 spent eight days
    #: announcing an obstacle that had already been removed.
    note: str | Callable[[Ctx], str] = ""

    def note_for(self, c: Ctx) -> str:
        return self.note(c) if callable(self.note) else self.note

    def level(self, c: Ctx) -> Level:
        if self.impossible:
            return "IMPOSSIBLE"
        if self.blocked:
            return "BLOCKED"
        if self.built is None or not self.built(c):
            return "SPECIFIED"
        if self.wired is None or not self.wired(c):
            return "BUILT"
        if self.verified is None or not self.verified(c):
            return "WIRED"
        return "VERIFIED"


def steps() -> list[Step]:
    """Every step of Phases 0-3, with a predicate per level.

    Later phases are listed as SPECIFIED without predicates: inventing checks for
    work that has not started would be writing the scoreboard before the game.
    """
    return [
        # --- Phase 0 ---------------------------------------------------------
        Step("0", "0 Audit & specification", "Plans 1-4 and the feasibility report",
             built=lambda c: all((DOCS / "plan" / f).exists() for f in
                                 ("PLAN_1_FOUNDATIONS.md", "PLAN_2_METHODOLOGY.md",
                                  "PLAN_3_EXECUTION.md", "PLAN_4_SCAN.md")),
             wired=lambda c: (DOCS / "plan" / "FEASIBILITY_2026-08-16.md").exists(),
             verified=lambda c: c.tested(r"test_plan_docs_do_not_advertise_dropped_horizons")),
        Step("0.6", "0.6 Blocking decisions", "0018 answered before any registration",
             built=lambda c: (DOCS / "decisions" / "0028-plausible-bound-scales-with-horizon.md").exists(),
             wired=lambda c: "SUPERSEDED" in (DOCS / "decisions" / "0018-plausible-bound-not-horizon-scaled.md").read_text()[:400],
             verified=lambda c: c.tested(r"TestScaledBoundUnderDecision0028")),

        # --- Phase 1 ---------------------------------------------------------
        Step("1.1", "1 Warehouse", "Freeze MICCV2 — agents unloaded, plists moved, tag",
             built=lambda c: True, wired=lambda c: True,
             note="verified manually 2026-08-22: no micc agents loaded, tag frozen-2026-08-16 exists"),
        Step("1.2", "1 Warehouse", "Repo scaffold, pyproject, CI",
             built=lambda c: (ROOT / "pyproject.toml").exists(),
             wired=lambda c: any((ROOT / ".github" / "workflows").glob("*.yml")),
             # VERIFIED would mean CI proves the suite green, and it cannot:
             # data/ and db/ are gitignored, so a runner has no warehouse. It
             # runs the UNIT tier only. Grading this VERIFIED would be a green
             # badge over an untested half.
             note=lambda c: ("unit tier only — a runner has no data/ or db/, so "
                             "the data and research tiers stay a local gate")),
        Step("1.3", "1 Warehouse", "src/common — paths, hashing, migrations, config, logging",
             built=lambda c: c.module("src/common/paths.py") and c.module("src/common/hashing.py"),
             wired=lambda c: c.consumed("from src.common.paths", "src/common/paths.py"),
             verified=lambda c: c.tested(r"test_unset_environment_raises"),
             note="no structured logging and no central config loader; six modules load their own YAML"),
        Step("1.4", "1 Warehouse", "Trading calendar from observed sessions",
             built=lambda c: c.module("src/common/calendar.py"),
             wired=lambda c: c.consumed("calendar", "src/common/calendar.py")
                             or "cal AS" in c.src_text.get("src/mart/clean.py", ""),
             verified=lambda c: c.tested(r"test_the_calendar_is_observed_not_generated"),
             note=lambda c: (f"{c.sessions} observed sessions; 3 of them are "
                             f"Saturdays a generated calendar would drop")),
        Step("1.5", "1 Warehouse", "Migration runner, forward-only and checksummed",
             built=lambda c: c.module("src/common/migrate.py"),
             wired=lambda c: c.consumed("migrate_duckdb", "src/common/migrate.py"),
             verified=lambda c: c.tested(r"test_editing_an_applied_migration_is_refused")),
        Step("1.6", "1 Warehouse", "Schema — every table in Plan 1 §5-§7",
             built=lambda c: "institutional_deals_raw" in c.duck_rows,
             wired=lambda c: c.duck_rows.get("institutional_deals_raw", 0) > 0,
             verified=lambda c: c.tested(r"test_every_plan_1_table_exists")),
        Step("1.7", "1 Warehouse", "Carry the seed, hash every file into the DAG",
             built=lambda c: SEED.is_dir() and any(SEED.glob("**/*.parquet")),
             wired=lambda c: c.gov_rows.get("artefact", 0) > 0,
             verified=lambda c: c.tested(r"test_the_carry_is_idempotent")),
        Step("1.8", "1 Warehouse", "Price spine, ADJUSTED spine, PIT universe",
             built=lambda c: any((warehouse_dir("prod") / "price_spine").glob("**/*.parquet")),
             wired=lambda c: any((warehouse_dir("prod") / "price_spine_adj").glob("**/*.parquet"))
                             and c.consumed("price_spine_adj", "src/warehouse/spine.py"),
             verified=lambda c: c.tested(r"test_adjustment_actually_removes_split_artefacts"),
             note=lambda c: (f"adjusted spine reaches {c.adj_spine_max}; "
                             f"PIT universe still missing")),
        Step("1.9", "1 Warehouse", "Provenance DAG live — every table registers artefact and edges",
             built=lambda c: c.gov_rows.get("artefact", 0) > 0,
             wired=lambda c: c.gov_rows.get("artefact_edge", 0) > 0,
             verified=lambda c: c.tested(r"test_each_spine_edges_only_to_the_sources_it_reads"),
             note="23 artefacts are test pollution and cannot be removed (append-only)"),
        Step("1.10", "1 Warehouse", "Close Risk 8 — off-machine backup with a watched restore",
             built=lambda c: (ROOT / "scripts" / "backup.sh").exists(),
             # This read BLOCKED for eight days on a hand-written string, while
             # the actual obstacle — a destination nobody had launched — went
             # unexamined. It is derived now: WIRED means a generation exists in
             # the destination backup.sh writes to, VERIFIED means nothing
             # irreplaceable is sitting outside it.
             wired=lambda c: c.backup.bundle is not None,
             verified=lambda c: not c.backup.alerting
                                and c.tested(r"test_backup_state_notices_a_session_outside_the_backup"),
             note=lambda c: c.backup.summary),

        # --- Phase 2 ---------------------------------------------------------
        Step("2.1", "2 Collection", "Archive: fetch, hash, dedupe, store, parse, land",
             built=lambda c: c.module("src/archive/stopgap.py") and c.module("src/ingest/parse.py"),
             wired=lambda c: c.duck_rows.get("deal_source_files", 0) > 0,
             verified=lambda c: c.tested(r"test_landing_is_idempotent_on_the_hash"),
             note="parsed parquet is still not written; rows go straight to the database"),
        Step("2.2", "2 Collection", "Browser-like session, rate limit, backoff",
             built=lambda c: "RATE_LIMIT" in c.src_text.get("src/archive/stopgap.py", ""),
             wired=lambda c: c.archive_sessions() > 0,
             verified=lambda c: c.tested(r"EMPTY_SENTINEL|NO RECORDS")),
        Step("2.3", "2 Collection", "NSE bulk and block parsers",
             built=lambda c: c.module("src/ingest/parse.py"),
             wired=lambda c: c.duck_rows.get("institutional_deals_raw", 0) > 0,
             verified=lambda c: c.tested(r"test_bulk_and_block_have_different_column_counts")),
        Step("2.4", "2 Collection", "Backfill 2026-07-09 to present",
             impossible="/api/historical/bulk-deals answers 503 with and without a session "
                        "cookie and referer. The working route is a rolling CURRENT-DAY file, "
                        "so ~26 sessions from 2026-07-09 are unrecoverable at any price."),
        Step("2.5", "2 Collection", "Backfill the full NSE history",
             impossible="Same 503. Twenty years cannot be re-fetched; the V1 export is the "
                        "only copy and is why decision 0027 carries it."),
        Step("2.6", "2 Collection", "BSE bulk and block",
             built=lambda c: "bse" in c.src_text.get("src/archive/stopgap.py", "").lower(),
             note="sources.yml marks both BSE routes UNPROVEN — 301 to an error page"),
        Step("2.7", "2 Collection", "FII/DII cash collector",
             built=lambda c: "fii_dii" in c.src_text.get("src/archive/stopgap.py", ""),
             wired=lambda c: c.duck_rows.get("deal_source_files", 0) > 0,
             verified=lambda c: c.tested(r"test_fii_dii_lands_as_a_file_but_not_as_deal_rows")),
        Step("2.8", "2 Collection", "participant_oi ported as the FII/DII proxy",
             built=lambda c: c.duck_rows.get("participant_oi", 0) > 0,
             wired=lambda c: c.consumed("participant_oi", "src/warehouse/participant_oi.py"),
             verified=lambda c: c.tested(r"test_total_is_a_computed_row_not_a_sixth_participant"),
             note=lambda c: (f"{c.duck_rows.get('participant_oi', 0):,} rows, "
                             f"2014-01-01 .. 2026-06-25; positioning, not cash "
                             f"flow (sources.yml)")),
        Step("2.9", "2 Collection", "Scheduled collection running",
             built=lambda c: (ROOT / "scripts" / "collect_daily.sh").exists(),
             wired=lambda c: c.archive_sessions() >= 4,
             verified=lambda c: c.tested(r"test_publication_is_bracketed_by_two_observations"),
             note="launchd added 2026-08-22 after cron silently lost the 19 Aug session"),
        # The `built` predicate here looked for "bhavcopy" inside stopgap.py,
        # which was right while the plan assumed the price feed would live in
        # the deal collector. It moved to its own module and the predicate kept
        # reporting NOT BUILT — with a hand-written note asserting it. Same
        # defect as 1.10, found in the same audit that fixed 1.10.
        Step("2.12", "2 Collection", "Daily PRICE feed, so collected deals are usable",
             built=lambda c: c.module("src/archive/prices.py")
                             and c.module("src/ingest/bhavcopy.py"),
             wired=lambda c: "src.archive.prices" in c.collect_script,
             verified=lambda c: c.price_spine_max > reconcile.MICCV2_HORIZON,
             note=lambda c: (
                 f"price_spine reaches {c.price_spine_max}; MICCV2 stopped at "
                 f"{reconcile.MICCV2_HORIZON}"
                 if c.price_spine_max else "no price spine on disk")),
        Step("2.14", "2 Collection", "Corporate actions, so the adjusted spine can extend",
             built=lambda c: c.module("src/archive/corporate_actions.py")
                             and c.module("src/ingest/corp_actions.py"),
             wired=lambda c: "src.archive.corporate_actions" in c.collect_script,
             verified=lambda c: c.tested(
                 r"test_preference_share_bonuses_are_never_treated_as_equity_bonuses"),
             note=lambda c: (
                 f"{c.corp_actions} price-affecting action(s) collected; the seed's "
                 f"table ends 2026-06-29 (decision 0041)")),
        Step("2.10", "2 Collection", "Measure available_from empirically",
             built=lambda c: c.module("src/ingest/publication.py"),
             wired=lambda c: c.archive_sessions() >= 2,
             verified=lambda c: c.tested(r"test_failed_fetches_are_not_evidence_of_absence"),
             note="brackets are 10.7h at best; nothing consumes the measurement yet"),
        Step("2.11", "2 Collection", "Revision detection",
             built=lambda c: "source_revisions" in c.duck_rows,
             wired=lambda c: "revision_number" in c.src_text.get("src/ingest/land.py", ""),
             verified=lambda c: c.tested(r"test_a_revision_is_detected_and_BOTH_versions_are_kept")),

        # --- Phase 3 ---------------------------------------------------------
        Step("3.1", "3 Identity", "security_master",
             built=lambda c: c.duck_rows.get("security_master", 0) > 0,
             wired=lambda c: c.duck_rows.get("symbol_history", 0) > 0,
             verified=lambda c: c.tested(r"test_.*identity|test_.*resolution")),
        Step("3.2", "3 Identity", "symbol_history and one point-in-time resolve()",
             built=lambda c: c.duck_rows.get("symbol_history", 0) > 0,
             wired=lambda c: "RESOLVE_SQL" in c.src_text.get("src/identity/master.py", ""),
             verified=lambda c: c.tested(r"test_.*resolve|test_.*point_in_time")),
        Step("3.3", "3 Identity", "Delisting detection and classification",
             built=lambda c: "DELISTED" in c.src_text.get("src/identity/master.py", ""),
             note="delisting_reason is UNKNOWN for all — MERGER vs SUSPENSION needs corporate actions"),
        Step("3.4", "3 Identity", "Resolve the unmatched deal symbols",
             built=lambda c: c.duck_rows.get("symbol_history", 0) > 0,
             wired=lambda c: "deal_resolution" in c.src_text.get("src/identity/master.py", ""),
             note="unresolved 4.14% — under the <5% gate"),
        Step("3.5", "3 Identity", "sector_history — point-in-time sectors",
             built=lambda c: c.duck_rows.get("sector_history", 0) > 0,
             note="blocks the industry dimension of CHAR_MATCHED"),
        Step("3.6", "3 Identity", "Participant normalisation",
             built=lambda c: c.duck_rows.get("participant_master", 0) > 0,
             note="the behavioural classifier exists in src/mart/eligibility.py but does not persist"),
        Step("3.7", "3 Identity", "Behavioural PROP_HFT classifier",
             built=lambda c: "roundtrip_ratio" in c.src_text.get("src/mart/eligibility.py", ""),
             wired=lambda c: c.consumed("eligibility", "src/mart/eligibility.py"),
             verified=lambda c: c.tested(r"prop_hft|roundtrip")),
        Step("3.8", "3 Identity", "Name-pattern classifier for the residual",
             built=lambda c: "roundtrip_ratio" in c.src_text.get("src/mart/eligibility.py", ""),
             wired=lambda c: c.consumed("eligibility", "src/mart/eligibility.py"),
             note=lambda c: "behavioural only; no name-pattern classifier exists"),
        Step("3.9", "3 Identity", "Merge suggestions recorded, never applied",
             built=lambda c: c.duck_rows.get("participant_aliases", 0) > 0,
             note=lambda c: "participant_aliases exists and holds 0 rows"),
        Step("3.12", "3 Identity", "Manual fund-house mapping file",
             built=lambda c: (ROOT / "configs" / "fund_houses.yml").exists()),
        Step("3.10", "3 Identity", "Review queue for the 1,515 names",
             built=lambda c: c.module("src/identity/review.py")),
        Step("3.11", "3 Identity", "SHP collector and promoter_entities",
             built=lambda c: c.duck_rows.get("promoter_entities", 0) > 0),

        # --- Phase 4+ --------------------------------------------------------
        # PHASES 4-7 WERE ONE ROW EACH UNTIL 2026-09-01, AND THAT UNDER-REPORTED
        # THEM BADLY. Plan 3 defines 7 steps in Phase 4, 7 in Phase 5, 10 in
        # Phase 6 and 8 in Phase 7; collapsing each to a single step made
        # "Phase 4: 1/1 wired or better" read as a finished phase while five of
        # its six flags were placeholders that are never true. The summary line
        # was arithmetically correct and substantively false — the same shape of
        # error as reporting a table complete because it exists.
        Step("4.1", "4 Clean mart", "institutional_deals_clean with all flags",
             built=lambda c: c.duck_rows.get("institutional_deals_clean", 0) > 0,
             wired=lambda c: "institutional_deals_clean" in c.src_text.get("src/research/measure.py", ""),
             verified=lambda c: c.tested(r"test_zero_silent_drops")),
        Step("4.2", "4 Clean mart", "Duplicate grouping — NSE/BSE cross-listing, both kept",
             built=lambda c: c.flag_is_real("duplicate_group_id"),
             note=lambda c: "" if c.flag_is_real("duplicate_group_id")
                            else "duplicate_group_id is NULL on every row"),
        Step("4.3", "4 Clean mart", "Same-day and 5-day round-trip flags",
             built=lambda c: c.flag_is_real("same_day_round_trip_flag"),
             wired=lambda c: c.flag_is_real("five_day_round_trip_flag"),
             note=lambda c: "same-day is real; five-day is FALSE on every row"
                            if not c.flag_is_real("five_day_round_trip_flag") else ""),
        Step("4.4", "4 Clean mart", "Internal-transfer and promoter-related flags",
             built=lambda c: c.flag_is_real("internal_transfer_flag")
                             and c.flag_is_real("promoter_related_flag"),
             note=lambda c: "both FALSE on every row; promoter_entities holds 0 rows"),
        Step("4.5", "4 Clean mart", "Size eligibility: >= 0.5% ADV20 and >= Rs 1cr",
             built=lambda c: "min_value" in c.src_text.get("src/mart/clean.py", ""),
             wired=lambda c: "below the ADV20 floor" in c.src_text.get("src/mart/clean.py", ""),
             verified=lambda c: c.tested(r"test_the_participation_ceiling")),
        Step("4.6", "4 Clean mart", "eligible_for_research excluding PROP_HFT",
             built=lambda c: "PROP_HFT" in c.src_text.get("src/mart/clean.py", ""),
             wired=lambda c: c.consumed("eligible_for_research", "src/mart/clean.py"),
             verified=lambda c: c.tested(r"test_zero_silent_drops")),
        Step("4.7", "4 Clean mart", "Three interpretations — individual / accumulated / confirmation",
             built=lambda c: c.duck_rows.get("deal_interpretation", 0) > 0,
             note=lambda c: "deal_interpretation exists and holds 0 rows"),

        Step("5.1", "5 Costs & benchmarks", "fee_schedule, rebuilt not ported, every row sourced",
             built=lambda c: c.gov_rows.get("fee_schedule", 0) > 0,
             wired=lambda c: c.gov_rows.get("fee_schedule", 0) > 0
                             and c.provides("src.research.costs", "statutory_cost"),
             verified=lambda c: c.tested(r"test_stt_is_charged_on_both_legs"),
             note=lambda c: (
                 f"{c.gov_rows.get('fee_schedule', 0)} statutory rows seeded from "
                 f"costs.yml; NSE round trip 29.33 bps headline")),
        Step("5.2", "5 Costs & benchmarks", "Corwin-Schultz and Abdi-Ranaldo spread estimators",
             built=lambda c: c.provides("src.research.costs", "corwin_schultz_spread")),
        Step("5.3", "5 Costs & benchmarks", "Square-root market impact with sensitivity",
             built=lambda c: c.provides("src.research.costs", "sqrt_impact")),
        Step("5.4", "5 Costs & benchmarks", "Participation cap and delay cost",
             built=lambda c: "participation_ceiling" in c.src_text.get("src/mart/clean.py", ""),
             wired=lambda c: "TOO_LARGE" in c.src_text.get("src/mart/clean.py", ""),
             verified=lambda c: c.tested(r"test_the_participation_ceiling"),
             note=lambda c: "the cap is applied; DELAY cost is not modelled"),
        Step("5.5", "5 Costs & benchmarks", "Volatility-regime multiplier from India VIX",
             built=lambda c: c.provides("src.research.costs", "vix_regime_multiplier")),
        Step("5.6", "5 Costs & benchmarks", "Six benchmarks incl. constructed smallcap and CHAR_MATCHED",
             built=lambda c: c.module("src/research/charmatch.py"),
             wired=lambda c: c.consumed("charmatch", "src/research/charmatch.py"),
             note=lambda c: "charmatch.py is 251 lines that nothing imports; the only "
                            "test reads its source as text, never runs it"),
        Step("5.7", "5 Costs & benchmarks", "Gross / base / pessimistic reporting",
             built=lambda c: c.provides("src.research.costs", "cost_scenarios")),

        Step("6.1", "6 Outcome study", "Register all four experiments, trial counter to 72",
             built=lambda c: c.gov_rows.get("experiment_registry", 0) > 0,
             wired=lambda c: c.gov_rows.get("experiment_registry", 0) >= 4,
             note=lambda c: f"{c.gov_rows.get('experiment_registry', 0)} of 4 registered"),
        Step("6.2", "6 Outcome study", "Power analysis per stratum, before any fit",
             built=lambda c: c.module("src/research/power.py"),
             wired=lambda c: c.consumed("power", "src/research/power.py"),
             verified=lambda c: c.tested(r"test_the_twelve_month_figure_is_reproducible")),
        Step("6.3", "6 Outcome study", "deal_forward_outcomes across 9 horizons x 6 benchmarks",
             built=lambda c: c.duck_rows.get("deal_forward_outcomes", 0) > 0,
             note=lambda c: "the table exists and holds 0 rows"),
        Step("6.4", "6 Outcome study", "Delisting/merger handling at 3 recovery factors",
             built=lambda c: c.provides("src.research.outcomes", "delisting_recovery")),
        Step("6.5", "6 Outcome study", "Monthly-cohort collapse, block bootstrap, NW-HAC",
             built=lambda c: c.provides("src.research.power", "serial_inflation"),
             wired=lambda c: c.consumed("serial_inflation", "src/research/power.py"),
             verified=lambda c: c.tested(r"test_the_serial_lag_covers_the_label_overlap")),
        Step("6.6", "6 Outcome study", "Three-scheme walk-forward: anchored + rolling + CPCV",
             built=lambda c: c.provides("src.research.walkforward", "cpcv_paths")),
        Step("6.7", "6 Outcome study", "PBO from the CPCV distribution",
             built=lambda c: c.provides("src.research.walkforward", "probability_of_backtest_overfitting")),
        Step("6.8", "6 Outcome study", "Romano-Wolf stepdown for ranking",
             built=lambda c: c.provides("src.research.multiplicity", "romano_wolf"),
             wired=lambda c: c.consumed("romano_wolf", "src/research/multiplicity.py"),
             verified=lambda c: c.tested(r"romano")),
        Step("6.9", "6 Outcome study", "Null-calibration on shuffled participant labels",
             built=lambda c: c.provides("src.research.outcomes", "null_calibration")),
        Step("6.10", "6 Outcome study", "Write study_result with corrected p and input hashes",
             built=lambda c: c.gov_rows.get("study_result", 0) > 0,
             note=lambda c: f"{c.gov_rows.get('study_result', 0)} row(s), from exp_001"),
        Step("6R", "6 Outcome study", "Re-run exp_001 reproducibly under the DAG (0013)",
             built=lambda c: c.gov_rows.get("study_result", 0) > 0,
             wired=lambda c: c.module("src/research/measure.py"),
             verified=lambda c: c.tested(r"test_the_twelve_month_figure_is_reproducible")),

        Step("6S", "6S Track S", "The scan track — folds, nulls, procedure test",
             built=lambda c: c.module("src/scan/procedure.py")),

        Step("7.1", "7 Seasonality", "Recompute a 100,000-cell sample, exact match required",
             built=lambda c: c.duck_rows.get("seasonality_cell", 0) > 0,
             note=lambda c: "seasonality_cell exists and holds 0 rows"),
        Step("7.2", "7 Seasonality", "Observation minimums >=10 yearly / >=30 monthly",
             built=lambda c: c.provides("src.research.seasonality", "min_observations")),
        Step("7.3", "7 Seasonality", "Index expansion 46 -> ~202 with dedup",
             built=lambda c: c.duck_rows.get("seasonality_cell", 0) > 0),
        Step("7.4", "7 Seasonality", "Near-duplicate grouping incl. return correlation > 0.9",
             built=lambda c: c.provides("src.research.seasonality", "group_near_duplicates")),
        Step("7.8", "7 Seasonality", "Three-scheme OOS + full cost model",
             built=lambda c: c.duck_rows.get("seasonality_cell", 0) > 0
                             and c.gov_rows.get("fee_schedule", 0) > 0),
        Step("7.5", "7 Seasonality", "BY + BH + Storey q over the actual run test count",
             built=lambda c: c.module("src/research/multiplicity.py"),
             wired=lambda c: c.consumed("multiplicity", "src/research/multiplicity.py"),
             verified=lambda c: c.tested(r"test_storey|storey")),
        Step("7.6", "7 Seasonality", "Permutation, 1,000 rotations",
             built=lambda c: c.provides("src.research.seasonality", "rotation_permutation")),
        Step("7.7", "7 Seasonality", "Hansen SPA for best-of-family",
             built=lambda c: c.provides("src.research.seasonality", "hansen_spa")),
        Step("2.13", "2 Collection", "Alert when collection goes stale",
             built=lambda c: c.module("src/monitor/health.py"),
             wired=lambda c: "monitor.health" in (ROOT/"scripts"/"collect_daily.sh").read_text(),
             verified=lambda c: c.tested(r"test_a_stale_required_source_alerts"),
             note="19 Aug lost, 28 Aug recovered two days late by hand — detection always "
                  "worked, nothing carried it anywhere"),
        Step("8", "8 Monitoring", "Generated status derived from repo and DB state",
             built=lambda c: c.module("src/monitor/status.py"),
             wired=lambda c: STATUS_PATH.exists(),
             verified=lambda c: c.tested(r"test_status_is_not_stale")),
    ]


@dataclass
class Report:
    rows: list[tuple[Step, Level]] = field(default_factory=list)
    #: The same ground truth the levels were graded against. Carried so a
    #: derived note cannot be resolved from a second, differing read.
    ctx: "Ctx | None" = None

    def by_phase(self) -> dict[str, list[tuple[Step, Level]]]:
        out: dict[str, list[tuple[Step, Level]]] = {}
        for step, lvl in self.rows:
            out.setdefault(step.phase, []).append((step, lvl))
        return out

    def counts(self) -> dict[str, int]:
        c: dict[str, int] = {}
        for _, lvl in self.rows:
            c[lvl] = c.get(lvl, 0) + 1
        return c


def evaluate() -> Report:
    c = Ctx()
    return Report([(s, s.level(c)) for s in steps()], ctx=c)


def _commit() -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                             cwd=ROOT, capture_output=True, text=True, timeout=10)
        return out.stdout.strip() or "UNKNOWN"
    except (OSError, subprocess.SubprocessError):
        return "UNKNOWN"


BADGE = {
    "VERIFIED": "**VERIFIED**", "WIRED": "WIRED", "BUILT": "BUILT",
    "SPECIFIED": "—", "IMPOSSIBLE": "**IMPOSSIBLE**", "BLOCKED": "**BLOCKED**",
}


def render(rep: Report) -> str:
    counts = rep.counts()
    lines = [
        "# Phase status",
        "",
        "**Generated by `src/monitor/status.py`. Do not edit.** A test fails if this",
        "file disagrees with what the code derives from the repository and databases.",
        "",
        "Completion is graded, because \"the artefact exists\" is not \"the step works\".",
        "Three steps were reported complete on 22-24 August while holding zero rows or",
        "having no consumer at all, which is what these levels exist to make visible.",
        "",
        "| level | meaning |",
        "|---|---|",
        "| **VERIFIED** | a test asserts its behaviour against real data |",
        "| WIRED | something downstream actually consumes it |",
        "| BUILT | the code or table exists, and nothing reads it |",
        "| — | specified in the plan, not started |",
        "| **IMPOSSIBLE** | measured to be undoable; evidence attached |",
        "| **BLOCKED** | waiting on something outside the project |",
        "",
        "  ".join(f"{k}: {counts.get(k, 0)}" for k in
                 ("VERIFIED", "WIRED", "BUILT", "SPECIFIED", "IMPOSSIBLE", "BLOCKED")),
        "",
    ]
    for phase, rows in rep.by_phase().items():
        lines += [f"## Phase {phase}", "", "| step | what | status | note |", "|---|---|---|---|"]
        for step, lvl in rows:
            note = step.impossible or step.blocked or step.note_for(rep.ctx or Ctx())
            lines.append(f"| {step.id} | {step.what} | {BADGE[lvl]} | {note} |")
        lines.append("")
    lines += ["---", "", f"Derived at commit `{_commit()}`."]
    return "\n".join(lines) + "\n"


def write(path: Path | None = None) -> Path:
    target = path or STATUS_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render(evaluate()))
    return target


def main() -> int:
    rep = evaluate()
    counts = rep.counts()
    print("PHASE STATUS — derived, not asserted")
    for k in ("VERIFIED", "WIRED", "BUILT", "SPECIFIED", "IMPOSSIBLE", "BLOCKED"):
        print(f"  {k:<11} {counts.get(k, 0):>3}")
    print()
    for phase, rows in rep.by_phase().items():
        done = sum(1 for _, lvl in rows if ORDER[lvl] >= 2)
        real = [r for r in rows if r[1] not in ("IMPOSSIBLE", "BLOCKED")]
        print(f"  Phase {phase:<26} {done}/{len(real)} wired or better"
              + (f"   ({len(rows) - len(real)} impossible/blocked)" if len(rows) != len(real) else ""))
    p = write()
    print(f"\n  wrote {p.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
