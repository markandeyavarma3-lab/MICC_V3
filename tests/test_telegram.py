"""The Telegram channel, and the four things that must not go wrong with it.

This channel is different from the two before it. The desktop notification can
only reach this machine and email only ever left this machine; a bot accepts
INBOUND traffic from anyone who learns its username, and this repository is
public. The tests that matter here are not "does it format nicely" but:

  the token never escapes into a string anyone can read;
  a chat that is not the owner's is not served;
  a message too long for the API is split without mangling a table;
  nothing in the module raises into a caller that is already failing.
"""

from __future__ import annotations

import pytest

from src.monitor import telegram

pytestmark = pytest.mark.unit


@pytest.fixture
def token(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:SECRET-TOKEN-VALUE")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "99887766")
    return "123456:SECRET-TOKEN-VALUE"


# --- the credential -----------------------------------------------------------


def test_the_token_is_scrubbed_from_anything_the_module_returns(token):
    """The token is IN THE URL. urllib prints the URL it was fetching in some
    error paths, and this project's logs are read, pasted and screenshotted."""
    leaked = f"failed fetching https://api.telegram.org/bot{token}/getMe"
    assert token not in telegram._scrub(leaked)
    assert "<token>" in telegram._scrub(leaked)


def test_a_token_file_is_read_and_preferred_only_when_the_env_var_is_absent(
        tmp_path, monkeypatch):
    f = tmp_path / "tok"
    f.write_text("  file-token\n")
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_FILE", str(f))
    assert telegram.token() == "file-token"
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "env-token")
    assert telegram.token() == "env-token"


def test_a_missing_token_file_is_not_an_error(tmp_path, monkeypatch):
    """Absent config must degrade to "not configured", never to a traceback in
    the middle of a collector run that was already reporting a failure."""
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_FILE", str(tmp_path / "nope"))
    assert telegram.token() is None
    assert not telegram.configured()
    assert "not configured" in telegram.send("hello")


# --- the authorization boundary ----------------------------------------------


def test_only_the_configured_chat_is_authorized(token):
    assert telegram.authorized("99887766")
    assert not telegram.authorized("99887767")
    assert not telegram.authorized("")
    assert not telegram.authorized(None)


def test_a_numeric_chat_id_matches_the_string_in_the_environment(token):
    """Telegram sends chat ids as JSON NUMBERS and the environment holds a
    string. A bare `!=` would lock the owner out of their own bot."""
    assert telegram.authorized(99887766)


def test_nobody_is_authorized_when_no_chat_is_configured(monkeypatch):
    """The dangerous direction. If TELEGRAM_CHAT_ID is unset, `authorized` must
    deny everyone rather than treating "unset" as "no restriction".

    THE THIRD CASE IS THE ONLY ONE THAT BITES, and this test was written without
    it and passed anyway. With no owner configured the comparison is against the
    string "None", so a real chat id and an empty string both fail it on their
    own. An update carrying NO chat id at all stringifies to "None" too — and
    "None" == "None" authorizes a malformed update from anywhere. Verified by
    removing the `bool(owner)` guard: with only the first two assertions this
    test stayed green.
    """
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    assert not telegram.authorized("99887766")
    assert not telegram.authorized("")
    assert not telegram.authorized(None)
    assert not telegram.authorized("None")


# --- chunking -----------------------------------------------------------------


def test_every_chunk_fits_and_no_line_is_split(token):
    text = "\n".join(f"  {i:<20} {'x' * 40}" for i in range(400))
    parts = telegram.chunks(text, limit=500)
    assert len(parts) > 1
    assert all(len(p) <= 500 for p in parts)
    # The report is a fixed-width table. A chunk boundary inside a row would
    # hand the reader a misaligned table and call it a status report.
    rejoined = "\n".join(parts)
    assert rejoined.split("\n") == text.split("\n")


def test_a_single_line_longer_than_the_limit_is_cut_rather_than_dropped(token):
    parts = telegram.chunks("a" * 250, limit=100)
    assert all(len(p) <= 100 for p in parts)
    assert "".join(parts) == "a" * 250


def test_chunking_empty_text_yields_one_empty_chunk(token):
    assert telegram.chunks("") == [""]


# --- HTML -----------------------------------------------------------------


def test_the_characters_that_break_telegrams_parser_are_escaped(token):
    """Not cosmetic. An unescaped `<` makes Telegram reject the WHOLE message
    with "can't parse entities", so the alert containing a stack trace — the one
    that mattered most — is the one that never arrives."""
    assert telegram._escape("a <b> & c") == "a &lt;b&gt; &amp; c"


# --- failure behaviour --------------------------------------------------------


def test_send_reports_the_failure_instead_of_raising(token, monkeypatch):
    def boom(*a, **k):
        raise telegram.TelegramError("HTTP 400: chat not found")

    monkeypatch.setattr(telegram, "call", boom)
    result = telegram.send("anything")
    assert "FAILED" in result
    assert "chat not found" in result


def test_send_names_how_many_parts_got_through_before_it_broke(token, monkeypatch):
    """A partial send is not a failed send, and an operator who sees "FAILED"
    after four of five chunks arrived will go looking for a message that is
    already on their phone."""
    calls = []

    def flaky(method, params=None, timeout=20):
        calls.append(params)
        if len(calls) == 3:
            raise telegram.TelegramError("HTTP 429: too many requests")
        return {}

    monkeypatch.setattr(telegram, "call", flaky)
    text = "\n".join("y" * 80 for _ in range(200))
    assert "2/" in telegram.send(text)


# --- format_report: headline vs table ------------------------------------------


def test_a_column_zero_line_becomes_a_bold_headline():
    out = telegram.format_report("ALL CLEAN\n  detail line")
    assert out.startswith("<b>ALL CLEAN</b>")
    assert "<pre>  detail line</pre>" in out


def test_an_indented_or_blank_line_is_boxed_not_bolded():
    """The convention every render() in this project already writes to: a
    section title flush left, its data indented. A data row must never
    become its own bold headline."""
    out = telegram.format_report("TITLE\n  row one\n  row two\n\n  row three")
    assert out.count("<b>") == 1
    assert "row one\n  row two" in out  # the whole run boxed as ONE block


def test_consecutive_headers_produce_consecutive_bold_lines_no_empty_pre():
    """Two headline lines in a row (a title, then a verdict) must not leave
    an empty <pre></pre> stranded between them."""
    out = telegram.format_report("COLLECT RUN — x\n✅ ALL CLEAN")
    assert out == "<b>COLLECT RUN — x</b>\n<b>✅ ALL CLEAN</b>"


def test_html_metacharacters_are_escaped_in_both_headlines_and_tables():
    """The reason this whole module escapes at all: an unescaped `<` makes
    Telegram reject the ENTIRE message, headline included."""
    out = telegram.format_report("A <script> title\n  a <b>row</b>")
    assert "<script>" not in out and "&lt;script&gt;" in out
    assert "<pre>  a &lt;b&gt;row&lt;/b&gt;</pre>" in out


def test_an_all_blank_report_formats_to_nothing_send_still_never_sends_empty(token, monkeypatch):
    """format_report("") -> "". Telegram rejects an empty message outright, so
    send() must fall back to a plain wrap rather than transmitting nothing."""
    assert telegram.format_report("") == ""
    assert telegram.format_report("\n\n") == ""
    sent = {}
    def fake_call(method, params=None, timeout=20):
        sent["text"] = params["text"]
        return {}
    monkeypatch.setattr(telegram, "call", fake_call)
    telegram.send("\n\n")
    assert sent["text"] != "", "an empty body was handed to Telegram"


def test_a_raw_send_never_bolds_anything_even_a_column_zero_line(token, monkeypatch):
    """/log and /verdict: a raw log tail or a markdown file's own headings do
    not follow the header/indent convention, and running them through the
    smart formatter would bold nearly every line rather than none."""
    sent = {}
    monkeypatch.setattr(telegram, "call", lambda m, params=None, timeout=20: sent.setdefault("text", params["text"]) or {})
    telegram.send("2026-09-23 collect.log\nline one\nline two", raw=True)
    assert sent["text"] == "<pre>2026-09-23 collect.log\nline one\nline two</pre>"
    assert "<b>" not in sent["text"]


def test_a_headline_after_a_table_is_separated_by_a_blank_line():
    """Telegram swallows the single newline after </pre>. With only one, the
    next headline arrived glued to the table's last row — the owner pasted
    "...the next slot retries.STAGES" and "failed: dealsFEEDS" (2026-09-25)."""
    out = telegram.format_report("A\n  row\nB\n  row2")
    assert "</pre>\n\n<b>B</b>" in out
    assert not out.endswith("\n"), "no trailing blank after the last block"
