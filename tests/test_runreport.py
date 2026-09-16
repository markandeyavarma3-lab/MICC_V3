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


def _tsv(tmp_path, started="2026-09-16T15:00:00+00:00", rows=(("exit", 0, 3),)):
    p = tmp_path / "last_run.tsv"
    p.write_text(f"# started {started}\n"
                 + "".join(f"{n}\t{c}\t{s}\n" for n, c, s in rows))
    return p


# --- reading the run record ---------------------------------------------------


def test_stages_exit_codes_and_timing_come_back_as_data(tmp_path):
    run = runreport.read_run(_tsv(tmp_path, rows=[("exit", 0, 3), ("mart", 1, 97)]))
    assert [s.name for s in run.stages] == ["exit", "mart"]
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
                 "exit\t0\t3\n"
                 "prices\t0\n"            # cut mid-line
                 "mart\tKILLED\t9\n"      # a code that is not a number
                 "spine\t0\tages\n")      # a duration that is not a number
    run = runreport.read_run(p)
    assert [s.name for s in run.stages] == ["exit"]
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
                        _tsv(tmp_path, rows=[("exit", 0, 3), ("mart", 0, 97)]))
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
                        _tsv(tmp_path, rows=[("exit", 0, 3)]))
    monkeypatch.setattr(runreport, "ARCHIVE", tmp_path)
    at_risk = backup_state.BackupState(
        destination=tmp_path, bundle=None, taken_at=None,
        commits_behind=0, sessions_at_risk=3, generations=0,
    )
    monkeypatch.setattr(backup_state, "read", lambda: at_risk)
    text = runreport.render()
    assert "AT RISKbackup" not in text
    assert "AT RISK  backup" in text or "AT RISK backup" in text
