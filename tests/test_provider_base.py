"""`coworker.providers.base.close_stream` — the two guarantees every provider's `finally`
depends on: a stream with no `.close()` must not blow up, and a `.close()` that raises
must never clobber a real error already propagating out of that same `finally`."""

from __future__ import annotations

import logging

from coworker.providers.base import close_stream


class _NoClose:
    """Stands in for the repo's fake/test streams (plain lists, bare generators, the
    hand-rolled `_FakeClient` fakes across the provider test files) — none of them are
    required to implement `.close()`."""


def test_close_stream_skips_silently_when_there_is_no_close_method():
    close_stream(_NoClose())  # must not raise
    close_stream([1, 2, 3])  # a plain list has no .close either
    close_stream(None)


class _RaisingClose:
    def __init__(self):
        self.calls = 0

    def close(self):
        self.calls += 1
        raise RuntimeError("close blew up")


def test_close_stream_swallows_its_own_exception():
    stream = _RaisingClose()
    close_stream(stream)  # must not raise
    assert stream.calls == 1


def test_close_stream_never_clobbers_a_real_error_already_propagating():
    """The exact shape every provider's `finally: close_stream(events)` runs in: a real
    exception is already unwinding the frame, and `close()` raising a second, unrelated
    one must never replace it — this is the whole reason `close_stream` never re-raises."""
    stream = _RaisingClose()
    real_error = ValueError("the actual failure")
    try:
        try:
            raise real_error
        finally:
            close_stream(stream)
    except ValueError as caught:
        assert caught is real_error
    else:
        raise AssertionError("the real error was swallowed")
    assert stream.calls == 1


def test_close_stream_logs_the_swallowed_exception_at_debug_level(caplog):
    with caplog.at_level(logging.DEBUG, logger="coworker.providers.base"):
        close_stream(_RaisingClose())
    debug_records = [r for r in caplog.records if r.levelno == logging.DEBUG]
    assert any("close" in r.getMessage() for r in debug_records)
