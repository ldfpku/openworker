"""One-poller-per-token guard.

`getupdates` is consume-on-read, so two pollers on one bot token each take half the
inbound stream with no error anywhere. These pin the guard that stops it -- including
the case that actually matters, a SEPARATE PROCESS, since an in-process check would
pass every one of these tests and still let the real failure through.
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
import textwrap
import time

from coworker.connectors.weixin_adapter import WeixinAdapter
from coworker.connectors.weixin_lock import TokenLock, token_fingerprint
from coworker.connectors.weixin_state import WeixinState


def test_fingerprint_is_stable_and_hides_the_token():
    token = "xxxx-secret-bot-token"
    fp = token_fingerprint(token)
    assert fp == token_fingerprint(token)
    assert token_fingerprint("other") != fp
    # The path is logged and sits in a browsable state dir -- the token must not be in it.
    assert token not in fp and len(fp) == 16


def test_second_lock_in_this_process_loses(tmp_path):
    first, second = TokenLock("tok", tmp_path), TokenLock("tok", tmp_path)
    assert first.acquire() is True
    assert second.acquire() is False
    first.release()
    assert second.acquire() is True  # freed on release
    second.release()


def test_the_holder_can_be_named_while_it_holds(tmp_path):
    """The error message says "close the other one" — it needs to say WHICH. A byte-range
    lock on byte 0 blocks even our own reader on Windows, so the lock byte sits past the
    pid record rather than on top of it."""
    import os

    holder = TokenLock("tok", tmp_path)
    assert holder.acquire()
    try:
        assert holder.holder_pid() == os.getpid()
        loser = TokenLock("tok", tmp_path)
        assert loser.acquire() is False
        assert loser.holder_pid() == os.getpid()  # readable while still locked
    finally:
        holder.release()


def test_different_tokens_do_not_contend(tmp_path):
    a, b = TokenLock("tok-a", tmp_path), TokenLock("tok-b", tmp_path)
    assert a.acquire() and b.acquire()  # separate bots poll independently
    assert a.path != b.path
    a.release()
    b.release()


def test_acquire_is_idempotent_for_the_holder(tmp_path):
    lock = TokenLock("tok", tmp_path)
    assert lock.acquire() and lock.acquire()
    lock.release()


def test_unwritable_state_dir_does_not_block_receiving(tmp_path):
    # A lock we cannot take must not cost the user their messages: the connector runs
    # unlocked rather than refusing to start.
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("", encoding="utf-8")
    assert TokenLock("tok", blocker / "nested").acquire() is True


def test_lock_dies_with_the_process_no_stale_file_wedges_it(tmp_path):
    """The whole reason this is an OS lock and not a PID file: a holder that is killed
    (or crashes) must not leave the connector permanently unable to start."""
    root = str(tmp_path).replace("\\", "\\\\")
    child = subprocess.Popen(
        [
            sys.executable,
            "-c",
            textwrap.dedent(
                f"""
                import sys, time
                from coworker.connectors.weixin_lock import TokenLock
                lock = TokenLock("tok", r"{root}")
                assert lock.acquire()
                print("held", flush=True)
                time.sleep(120)
                """
            ),
        ],
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert child.stdout.readline().strip() == "held"
        # Contended across a real process boundary, which is the case that matters.
        assert TokenLock("tok", tmp_path).acquire() is False
    finally:
        child.kill()
        child.wait(timeout=30)
    # Killed without any chance to clean up -- the OS drops the lock anyway. Windows
    # releases it when the last handle closes, which trails process exit slightly, so
    # give it a moment rather than racing the kernel.
    reclaimed = TokenLock("tok", tmp_path)
    for _ in range(50):
        if reclaimed.acquire():
            break
        time.sleep(0.1)
    else:
        raise AssertionError("lock never released after the holder was killed")
    reclaimed.release()


def test_adapter_refuses_to_start_a_second_poller(tmp_path):
    profile = {"bot_token": "tok", "account_id": "bot@im.bot", "base_url": "https://x"}
    state = WeixinState(tmp_path / "wx-state")

    async def scenario():
        first = WeixinAdapter(profile, state=state)
        second = WeixinAdapter(profile, state=WeixinState(tmp_path / "wx-state"))
        assert await first.connect() is True
        # Refuses rather than silently splitting the stream with the first adapter.
        assert await second.connect() is False
        await first.disconnect()
        # ...and the token is claimable again once the first one really stopped.
        assert await second.connect() is True
        await second.disconnect()

    asyncio.run(scenario())
