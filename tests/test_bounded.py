"""The deadline that `urlopen(timeout=)` does not provide.

A 50-minute deal fetch on 2026-09-17 against a 30-second timeout is the whole
motivation. `getaddrinfo` has no timeout; the only bound available is on the
caller's patience.
"""

from __future__ import annotations

import threading
import time

import pytest

from src.common.bounded import Deadline, bounded

pytestmark = pytest.mark.unit


def test_a_call_that_returns_in_time_returns_its_value():
    assert bounded(lambda: 42, 1.0) == 42


def test_a_call_that_hangs_is_abandoned_at_the_deadline():
    """The one that matters. Without the bound this test would take 60s."""
    started = time.monotonic()
    with pytest.raises(Deadline):
        bounded(lambda: time.sleep(60), 0.2, what="hang")
    assert time.monotonic() - started < 2.0


def test_the_deadline_is_a_timeout_error_so_existing_handlers_catch_it():
    """Every fetcher already has `except (URLError, TimeoutError)`. A new
    exception type that slipped past those would turn a slow network into a
    traceback instead of a retry."""
    assert issubclass(Deadline, TimeoutError)


def test_an_exception_inside_the_call_keeps_its_own_type():
    """A 404 must still read as a 404: prices.py treats it as a holiday and
    stops retrying. Wrapping it in Deadline would make every holiday retry."""
    class Custom(Exception):
        pass

    def boom():
        raise Custom("original")

    with pytest.raises(Custom, match="original"):
        bounded(boom, 1.0)


def test_the_abandoned_thread_is_a_daemon_and_cannot_pin_the_process():
    """A resolver that never answers must not hold the collector open at exit —
    that would turn a 50-minute stage into a process that never ends."""
    seen: list[threading.Thread] = []

    def capture():
        seen.append(threading.current_thread())
        time.sleep(30)

    with pytest.raises(Deadline):
        bounded(capture, 0.1)
    assert seen and seen[0].daemon
