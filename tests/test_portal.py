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

from src.common import network, portal

pytestmark = pytest.mark.unit

FAKE_USER, FAKE_PW = "9999900001", "hunter2-not-real"


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


# --- wired into the network wait -----------------------------------------------------------


def test_the_network_wait_signs_in_when_the_portal_intercepts():
    """The university portal signs a sleeping Mac out; waiting alone never
    brings that back. PORTAL -> sign in -> UP."""
    states = iter(["PORTAL", "UP"])
    clock = [0.0]
    tried = []
    state, _ = network.wait_for_network(
        180, poll=10, _probe=lambda: next(states, "UP"),
        _sleep=lambda s: clock.__setitem__(0, clock[0] + s), _now=lambda: clock[0],
        _recover=lambda: tried.append(1) or (True, "signed in"))
    assert state == "UP" and tried == [1]


def test_sign_in_is_not_retried_faster_than_every_half_minute():
    clock = [0.0]
    tried = []
    network.wait_for_network(
        90, poll=10, _probe=lambda: "PORTAL",
        _sleep=lambda s: clock.__setitem__(0, clock[0] + s), _now=lambda: clock[0],
        _recover=lambda: tried.append(clock[0]) or (False, "refused"))
    assert len(tried) <= 90 // network.RECOVER_EVERY + 1
    assert all(b - a >= network.RECOVER_EVERY for a, b in zip(tried, tried[1:]))


def test_the_keepalive_agent_runs_every_180_seconds_and_holds_no_credentials():
    from src.common.paths import ROOT
    s = (ROOT / "scripts" / "com.institutional-research.wifi.plist").read_text()
    assert "--keepalive" in s and "<integer>180</integer>" in s
    assert "PORTAL_PASSWORD=" not in s, "a credential value in a tracked file"
