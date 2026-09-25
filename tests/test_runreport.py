"""The per-run report, and the once-a-day gate that replaced a clock check.

A clean run used to produce nothing anywhere a person looks. That sounds
efficient until you notice that both of this project's real data losses — 19
August and 10-15 September — looked exactly like a quiet, working collector.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from src.monitor import digest, runreport

pytestmark = pytest.mark.unit


def _tsv(tmp_path, started="2026-09-16T15:00:00+00:00", rows=(("deals", 0, 3),), finished=True):
    p = tmp_path / "last_run.tsv"
    p.write_text(f"# started {started}\n"
                 + "".join(f"{n}\t{c}\t{s}\n" for n, c, s in rows)
                 + ("# finished 2026-09-16T15:10:00+00:00\n" if finished else ""))
    return p


# --- reading the run record ---------------------------------------------------


def test_stages_exit_codes_and_timing_come_back_as_data(tmp_path):
    run = runreport.read_run(_tsv(tmp_path, rows=[("deals", 0, 3), ("mart", 1, 97)]))
    assert [s.name for s in run.stages] == ["deals", "mart"]
    assert [s.ok for s in run.stages] == [True, False]
    assert run.elapsed == 100
    assert [s.name for s in run.failed] == ["mart"]


def test_a_run_that_died_mid_stage_still_parses(tmp_path):
    """The partial file is the MOST useful state this can be in — it names the
    stage that never returned. Parsing strictly and raising would throw it away."""
    p = tmp_path / "last_run.tsv"
    # THREE SHAPES OF DAMAGE, because the first version of this test used only
    # the second one — a short line, which is caught by the field count and
    # never reaches the int() that the "tolerates a truncated file" claim is
    # really about. Removing the ValueError guard left it green.
    p.write_text("# started 2026-09-16T15:00:00+00:00\n"
                 "deals\t0\t3\n"
                 "prices\t0\n"            # cut mid-line
                 "mart\tKILLED\t9\n"      # a code that is not a number
                 "spine\t0\tages\n")      # a duration that is not a number
    run = runreport.read_run(p)
    assert [s.name for s in run.stages] == ["deals"]
    assert run.started is not None


def test_a_missing_record_is_not_an_error(tmp_path):
    run = runreport.read_run(tmp_path / "nope.tsv")
    assert run.stages == [] and run.started is None
    assert "No stage record found" in runreport.render(run)


def test_an_unparseable_start_line_does_not_lose_the_stages(tmp_path):
    p = tmp_path / "last_run.tsv"
    p.write_text("# started not-a-timestamp\nexit\t0\t3\n")
    run = runreport.read_run(p)
    assert run.started is None
    assert len(run.stages) == 1


# --- what this run collected --------------------------------------------------


def test_collected_since_returns_nothing_when_the_start_is_unknown(tmp_path, monkeypatch):
    """"Everything ever archived" is not an answer to "what did this run do",
    and printing 40,000 rows into a phone message is worse than printing none."""
    assert runreport.collected_since(None) == []


def test_only_rows_written_after_the_run_started_are_counted(tmp_path, monkeypatch):
    import json

    start = datetime(2026, 9, 16, 15, 0, tzinfo=UTC)
    man = tmp_path / "manifest.jsonl"
    man.write_text("\n".join(json.dumps(r) for r in [
        {"source_id": "old", "fetched_at": (start - timedelta(minutes=1)).isoformat()},
        {"source_id": "new", "fetched_at": start.isoformat()},
        {"source_id": "newer", "fetched_at": (start + timedelta(minutes=5)).isoformat()},
        {"source_id": "broken"},
    ]))
    monkeypatch.setattr(runreport, "ARCHIVE", tmp_path)
    got = [r["source_id"] for r in runreport.collected_since(start)]
    assert got == ["new", "newer"]


# --- the report ---------------------------------------------------------------


def test_a_failed_collection_stage_is_called_out_separately_from_processing(
        tmp_path, monkeypatch):
    """The distinction that decides whether the operator acts NOW or tomorrow.
    A rolling NSE feed is recoverable only until the file turns over."""
    monkeypatch.setattr(runreport, "RUN_TSV",
                        _tsv(tmp_path, rows=[("prices", 1, 4), ("mart", 1, 9)]))
    monkeypatch.setattr(runreport, "ARCHIVE", tmp_path)
    text = runreport.render()
    assert "COLLECTION FAILED: prices" in text
    assert "PROCESSING FAILED: mart" in text
    assert text.index("COLLECTION FAILED") < text.index("PROCESSING FAILED")


def test_a_clean_run_says_so_without_naming_a_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(runreport, "RUN_TSV",
                        _tsv(tmp_path, rows=[("deals", 0, 3), ("mart", 0, 97)]))
    monkeypatch.setattr(runreport, "ARCHIVE", tmp_path)
    text = runreport.render()
    assert "ALL CLEAN" in text
    assert "FAILED" not in text


# --- the once-a-day gate ------------------------------------------------------


def test_the_digest_is_due_once_per_day_and_not_twice(tmp_path):
    stamp = tmp_path / "stamp"
    day = date(2026, 9, 16)
    assert digest.due(day, stamp)
    digest.mark(day, stamp)
    assert not digest.due(day, stamp)
    assert digest.due(date(2026, 9, 17), stamp)


def test_a_missing_stamp_means_due(tmp_path):
    """Erring toward a duplicate digest costs one message. Erring the other way
    costs the day's only report."""
    assert digest.due(date(2026, 9, 16), tmp_path / "never-written")


def test_an_unreadable_stamp_means_due(tmp_path):
    """A directory where a file should be. `due` must not raise INTO a collector
    run, and must not answer "already sent"."""
    d = tmp_path / "stamp"
    d.mkdir()
    assert digest.due(date(2026, 9, 16), d)


def test_marking_never_raises_when_the_stamp_cannot_be_written(tmp_path):
    """A digest that was SENT must not be reported as failed because a stamp
    file could not be written."""
    d = tmp_path / "stamp"
    d.mkdir()
    digest.mark(date(2026, 9, 16), d)  # must not raise


# --- a real defect, found from an actual Telegram reply ----------------------


def test_the_at_risk_flag_never_runs_into_the_word_backup(tmp_path, monkeypatch):
    """A live /status reply read "AT RISKbackup" with nothing between them.

    `f"{flag:<6}{'backup':<22}"` relies on padding INSIDE the width to supply
    the separator, and "AT RISK" is 7 characters — one past that width. When a
    field's content is already at or past its width, str.format adds no
    padding at all, so two adjacent format fields with no literal character
    between them can fuse with zero separation. "ok    " (6 chars, hand-padded)
    happened to fit; "AT RISK" did not.
    """
    from src.monitor import backup_state

    monkeypatch.setattr(runreport, "RUN_TSV",
                        _tsv(tmp_path, rows=[("deals", 0, 3)]))
    monkeypatch.setattr(runreport, "ARCHIVE", tmp_path)
    at_risk = backup_state.BackupState(
        destination=tmp_path, bundle=None, taken_at=None,
        commits_behind=0, sessions_at_risk=3, generations=0,
    )
    monkeypatch.setattr(backup_state, "read", lambda: at_risk)
    text = runreport.render()
    assert "AT RISKbackup" not in text
    assert "AT RISK  backup" in text or "AT RISK backup" in text


# --- the collection branch: the 2026-09-17 false alarm ------------------------


def test_a_failed_deals_stage_with_the_session_held_does_not_say_re_run(tmp_path, monkeypatch):
    from src.monitor import health

    monkeypatch.setattr(runreport, "RUN_TSV", _tsv(tmp_path, rows=[("deals", 1, 3020)]))
    monkeypatch.setattr(runreport, "ARCHIVE", tmp_path)
    monkeypatch.setattr(health, "rolling_exposure", lambda rows=None: [
        (s, False, "newest held 2026-09-16 is what the endpoint is serving; nothing at risk, the next slot retries")
        for s in health.ROLLING])
    text = runreport.render()
    assert "COLLECTION FAILED: deals" in text
    assert "held     nse_bulk_deals" in text
    assert "Nothing on the endpoint is missing" in text
    assert "Re-run" not in text and "turns over" not in text


def test_a_failed_deals_stage_with_the_session_missing_says_re_run(tmp_path, monkeypatch):
    from src.monitor import health

    monkeypatch.setattr(runreport, "RUN_TSV", _tsv(tmp_path, rows=[("deals", 1, 30)]))
    monkeypatch.setattr(runreport, "ARCHIVE", tmp_path)
    monkeypatch.setattr(health, "rolling_exposure", lambda rows=None: [
        ("nse_bulk_deals", True, "newest held 2026-09-15; the endpoint is serving 2026-09-16, which is NOT held — Fetch now"),
        ("nse_block_deals", False, "nothing at risk"),
        ("fii_dii_cash", False, "nothing at risk")])
    text = runreport.render()
    assert "AT RISK  nse_bulk_deals" in text
    assert "Re-run: /collect" in text


def test_a_dated_feed_asked_before_publish_reads_as_not_yet_published(tmp_path, monkeypatch):
    """Three feeds read "no result" on every morning run. PENDING is a fact
    about the exchange — the file does not exist yet — not a missing result."""
    import json

    start = datetime(2026, 9, 17, 3, 0, tzinfo=UTC)
    (tmp_path / "manifest.jsonl").write_text("\n".join(json.dumps(r) for r in [
        {"source_id": "nse_fo_bhavcopy", "status": "PENDING", "session_date": "2026-09-17",
         "fetched_at": (start + timedelta(minutes=5)).isoformat()},
        {"source_id": "nse_bhavcopy", "status": "NO_SESSION", "session_date": "2026-09-14",
         "fetched_at": (start + timedelta(minutes=5)).isoformat()},
    ]))
    monkeypatch.setattr(runreport, "RUN_TSV",
                        _tsv(tmp_path, started=start.isoformat(), rows=[("deals", 0, 3)]))
    monkeypatch.setattr(runreport, "ARCHIVE", tmp_path)
    text = runreport.render()
    assert "nse_fo_bhavcopy        2026-09-17 not yet published" in text
    assert "nse_bhavcopy           1 no session (holiday)" in text
    assert "no result" not in text


def test_the_legacy_stage_name_is_read_as_the_current_one(tmp_path, monkeypatch):
    """Every record before 2026-09-17 says `exit`. The morning the rename
    landed, that day's own record read as a PROCESSING failure."""
    from src.monitor import health

    monkeypatch.setattr(runreport, "RUN_TSV", _tsv(tmp_path, rows=[("exit", 1, 3020)]))
    monkeypatch.setattr(runreport, "ARCHIVE", tmp_path)
    monkeypatch.setattr(health, "rolling_exposure",
                        lambda rows=None: [(s, False, "nothing at risk") for s in health.ROLLING])
    text = runreport.render()
    assert "COLLECTION FAILED: deals" in text
    assert "PROCESSING FAILED" not in text
    assert "FAIL  deals" in text


def test_a_run_that_stopped_on_its_own_clock_says_so_instead_of_no_record(tmp_path, monkeypatch):
    """A STOPPED row falls through every bucket — not held, not FAILED, not
    PENDING — so the feed rendered as "no record", which reads as a feed that
    did nothing on a night it did 45 minutes of work and has a backlog left.
    The stop is not a failure and must not page; it is also not nothing."""
    import json

    start = datetime(2026, 9, 20, 3, 0, tzinfo=UTC)
    (tmp_path / "manifest.jsonl").write_text("\n".join(json.dumps(r) for r in [
        {"source_id": "nse_insider_pit", "status": "STORED", "bytes": 7000,
         "fetched_at": (start + timedelta(minutes=1)).isoformat()},
        {"source_id": "nse_insider_pit", "status": "STOPPED",
         "note": "run stopped — wall clock: 45 min reached after 1 window(s)",
         "fetched_at": (start + timedelta(minutes=45)).isoformat()},
    ]))
    monkeypatch.setattr(runreport, "RUN_TSV",
                        _tsv(tmp_path, started=start.isoformat(), rows=[("insider", 0, 2700)]))
    monkeypatch.setattr(runreport, "ARCHIVE", tmp_path)
    text = runreport.render()
    assert "STOPPED — wall clock: 45 min reached" in text
    assert "no record" not in text
    # A stop is not a failure: the run is still ALL CLEAN and nothing pages.
    assert "ALL CLEAN" in text and "COLLECTION FAILED" not in text


# --- a run in flight is not a verdict (2026-09-25) --------------------------------


def test_a_run_still_in_flight_says_in_progress_not_failed(tmp_path, monkeypatch):
    """/status sent mid-run on 09-25 answered "FAILED — 4 stages in 73m" for a
    run with nineteen stages still to go. A partial record is not a verdict."""
    monkeypatch.setattr(runreport, "RUN_TSV",
                        _tsv(tmp_path, rows=[("deals", 1, 4396), ("prices", 0, 1)], finished=False))
    monkeypatch.setattr(runreport, "ARCHIVE", tmp_path)
    monkeypatch.setattr(runreport, "collector_running", lambda: True)
    text = runreport.render()
    assert "IN PROGRESS" in text and "1 failed so far" in text
    assert "FAILED — " not in text and "ALL CLEAN" not in text


def test_a_run_that_died_says_incomplete_and_names_the_last_stage(tmp_path, monkeypatch):
    monkeypatch.setattr(runreport, "RUN_TSV",
                        _tsv(tmp_path, rows=[("deals", 0, 3), ("prices", 0, 1)], finished=False))
    monkeypatch.setattr(runreport, "ARCHIVE", tmp_path)
    monkeypatch.setattr(runreport, "collector_running", lambda: False)
    text = runreport.render()
    assert "INCOMPLETE" in text and "last: prices" in text
    assert "ALL CLEAN" not in text


def test_an_old_record_without_the_marker_is_finished_if_backup_ran(tmp_path):
    """Records from before the `# finished` line existed must not all read as
    incomplete: `backup` has always been the last stage noted."""
    run = runreport.read_run(_tsv(tmp_path, rows=[("deals", 0, 3), ("backup", 0, 40)], finished=False))
    assert run.finished
    run = runreport.read_run(_tsv(tmp_path, rows=[("deals", 0, 3)], finished=False))
    assert not run.finished
