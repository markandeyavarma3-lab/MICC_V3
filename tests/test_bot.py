"""The command surface, which is the only inbound path into this machine.

Everything else in this project is a reader or a scheduled writer. This is a
door, and the tests below are about the door rather than about the reports it
serves: what it refuses, what it never passes to a shell, and what it does when
a handler dies.
"""

from __future__ import annotations

import pytest

from src.monitor import bot

pytestmark = pytest.mark.unit


# --- the allowlist ------------------------------------------------------------


def test_an_unknown_command_gets_help_and_does_not_run_anything():
    reply = bot.handle("/rm -rf /")
    assert "unknown command" in reply
    assert "/status" in reply  # it fell through to help


def test_plain_text_is_not_a_command():
    assert "unknown command" in bot.handle("please run the collector")


def test_the_group_suffix_telegram_appends_is_stripped():
    """In a group Telegram sends `/status@mybotname`. Without stripping, every
    command sent from a group would read as unknown."""
    assert bot.handle("/help@some_bot") == bot.handle("/help")


def test_every_allowlisted_command_is_a_callable_taking_one_argument():
    for name, fn in bot.COMMANDS.items():
        assert name.startswith("/")
        assert callable(fn)


def test_no_command_can_name_a_path_or_reach_a_shell():
    """The property that matters, asserted over the whole allowlist rather than
    one handler: every entry takes a parsed word list, and the only handler that
    starts a process passes a fixed argv. If a future command takes a filename,
    this test is where that decision should have to be argued."""
    import inspect

    for name, fn in bot.COMMANDS.items():
        src = inspect.getsource(fn)
        assert "shell=True" not in src, name
        assert "os.system" not in src, name
        assert "eval(" not in src, name


# --- the one argument the bot accepts ----------------------------------------


def test_log_rejects_a_non_numeric_argument_without_touching_it():
    reply = bot.cmd_log(["; rm -rf ~"])
    assert "is not a number" in reply


def test_log_clamps_its_line_count(tmp_path, monkeypatch):
    monkeypatch.setattr(bot, "LOGS", tmp_path)
    (tmp_path / "collect_2026-09.log").write_text("\n".join(str(i) for i in range(5000)))
    assert "last 200 line(s)" in bot.cmd_log(["999999"])
    assert "last 1 line(s)" in bot.cmd_log(["0"])
    assert "last 1 line(s)" in bot.cmd_log(["-5"])


def test_log_says_so_when_there_is_no_log(tmp_path, monkeypatch):
    monkeypatch.setattr(bot, "LOGS", tmp_path)
    assert "no collector log" in bot.cmd_log([])


# --- the command with teeth ---------------------------------------------------


def test_collect_refuses_to_start_a_second_run(monkeypatch):
    """0059 retired cron because two runs seconds apart collided on DuckDB's
    exclusive write lock and failed every slot. A /collect sent while the 20:30
    job is working would rebuild that failure from a phone."""
    started = []
    monkeypatch.setattr(bot, "_running", lambda: True)
    monkeypatch.setattr(bot.subprocess, "Popen", lambda *a, **k: started.append(a))
    reply = bot.handle("/collect")
    assert "already in flight" in reply
    assert not started


def test_collect_starts_the_script_by_fixed_argv_with_no_shell(monkeypatch):
    seen = {}

    def fake_popen(argv, **kwargs):
        seen["argv"], seen["kwargs"] = argv, kwargs

    monkeypatch.setattr(bot, "_running", lambda: False)
    monkeypatch.setattr(bot.subprocess, "Popen", fake_popen)
    assert "started" in bot.handle("/collect extra words ignored")
    assert seen["argv"] == [str(bot.COLLECT)]     # a LIST, and nothing from the message
    assert "shell" not in seen["kwargs"]
    assert seen["kwargs"]["start_new_session"] is True


# --- failure behaviour --------------------------------------------------------


def test_a_handler_that_raises_answers_with_the_reason(monkeypatch):
    """A silent bot is indistinguishable from a bot whose machine is off, which
    is the exact ambiguity this channel exists to remove."""
    monkeypatch.setitem(bot.COMMANDS, "/boom",
                        lambda _: (_ for _ in ()).throw(RuntimeError("no db")))
    reply = bot.handle("/boom")
    assert "/boom failed" in reply
    assert "RuntimeError" in reply and "no db" in reply
