"""Item 6 — scratch-base failure handling.

`ensure_scratch_base()` / `_provision_scratch()` must never let a bad filesystem take down
construction or a background delivery: an unwritable configured base auto-degrades to the
default (~/OpenWorker) with a warning surfaced through `get_settings()`, and even the rare
case where the default itself is also unwritable must not raise out of `SessionManager()` or
`deliver_to_session()` — the latter records the failure to the unrouted dead-letter store
instead of crashing the inbound-delivery loop (`_dispatch_inbound` does not catch exceptions
from it).
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import time

from coworker.providers import ModelCapabilities, ProviderClient
from coworker.server.manager import SessionManager
from coworker.sessions import SessionRecord


class ScriptedProvider(ProviderClient):
    def complete(self, *, model, messages, tools=None, **settings):
        raise AssertionError("no turns expected")

    def capabilities(self, model):
        return ModelCapabilities()


def _block_with_file(path):
    """Occupy `path` with a plain file so a later mkdir() on it raises OSError — simulates
    "this location can't be a writable directory" without touching real ACLs/permissions."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("blocked", encoding="utf-8")


def test_unwritable_configured_base_falls_back_to_default(tmp_path, monkeypatch):
    monkeypatch.setenv("COWORKER_STATE_DIR", str(tmp_path / "state"))
    blocked = tmp_path / "blocked-base"
    _block_with_file(blocked)
    monkeypatch.setenv("COWORKER_SCRATCH_BASE", str(blocked))

    mgr = SessionManager(data_dir=tmp_path / "data", provider=ScriptedProvider())  # must not raise

    settings = mgr.get_settings()
    assert settings["scratch_base_error"] is not None
    assert str(blocked) in settings["scratch_base_error"]
    # Falls back to the real default, not the blocked custom path.
    assert settings["scratch_base_effective"] != str(blocked)
    assert "OpenWorker" in settings["scratch_base_effective"]

    # The fallback is actually usable — a session provisions fine under it.
    scratch = mgr._provision_scratch("sess1")
    assert settings["scratch_base_effective"] in scratch


def test_construction_survives_default_also_unwritable(tmp_path, monkeypatch):
    """Both the configured base AND the ~/OpenWorker fallback are unwritable: construction
    still must not raise (decision: never blocks startup), and the error is surfaced."""
    monkeypatch.setenv("COWORKER_STATE_DIR", str(tmp_path / "state"))
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    _block_with_file(home / "OpenWorker")  # blocks the ~/OpenWorker fallback too
    blocked = tmp_path / "blocked-base"
    _block_with_file(blocked)
    monkeypatch.setenv("COWORKER_SCRATCH_BASE", str(blocked))

    mgr = SessionManager(data_dir=tmp_path / "data", provider=ScriptedProvider())  # must not raise

    settings = mgr.get_settings()
    assert settings["scratch_base_error"] is not None
    assert str(blocked) in settings["scratch_base_error"]
    assert str(home / "OpenWorker") in settings["scratch_base_error"]


def test_deliver_to_session_records_unrouted_instead_of_raising(tmp_path, monkeypatch):
    """A background delivery (weixin DM, self-wake, …) whose engine build fails — here
    because even the scratch-base fallback is unwritable — must not raise out of
    `deliver_to_session`: `_dispatch_inbound`/`_on_inbound` do not catch that exception, so
    an uncaught raise here used to vanish the inbound message with no trace anywhere."""
    monkeypatch.setenv("COWORKER_STATE_DIR", str(tmp_path / "state"))
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    _block_with_file(home / "OpenWorker")
    blocked = tmp_path / "blocked-base"
    _block_with_file(blocked)
    monkeypatch.setenv("COWORKER_SCRATCH_BASE", str(blocked))

    mgr = SessionManager(data_dir=tmp_path / "data", provider=ScriptedProvider())
    assert mgr.get_settings()["scratch_base_error"] is not None  # sanity: both bases broken

    # A persisted session whose workspace no longer exists, on a non-folder-requiring
    # persona (like a weixin DM session) — get_engine re-provisions the scratch dir on
    # every rebuild, which is exactly the call that fails here.
    sid = "brokensess"
    mgr.session_store.save(
        SessionRecord(
            session_id=sid,
            workspace=str(tmp_path / "gone"),
            model=mgr.model,
            mode="interactive",
            messages=[],
            agent="cowork",
        )
    )

    asyncio.run(mgr.deliver_to_session(sid, "hello from weixin"))  # must not raise

    items = mgr.unrouted.list()
    assert any(
        i["source"] == sid and i["text"] == "hello from weixin" for i in items
    ), items


def test_concurrent_probe_writable_dir_no_false_failures(tmp_path):
    """Two or more threads probing the *same* writable directory at once must never see a
    false "unwritable" — a shared fixed probe filename raced under Windows as
    [WinError 32] "the process cannot access the file because it is being used by another
    process" (one thread's unlink() colliding with another thread's write_text() on the
    identical path) on a directory that was in fact perfectly writable the whole time.
    `get_settings()` (threadpool route) and `_provision_scratch()`/`get_engine()`
    (asyncio.to_thread) both call `ensure_scratch_base()` -> `_probe_writable_dir` on
    different threads and routinely overlap in practice."""
    base = tmp_path / "shared-scratch"
    base.mkdir()

    def probe(_iteration):
        return SessionManager._probe_writable_dir(base)

    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(probe, range(400)))

    failures = [r for r in results if r is not None]
    assert not failures, failures


def test_ensure_scratch_base_caches_probe_briefly(tmp_path, monkeypatch):
    """`ensure_scratch_base()` runs on every `get_settings()` poll and every session
    provision; without a short cache each call redoes a real mkdir+write+unlink, which also
    widens the window for the concurrent-probe race covered above. A call within the TTL
    must be a cache hit (no real probe); `force=True` and TTL expiry must each force a fresh
    one."""
    monkeypatch.setenv("COWORKER_STATE_DIR", str(tmp_path / "state"))
    scratch = tmp_path / "scratch"
    monkeypatch.setenv("COWORKER_SCRATCH_BASE", str(scratch))

    mgr = SessionManager(data_dir=tmp_path / "data", provider=ScriptedProvider())

    calls = []
    real_probe = SessionManager._probe_writable_dir

    def counting_probe(base):
        calls.append(base)
        return real_probe(base)

    monkeypatch.setattr(SessionManager, "_probe_writable_dir", staticmethod(counting_probe))
    mgr._scratch_probe_cache.clear()  # drop the constructor's own warm-up probe

    mgr.ensure_scratch_base()
    assert len(calls) == 1  # cache was empty: a real probe

    mgr.ensure_scratch_base()
    assert len(calls) == 1  # within the TTL: cache hit, no second probe

    mgr.ensure_scratch_base(force=True)
    assert len(calls) == 2  # force bypasses the cache regardless of TTL

    mgr._SCRATCH_PROBE_TTL_SECONDS = 0.01  # instance override; shrinks the TTL for the test
    time.sleep(0.05)
    mgr.ensure_scratch_base()
    assert len(calls) == 3  # TTL expired: cache miss, real probe again
