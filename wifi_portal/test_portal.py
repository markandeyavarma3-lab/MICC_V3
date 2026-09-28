"""The KL University Wi-Fi portal: signing in, staying signed in, and never
leaking the password.

The owner's Wi-Fi drops a machine after ~10 idle minutes because nothing sends
the Sophos portal's keep-alive once the login tab is closed. Every test here
runs against a fake portal — no unit test signs anybody in to anything, and no
real credentials appear in this repository, which is public.
"""

from __future__ import annotations

import os
from urllib.parse import parse_qs, urlparse

import pytest

from wifi_portal import portal

pytestmark = pytest.mark.unit

FAKE_USER, FAKE_PW = "9999900001", "hunter2-not-real"


@pytest.fixture(autouse=True)
def _isolated_refusal_mark(tmp_path, monkeypatch):
    """Never read or write the real logs/.wifi_portal_refused from a test."""
    monkeypatch.setattr(portal, "REFUSED_MARK", tmp_path / "refused")


def _creds(tmp_path, mode=0o600, body=None):
    p = tmp_path / "wifi"
    p.write_text(body if body is not None else f"PORTAL_USERNAME={FAKE_USER}\nPORTAL_PASSWORD={FAKE_PW}\n")
    os.chmod(p, mode)
    return p


# --- credentials ------------------------------------------------------------------


def test_credentials_are_read_from_a_private_file(tmp_path):
    assert portal.load_credentials(_creds(tmp_path)) == (FAKE_USER, FAKE_PW)


def test_a_missing_or_incomplete_file_means_not_configured(tmp_path):
    assert portal.load_credentials(tmp_path / "nope") is None
    assert portal.load_credentials(_creds(tmp_path, body="PORTAL_USERNAME=x\n")) is None


def test_a_file_readable_by_others_is_refused_not_used(tmp_path):
    """Silently using a password sitting in a world-readable file is worse than
    a run that says why it could not sign in."""
    with pytest.raises(portal.PortalError, match="chmod 600"):
        portal.load_credentials(_creds(tmp_path, mode=0o644))


def test_the_username_is_only_ever_shown_masked():
    m = portal.mask(FAKE_USER)
    assert m != FAKE_USER and m.startswith("99") and m.endswith("01")


# --- the protocol, as the portal's own httpclient.js speaks it --------------------------


def test_sign_in_posts_exactly_what_the_portal_page_posts():
    seen = {}
    def fake(req):
        seen["url"], seen["method"] = req.full_url, req.get_method()
        seen["form"] = parse_qs(req.data.decode())
        return "<requestresponse><status><![CDATA[LIVE]]></status><message><![CDATA[You are signed in]]></message></requestresponse>"
    assert portal.login(FAKE_USER, FAKE_PW, _http=fake) == "You are signed in"
    assert seen["url"] == "https://captiveportal.kluniversity.in:8090/login.xml"
    assert seen["method"] == "POST"
    f = {k: v[0] for k, v in seen["form"].items()}
    assert f["mode"] == "191" and f["producttype"] == "0"
    assert f["username"] == FAKE_USER and f["password"] == FAKE_PW and f["a"].isdigit()


def test_a_refused_sign_in_raises_and_never_echoes_the_password():
    fake = lambda req: f"<status>LOGIN</status><message>Invalid password {FAKE_PW}</message>"  # noqa: E731
    with pytest.raises(portal.PortalError) as exc:
        portal.login(FAKE_USER, FAKE_PW, _http=fake)
    assert FAKE_PW not in str(exc.value)


def test_keepalive_sends_mode_192_and_reads_the_ack():
    seen = {}
    def fake(req):
        seen["q"] = parse_qs(urlparse(req.full_url).query)
        return "<ack><![CDATA[ack]]></ack>"
    assert portal.keepalive("ABC123", _http=fake)
    assert seen["q"]["mode"] == ["192"] and seen["q"]["username"] == ["abc123"]
    assert not portal.keepalive("x", _http=lambda r: "<ack>nack</ack>")
    assert not portal.keepalive("x", _http=lambda r: (_ for _ in ()).throw(OSError("down")))


# --- keeping the session ---------------------------------------------------------------


def test_a_live_session_is_left_alone_and_a_lapsed_one_signs_in_again(tmp_path, monkeypatch):
    monkeypatch.setenv("WIFI_PORTAL_FILE", str(_creds(tmp_path)))
    calls = []
    monkeypatch.setattr(portal, "keepalive", lambda u: True)
    monkeypatch.setattr(portal, "login", lambda u, p: calls.append(1) or "ok")
    assert "alive" in portal.keep_session() and not calls
    monkeypatch.setattr(portal, "keepalive", lambda u: False)
    msg = portal.keep_session()
    assert calls and "lapsed" in msg and FAKE_PW not in msg and FAKE_USER not in msg


def test_sign_in_messages_never_contain_the_password_or_full_username(tmp_path, monkeypatch):
    monkeypatch.setenv("WIFI_PORTAL_FILE", str(_creds(tmp_path)))
    monkeypatch.setattr(portal, "login", lambda u, p: "You are signed in")
    ok, msg = portal.login_if_configured()
    assert ok and FAKE_PW not in msg and FAKE_USER not in msg


# --- the keep-alive agent ------------------------------------------------------------------


def test_the_keepalive_agent_runs_every_180_seconds_and_holds_no_credentials():
    from src.common.paths import ROOT
    s = (ROOT / "wifi_portal" / "com.institutional-research.wifi.plist").read_text()
    assert "--keepalive" in s and "<integer>180</integer>" in s
    assert "PORTAL_PASSWORD=" not in s, "a credential value in a tracked file"


# --- 2026-09-27: a typo must not break a working setup ---------------------------------


def _setup(tmp_path, user, login):
    path = tmp_path / "creds"
    rc = portal.setup(path, _input=lambda _: user, _getpass=lambda _: FAKE_PW, _login=login)
    return rc, path


def _refuse(u, p):
    raise portal.PortalError("portal refused sign-in (LOGIN): Invalid user name/password")


def _unreachable(u, p):
    raise portal.PortalUnreachable("portal unreachable: URLError: [Errno 8] nodename nor servname")


def test_setup_saves_only_credentials_the_portal_accepts(tmp_path):
    rc, path = _setup(tmp_path, FAKE_USER, lambda u, p: "You are signed in as 99******01")
    assert rc == 0 and path.exists()
    assert oct(path.stat().st_mode & 0o777) == "0o600"


def test_a_rejected_setup_leaves_the_working_credentials_untouched(tmp_path):
    """The owner typed one extra digit and the working file was replaced."""
    rc, path = _setup(tmp_path, FAKE_USER, lambda u, p: "ok")
    before = path.read_text()
    rc, _ = _setup(tmp_path, FAKE_USER + "0", _refuse)
    assert rc == 1 and path.read_text() == before


def test_an_unreachable_portal_during_setup_saves_nothing(tmp_path):
    rc, path = _setup(tmp_path, FAKE_USER, _unreachable)
    assert rc == 1 and not path.exists()


def test_rejected_credentials_are_not_retried_until_the_file_changes(tmp_path, monkeypatch):
    """Retrying a rejected pair every three minutes is how accounts get locked."""
    creds = _creds(tmp_path)
    monkeypatch.setenv("WIFI_PORTAL_FILE", str(creds))
    calls = []
    monkeypatch.setattr(portal, "login", lambda u, p: calls.append(1) or _refuse(u, p))
    ok, msg = portal.login_if_configured()
    assert not ok and len(calls) == 1
    ok, msg = portal.login_if_configured()
    assert not ok and len(calls) == 1 and "REJECTED" in msg
    creds.write_text(f"PORTAL_USERNAME={FAKE_USER}\nPORTAL_PASSWORD=changed-pw\n")
    portal.login_if_configured()
    assert len(calls) == 2, "new credentials must be tried"


def test_an_unreachable_portal_is_not_remembered_as_a_rejection(tmp_path, monkeypatch):
    monkeypatch.setenv("WIFI_PORTAL_FILE", str(_creds(tmp_path)))
    calls = []
    monkeypatch.setattr(portal, "login", lambda u, p: calls.append(1) or _unreachable(u, p))
    portal.login_if_configured()
    portal.login_if_configured()
    assert len(calls) == 2


def test_unreachable_says_why_not_just_urlerror():
    from urllib.error import URLError
    def fake(req):
        raise URLError("[Errno 8] nodename nor servname provided")
    with pytest.raises(portal.PortalUnreachable, match="nodename nor servname"):
        portal.login(FAKE_USER, FAKE_PW, _http=fake)


def test_the_portals_unfilled_template_is_filled_with_the_masked_id():
    fake = lambda r: "<status>LIVE</status><message>You are signed in as {username}</message>"  # noqa: E731
    assert portal.login(FAKE_USER, FAKE_PW, _http=fake) == "You are signed in as 99******01"
