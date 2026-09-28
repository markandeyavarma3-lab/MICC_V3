# wifi_portal — KL University Wi-Fi auto sign-in (PARKED)

**Status: parked 2026-09-28 at the owner's request, to be developed later.**
Nothing in the research platform imports this folder. The keep-alive agent is
**not installed**. The collectors still wait for the network before fetching
and no longer blame NSE for a local outage (`src/common/network.py`); that
part is generic and stays in use.

## The problem it solves

The owner's network (KLEF-SQ / KLEF-SQ-5G) sits behind a Sophos Firewall
captive portal at `captiveportal.kluniversity.in`. A session lasts only while
something sends the portal's keep-alive; the portal's own login page does it
every 180 s, so with no browser tab open the Mac is signed out after about ten
idle minutes. Every scheduled run that finds the Mac asleep also finds it
signed out. DNS failures were 148 of 277 fetch failures from 09-15 to 09-25.

## What is built and what works

| piece | file | status |
|---|---|---|
| Sign in (`POST :8090/login.xml`, `mode=191`, `producttype=0`) | `portal.py` `login()` | **works while the portal is reachable**: signed in on 09-27 23:22:30 by itself |
| Keep-alive (`GET :8090/live`, `mode=192`, every 180 s) | `portal.py` `keepalive()`, `keep_session()` | built; only proven while signed in |
| Credentials in `~/.micc_wifi_portal`, mode 600, never in the repo | `portal.py` `setup()` | works; tests before saving, and a rejected pair never overwrites a working one |
| No retry after a rejection (account-lock guard) | `portal.py` `_refused()` | works: logged "REJECTED … not retrying" 23:34–23:40 |
| launchd agent, every 180 s | `com.institutional-research.wifi.plist` | built, **not installed** |
| Tests (offline, fake portal) | `test_portal.py` | run with `pytest wifi_portal` |

The protocol was read from the portal's own `httpclient.js`, not guessed. The
certificate is a valid Sectigo `*.kluniversity.in`; HTTPS is verified normally.

## The blocker — start here

**While signed out, the portal's hostname does not resolve.** From the
keep-alive log after the owner signed out on 09-28:

    00:04:09 wifi portal: portal unreachable: URLError: [Errno 8] nodename nor servname provided
    00:07:09 wifi portal: portal unreachable: URLError: [Errno 8] nodename nor servname provided

So `login()` can sign in only when it is least needed. macOS's own sign-in
window does reach the portal while signed out, so the portal is reachable by
some other route. The next steps, in order:

1. **Find the route the sign-in window uses.** While signed out, run
   `curl -sv http://captive.apple.com/hotspot-detect.html` (do not follow
   redirects) and read the `Location:` header the firewall answers with: it
   names the exact portal URL and very likely an IP address.
2. **Fall back to that address when the name will not resolve.** Connect to
   the IP but keep certificate checking against `captiveportal.kluniversity.in`
   (set the TLS `server_hostname`); do not turn certificate checking off.
   When signed in the name resolves to 45.249.79.62; confirm whether that
   address is reachable while signed out.
3. **Test it while signed out,** from the Mac's own Terminal. Signing out also
   cuts off anything else running on the Mac, Claude Code included.

## Turning it back on

    # 1. re-wire the network wait to sign in (src/common/network.py): pass
    #    _recover=lambda: portal.login_if_configured() into wait_for_network
    #    from main() and counts_against_host's default wait.
    # 2. install the keep-alive:
    cp wifi_portal/com.institutional-research.wifi.plist ~/Library/LaunchAgents/
    launchctl bootstrap gui/$UID ~/Library/LaunchAgents/com.institutional-research.wifi.plist
    # 3. credentials (already present if ~/.micc_wifi_portal exists):
    .venv/bin/python -m wifi_portal.portal --setup

## Security notes

- The repository is public. Credentials live only in `~/.micc_wifi_portal`.
- The password was typed into a chat session on 2026-09-27. Change it if KL
  allows, then re-run `--setup`.
- To remove the stored credentials: `rm ~/.micc_wifi_portal`.
