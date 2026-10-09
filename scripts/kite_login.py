"""Log in to Kite Connect once for the day and save the access token, mode 600.

The OWNER runs this, in their own Terminal, never through a chat:

    .venv/bin/python scripts/kite_login.py

It opens Zerodha's login page; after the login Zerodha redirects the browser
to http://127.0.0.1:5000/?request_token=... (the redirect URL set on the Kite
Connect app). A one-request server on this machine catches it, exchanges the
request token for the day's access token with the app secret, and writes
~/.micc_kite_token. Nothing secret is printed, logged or sent anywhere but
api.kite.trade. Kite tokens expire every day, so this is a once-a-day step
while the audit runs (src/archive/kite.py).
"""

from __future__ import annotations

import json
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.archive import kite  # noqa: E402

PORT = 5000


def catch_request_token(port: int = PORT, timeout_s: int = 300) -> str:
    got: dict[str, str] = {}

    class H(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - http.server's name
            q = parse_qs(urlparse(self.path).query)
            got["status"] = (q.get("status") or [""])[0]
            got["token"] = (q.get("request_token") or [""])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"Logged in. You can close this tab and return to the Terminal.")

        def log_message(self, *a):  # the query string carries the token: never log it
            return

    srv = HTTPServer(("127.0.0.1", port), H)
    srv.timeout = timeout_s
    srv.handle_request()
    srv.server_close()
    if got.get("status") != "success" or not got.get("token"):
        raise SystemExit("  login did not complete (no request_token on the redirect)")
    return got["token"]


def exchange(key: str, secret: str, request_token: str) -> str:
    data = urlencode({"api_key": key, "request_token": request_token,
                      "checksum": kite.checksum(key, request_token, secret)}).encode()
    req = Request(f"{kite.API}/session/token", data=data, headers={"X-Kite-Version": "3"})
    with urlopen(req, timeout=kite.TIMEOUT) as r:
        return json.loads(r.read())["data"]["access_token"]


def main() -> int:
    try:
        key, secret = kite.creds()
    except kite.KiteAuthError as e:
        print(f"  {e}")
        return 1
    print("  Opening Zerodha's login page in your browser. Waiting for the redirect (5 min)...")
    webbrowser.open(kite.LOGIN.format(key=key))
    access = exchange(key, secret, catch_request_token())
    kite.write_token(access)
    print(f"  Saved today's access token to {kite.TOKEN} (mode 600). Valid until about 06:00 IST tomorrow.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
