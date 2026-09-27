"""portal.py — sign this Mac in to the KL University Wi-Fi, and keep it signed in.

WHY. The owner's network is KLEF-SQ / KLEF-SQ-5G, behind a Sophos Firewall
captive portal at captiveportal.kluniversity.in. A signed-in session stays up
only while something sends the portal's keep-alive: the portal's own login
page does it every 180 seconds (`liveReqTimeInJS=180` in its httpclient.js),
and when no browser tab is open, nothing does, so the firewall drops the
machine after about ten idle minutes. Every scheduled run that found the Mac
asleep therefore also found it signed out: DNS failures were 148 of 277 fetch
failures since 2026-09-15.

THE PROTOCOL, read from the portal's own script (2026-09-25), not guessed:

  sign in    POST https://<portal>:8090/login.xml
             mode=191&username=U&password=P&a=<epoch ms>&producttype=0
             -> XML whose <status> is LIVE on success
  keep-alive GET  https://<portal>:8090/live?mode=192&username=u&a=<ms>&producttype=0
             -> XML whose <ack> is "ack" while the session is alive

producttype 0 is the portal's `Client.WEB`. The certificate is a valid
Sectigo *.kluniversity.in, so HTTPS is verified normally — nothing here turns
certificate checking off.

CREDENTIALS NEVER LIVE IN THE REPOSITORY, which is public. They are read from
~/.micc_wifi_portal (override: WIFI_PORTAL_FILE), two lines:

    PORTAL_USERNAME=<id>
    PORTAL_PASSWORD=<password>

created by the owner with `python -m src.common.portal --setup`, which asks
for the password without echoing it. The file must be mode 600; a readable
file is refused rather than used. No function in this module prints, logs or
returns the password, and the username is only ever shown masked.
"""

from __future__ import annotations

import os
import re
import stat
import sys
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from src.common.bounded import bounded

PORTAL = "https://captiveportal.kluniversity.in:8090"
LOGIN_URL = f"{PORTAL}/login.xml"
LIVE_URL = f"{PORTAL}/live"
PRODUCT_WEB = "0"
TIMEOUT = 10
#: The portal's own keep-alive cadence (httpclient.js liveReqTimeInJS).
KEEPALIVE_SECONDS = 180
DEFAULT_FILE = Path.home() / ".micc_wifi_portal"


class PortalError(RuntimeError):
    """Signing in failed; the message never contains the password."""


class PortalUnreachable(PortalError):
    """The portal could not be reached at all — not a verdict on the credentials."""


#: The mtime of a credentials file the portal REJECTED. Retrying rejected
#: credentials every three minutes is how an account gets locked; once refused,
#: nothing signs in again until the file changes (i.e. setup is re-run).
REFUSED_MARK = Path(os.environ.get("WIFI_PORTAL_REFUSED",
                                   Path(__file__).resolve().parents[2] / "logs" / ".wifi_portal_refused"))


def _file_stamp(path: Path) -> str:
    st = path.stat()
    return f"{st.st_mtime_ns}:{st.st_size}"


def _refused(path: Path) -> bool:
    try:
        return REFUSED_MARK.read_text().strip() == _file_stamp(path)
    except OSError:
        return False


def _mark_refused(path: Path) -> None:
    try:
        REFUSED_MARK.parent.mkdir(parents=True, exist_ok=True)
        REFUSED_MARK.write_text(_file_stamp(path))
    except OSError:
        pass


def credentials_path() -> Path:
    return Path(os.environ.get("WIFI_PORTAL_FILE", DEFAULT_FILE))


def load_credentials(path: Path | None = None) -> tuple[str, str] | None:
    """(username, password), or None when not configured.

    A file readable by group or others is REFUSED — raising, not returning
    None — because silently using a leaked password is worse than a run that
    says why it could not sign in.
    """
    path = path or credentials_path()
    if not path.exists():
        return None
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o077:
        raise PortalError(f"{path} is mode {oct(mode)}; run: chmod 600 {path}")
    vals: dict[str, str] = {}
    for line in path.read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, _, v = line.partition("=")
            vals[k.strip()] = v.strip()
    user, pw = vals.get("PORTAL_USERNAME", ""), vals.get("PORTAL_PASSWORD", "")
    return (user, pw) if user and pw else None


def mask(user: str) -> str:
    return user[:2] + "*" * max(len(user) - 4, 0) + user[-2:] if len(user) > 4 else "****"


def _tag(xml: str, name: str) -> str:
    m = re.search(rf"<{name}>\s*(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?\s*</{name}>", xml, re.S | re.I)
    return m.group(1).strip() if m else ""


def _ms() -> str:
    return str(int(time.time() * 1000))


def _http(req: Request) -> str:
    def _go() -> str:
        with urlopen(req, timeout=TIMEOUT) as resp:  # noqa: S310 - fixed https host
            return resp.read(65536).decode("utf-8", "replace")
    return bounded(_go, TIMEOUT + 5, what="wifi portal")


def login(user: str, password: str, _http=_http) -> str:
    """Sign in. Returns the portal's message on success; raises PortalError."""
    body = urlencode({"mode": "191", "username": user, "password": password,
                      "a": _ms(), "producttype": PRODUCT_WEB}).encode()
    req = Request(LOGIN_URL, data=body, method="POST",
                  headers={"Content-Type": "application/x-www-form-urlencoded",
                           "User-Agent": "Mozilla/5.0"})
    try:
        xml = _http(req)
    except Exception as exc:  # noqa: BLE001
        # THE REASON, NOT JUST THE CLASS. "portal unreachable: URLError" on
        # 2026-09-27 could not say whether the Wi-Fi was still re-associating
        # or the portal was down. urllib's reason carries no credentials.
        reason = getattr(exc, "reason", None) or exc
        raise PortalUnreachable(f"portal unreachable: {type(exc).__name__}: {str(reason)[:100]}") from None
    status, message = _tag(xml, "status"), _tag(xml, "message")
    if status.upper() == "LIVE":
        # The portal returns its own template unfilled: "You are signed in as {username}".
        return (message or "signed in").replace("{username}", mask(user))
    # The portal's message can quote what was submitted; never echo the password.
    message = message.replace(password, "***") if password else message
    raise PortalError(f"portal refused sign-in ({status or 'no status'}): {message[:120]}")


def keepalive(user: str, _http=_http) -> bool:
    """One keep-alive. True if the portal acknowledged a live session."""
    q = urlencode({"mode": "192", "username": user.lower(), "a": _ms(), "producttype": PRODUCT_WEB})
    try:
        xml = _http(Request(f"{LIVE_URL}?{q}", headers={"User-Agent": "Mozilla/5.0"}))
    except Exception:  # noqa: BLE001
        return False
    return _tag(xml, "ack").lower() == "ack"


def login_if_configured() -> tuple[bool, str]:
    """The recovery step network.wait_for_network runs when not UP. NEVER RAISES.

    (signed_in, sentence for the log). Not configured is (False, why).
    """
    path = credentials_path()
    try:
        creds = load_credentials(path)
    except PortalError as exc:
        return False, f"wifi portal: {exc}"
    if not creds:
        return False, "wifi portal: no credentials configured (python -m src.common.portal --setup)"
    if _refused(path):
        return False, ("wifi portal: these credentials were REJECTED by the portal; not retrying "
                       "(re-run: python -m src.common.portal --setup)")
    user, pw = creds
    try:
        login(user, pw)
        return True, f"wifi portal: signed in as {mask(user)}"
    except PortalUnreachable as exc:
        return False, f"wifi portal: {exc}"
    except PortalError as exc:
        _mark_refused(path)
        return False, f"wifi portal: {exc} — not retrying until setup is re-run"


def keep_session() -> str:
    """What the keep-alive agent runs every KEEPALIVE_SECONDS. NEVER RAISES.

    Ack -> nothing to do. No ack -> the session is gone: sign in again.
    """
    path = credentials_path()
    try:
        creds = load_credentials(path)
    except PortalError as exc:
        return f"wifi portal: {exc}"
    if not creds:
        return "wifi portal: not configured"
    user, _ = creds
    if keepalive(user):
        return "wifi portal: session alive"
    ok, msg = login_if_configured()
    return msg.replace("wifi portal: ", "wifi portal: session had lapsed; ", 1) if ok else msg


def setup(path: Path | None = None, _input=input, _getpass=None, _login=None) -> int:
    """Create or replace the credentials file — ONLY with credentials the
    portal has just accepted.

    TEST FIRST, THEN SAVE (2026-09-27). The first version wrote the file and
    then tested it, so a typo'd ID (one extra digit) replaced credentials that
    had signed in minutes earlier, and the keep-alive then retried the bad
    pair every three minutes. Now: rejected -> nothing is written and any
    existing file is untouched; portal unreachable -> nothing is written,
    because an untested pair is not saved over a tested one.
    """
    import getpass

    path = path or credentials_path()
    _getpass = _getpass or getpass.getpass
    _login = _login or login
    user = _input("KL University Wi-Fi username (your ID): ").strip()
    pw = _getpass("Password (not shown): ")
    if not user or not pw:
        print("nothing written: username and password are both required")
        return 1
    print(f"testing sign-in as {mask(user)} ({len(user)} characters)...")
    try:
        msg = _login(user, pw)
    except PortalUnreachable as exc:
        print(f"NOT saved — {exc}.\n  Is the Wi-Fi connected to KLEF-SQ / KLEF-SQ-5G? "
              f"Wait until it shows Connected, then run setup again.")
        return 1
    except PortalError as exc:
        print(f"NOT saved — {exc}.\n  Check the ID ({len(user)} characters typed) and the password."
              + ("  The existing credentials were left as they were." if path.exists() else ""))
        return 1
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(f"PORTAL_USERNAME={user}\nPORTAL_PASSWORD={pw}\n")
    os.chmod(tmp, 0o600)
    tmp.replace(path)
    print(f"saved {path} (mode 600) — portal says: {msg}")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if "--setup" in argv:
        return setup()
    if "--keepalive" in argv:
        print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {keep_session()}", flush=True)
        return 0
    if "--login" in argv:
        ok, msg = login_if_configured()
        print(msg)
        return 0 if ok else 1
    print(__doc__.split("\n")[0])
    print("usage: python -m src.common.portal --setup | --login | --keepalive")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
