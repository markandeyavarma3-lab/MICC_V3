"""bounded.py — a hard deadline on a call that has no timeout of its own.

THE HOLE THIS CLOSES, MEASURED 2026-09-17. The 08:30 collector run spent
50 minutes 20 seconds in the deal fetch. Every fetcher in this project passes
`timeout=30` to `urlopen`, and every one of them is unbounded anyway, because
that timeout applies to the SOCKET — connect and read — and not to name
resolution. `socket.create_connection` calls `getaddrinfo` first, with no
timeout parameter, and on a half-up network (Wi-Fi reassociating, resolver
not yet answering) macOS's resolver can block for minutes per call.

From the manifest: run start 03:07:55 UTC, `nse_bulk_deals` FAILED at
03:20:44 after six resolution attempts (warm-up and bulk, three each), then
`nse_block_deals` succeeded at 03:57:55 — 37 minutes for one source, most of
it inside `getaddrinfo`. `timeout=30` never fired once.

There is no portable way to give `getaddrinfo` a deadline. There is a way to
give the CALLER one: run the call in a thread and stop waiting. The thread is
a daemon, so a resolver that never answers cannot hold the process at exit.
The abandoned call finishes whenever it finishes and its result is discarded.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


class Deadline(TimeoutError):
    """The call did not return in time. Subclasses TimeoutError so every
    `except (URLError, TimeoutError)` already in the fetchers catches it."""


def bounded(fn: Callable[[], T], seconds: float, what: str = "call") -> T:
    """Run `fn()` and return its result, or raise Deadline after `seconds`.

    An exception raised by `fn` is re-raised here, with its original type,
    so a 404 still reads as a 404 to the caller's own handling.
    """
    box: dict[str, object] = {}

    def run() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 - carried across the thread, not swallowed
            box["error"] = exc

    t = threading.Thread(target=run, daemon=True, name=f"bounded:{what}")
    t.start()
    t.join(seconds)
    if t.is_alive():
        raise Deadline(f"{what} did not return within {seconds:g}s")
    if "error" in box:
        raise box["error"]  # type: ignore[misc]
    return box["value"]  # type: ignore[return-value]
