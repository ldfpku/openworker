"""Tests for automation — models, store, next-run math, scheduler loop, tools, REST.

No network and no LLM: the scheduler's runner is injected with a fake; the agent-facing tools
operate on a real SQLite store; execution policy (catch-up, overlap) is exercised directly.
"""

from __future__ import annotations

import os
import asyncio
import threading
import time
from datetime import datetime, timezone

import pytest

from coworker.automation import (
    Schedule,
    ScheduledTask,
    Scheduler,
    TaskRun,
    TaskStore,
    compute_next_run,
)
from coworker.automation.tools import scheduling_tools


def _task(**kw) -> ScheduledTask:
    kw.setdefault("title", "Daily brief")
    kw.setdefault("instructions", "search the web and brief me")
    kw.setdefault("schedule", Schedule(kind="cron", cron="10 19 * * *"))
    kw.setdefault("workspace", "/tmp/cw-auto")
    return ScheduledTask(**kw)


# -- model / schedule ----------------------------------------------------------
def test_schedule_human():
    assert Schedule("cron", cron="10 19 * * *").human() == "每天 ~19:10"
    # Cron day-of-week: 0 (and 7) = Sunday, 1 = Monday … 6 = Saturday.
    assert "周日" in Schedule("cron", cron="0 9 * * 0").human()
    assert "周一" in Schedule("cron", cron="0 9 * * 1").human()
    assert "周六" in Schedule("cron", cron="0 9 * * 6").human()
    assert "周日" in Schedule("cron", cron="0 9 * * 7").human()  # 7 也是周日
    assert Schedule("cron", cron="0 9 5 * *").human() == "每月 5 日 ~09:00"
    assert Schedule("once", fire_at="2026-07-01T09:00:00").human().startswith("单次于")


def test_weekly_label_matches_croniter_fire_day():
    """The rendered weekday must equal the day croniter actually fires on (regression: a
    Monday-first name list indexed by cron dow labelled every weekly schedule a day late)."""
    from croniter import croniter

    # Independent oracle: indexed by datetime.weekday() (Mon=0), not by the cron dow the
    # label builder uses — so a rotated name list in models.py still trips this test.
    zh_dow = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    for dow in range(7):
        label = Schedule("cron", cron=f"0 9 * * {dow}").human()
        base = datetime(2026, 7, 20, 0, 0)  # a Monday
        fires = croniter(f"0 9 * * {dow}", base).get_next(datetime)
        assert zh_dow[fires.weekday()] in label, (dow, label, fires.strftime("%A"))


def test_task_gets_own_thread_id():
    t = _task()
    assert t.task_session_id == f"__task__{t.id}"
    assert t.public()["schedule"] == "每天 ~19:10"


def test_compute_next_run_cron_explicit_utc():
    t = _task(schedule=Schedule(kind="cron", cron="10 19 * * *", timezone="UTC"))
    after = datetime(2026, 6, 5, 18, 0, tzinfo=timezone.utc).timestamp()
    nxt = compute_next_run(t, after=after)
    assert datetime.fromtimestamp(nxt, tz=timezone.utc) == datetime(
        2026, 6, 5, 19, 10, tzinfo=timezone.utc
    )


def test_compute_next_run_defaults_to_local_time():
    """Default 'local' tz: '7:10pm' fires at 19:10 on the *machine's* clock, not UTC."""
    t = _task()  # Schedule default timezone == "local"
    assert t.schedule.timezone == "local"
    nxt = compute_next_run(t)
    local = datetime.fromtimestamp(nxt).astimezone()
    assert (local.hour, local.minute) == (19, 10)


def test_compute_next_run_once_in_past_is_none():
    past = "2020-01-01T00:00:00+00:00"
    t = _task(schedule=Schedule(kind="once", fire_at=past))
    assert compute_next_run(t) is None


def test_compute_next_run_once_local_is_dst_aware():
    """A one-time 'local' task set while EDT is in effect but firing on a winter EST date must
    fire at the requested wall-clock, not an hour off. Binding the naive datetime to the
    offset in effect at compute time (the old bug) misfired by the DST delta.

    The local zone is a process-wide C-runtime setting, so the check runs in a child
    interpreter with TZ fixed in its environment: POSIX takes the IANA name, the Windows CRT
    only understands the `EST5EDT` form (and has no `time.tzset` to re-read TZ in-process)."""
    import json
    import subprocess
    import sys

    script = "\n".join(
        [
            "import json",
            "from datetime import datetime",
            "from coworker.automation import Schedule, ScheduledTask, compute_next_run",
            "summer_now = datetime(2026, 7, 1, 12, 0).timestamp()",
            "t = ScheduledTask(title='Daily brief', instructions='x', workspace='/tmp/cw-auto', "
            "schedule=Schedule(kind='once', fire_at='2026-12-25T08:00:00'))",
            "nxt = compute_next_run(t, after=summer_now)",
            "fires = datetime.fromtimestamp(nxt)",
            "print(json.dumps([fires.year, fires.month, fires.day, fires.hour, fires.minute]))",
        ]
    )
    env = {**os.environ, "TZ": "EST5EDT" if sys.platform == "win32" else "America/New_York"}
    proc = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout.strip().splitlines()[-1]) == [2026, 12, 25, 8, 0]


# -- store ---------------------------------------------------------------------
def test_store_crud_and_due(tmp_path):
    store = TaskStore(tmp_path / "auto.db")
    t = _task(
        schedule=Schedule(kind="cron", cron="* * * * *")
    )  # every minute → due soon
    store.save(t)
    assert store.get(t.id).title == "Daily brief"
    assert [x.id for x in store.list()] == [t.id]
    # next_run computed + due() finds it once we're past next_run
    due = store.due(now=t.next_run + 1)
    assert [x.id for x in due] == [t.id]
    # disabled tasks are not due
    t.enabled = False
    store.save(t)
    assert store.due(now=t.next_run + 1 if t.next_run else 9e9) == []
    assert store.delete(t.id) is True and store.get(t.id) is None


def test_store_runs_history(tmp_path):
    store = TaskStore(tmp_path / "auto.db")
    t = _task()
    store.save(t)
    store.add_run(TaskRun(task_id=t.id, status="ok", result_text="hi"))
    store.add_run(TaskRun(task_id=t.id, status="error", error="boom"))
    runs = store.runs(t.id)
    assert len(runs) == 2 and runs[0].status in ("ok", "error")


# -- scheduler loop ------------------------------------------------------------
async def test_scheduler_runs_due_task_and_advances(tmp_path):
    store = TaskStore(tmp_path / "auto.db")
    t = _task(schedule=Schedule(kind="cron", cron="* * * * *"))
    store.save(t)
    # force it due now
    t.next_run = 1.0
    store.save(t)
    t.next_run = 1.0  # save() recomputes; push it into the past again
    store._conn.execute("UPDATE scheduled_tasks SET next_run=1.0 WHERE id=?", (t.id,))
    store._conn.commit()

    ran: list[str] = []
    ran_once = asyncio.Event()

    async def runner(task, trigger):
        ran.append(task.id)
        ran_once.set()
        return TaskRun(task_id=task.id, status="ok", trigger=trigger)

    sched = Scheduler(store, runner, tick_seconds=0.05)
    sched.start()
    # Wait for the run instead of sleeping a fixed window: with an every-minute cron, a
    # fixed sleep that happens to straddle a minute boundary lets the advanced task come
    # due AGAIN and legitimately fire twice. Stopping right after the first run (the
    # advance is synchronous once the runner returns) makes the single-fire assertion
    # deterministic.
    await asyncio.wait_for(ran_once.wait(), timeout=5.0)
    await sched.stop()
    assert ran == [t.id]
    advanced = store.get(t.id)
    assert advanced.run_count == 1 and advanced.last_status == "ok"
    assert (
        advanced.next_run is not None and advanced.next_run > 1.0
    )  # moved to the future


async def test_scheduler_skips_overlapping_run(tmp_path):
    store = TaskStore(tmp_path / "auto.db")
    t = _task()
    store.save(t)
    gate = asyncio.Event()
    started = 0

    async def slow_runner(task, trigger):
        nonlocal started
        started += 1
        await gate.wait()
        return TaskRun(task_id=task.id, status="ok")

    sched = Scheduler(store, slow_runner)
    first = asyncio.create_task(sched.run_task(t, trigger="manual"))
    await asyncio.sleep(0.02)
    second = await sched.run_task(t, trigger="manual")  # overlaps → skipped
    assert second is None and started == 1
    gate.set()
    await first


async def test_tick_retains_spawned_run_until_it_finishes(tmp_path):
    """`_tick` spawns each claimed run without awaiting it — `_spawned` must hold a
    strong reference (spawn_retained) for as long as the run is in flight, and drop it
    once the run settles, the same set `stop()` drains at shutdown."""
    store = TaskStore(tmp_path / "auto.db")
    t = _task(schedule=Schedule(kind="cron", cron="* * * * *"))
    store.save(t)
    # force it due now (same recipe as test_scheduler_runs_due_task_and_advances)
    t.next_run = 1.0
    store.save(t)
    t.next_run = 1.0  # save() recomputes; push it into the past again
    store._conn.execute("UPDATE scheduled_tasks SET next_run=1.0 WHERE id=?", (t.id,))
    store._conn.commit()

    gate = asyncio.Event()
    started = asyncio.Event()

    async def slow_runner(task, trigger):
        started.set()
        await gate.wait()
        return TaskRun(task_id=task.id, status="ok", trigger=trigger)

    sched = Scheduler(store, slow_runner)
    await sched._tick(trigger="manual")
    await asyncio.wait_for(started.wait(), timeout=2.0)

    assert len(sched._spawned) == 1
    (spawned_task,) = sched._spawned
    assert not spawned_task.done()

    gate.set()
    await asyncio.wait_for(spawned_task, timeout=2.0)
    assert sched._spawned == set()


# -- agent-facing tools --------------------------------------------------------
def test_create_and_list_tools(tmp_path):
    store = TaskStore(tmp_path / "auto.db")
    origin = {
        "surface": "cowork",
        "session_id": "s1",
        "workspace": "/tmp/ws",
        "agent": "cowork",
    }
    tools = {
        t.__name__: t
        for t in scheduling_tools(store, origin=origin, default_workspace="/tmp/ws")
    }

    out = tools["create_scheduled_task"](
        title="Brief", instructions="brief me", cron="10 19 * * *"
    )
    assert out["ok"] and out["schedule"] == "每天 ~19:10"
    # create surfaces a confirm card → gated
    assert (
        tools["create_scheduled_task"].__aisuite_tool_metadata__.requires_approval
        is True
    )

    listed = tools["list_scheduled_tasks"]()["tasks"]
    assert (
        len(listed) == 1
        and listed[0]["origin_session_id" if False else "title"] == "Brief"
    )
    saved = store.list()[0]
    assert saved.origin_session_id == "s1" and saved.workspace == "/tmp/ws"

    bad = tools["create_scheduled_task"](title="x", instructions="y", cron="not-a-cron")
    assert "invalid cron" in bad["error"]
    none = tools["create_scheduled_task"](title="x", instructions="y")
    assert "error" in none  # neither cron nor fire_at


def test_update_and_delete_tools(tmp_path):
    store = TaskStore(tmp_path / "auto.db")
    tools = {
        t.__name__: t
        for t in scheduling_tools(
            store, origin={"workspace": "/tmp/ws"}, default_workspace="/tmp/ws"
        )
    }
    tid = tools["create_scheduled_task"](
        title="X", instructions="do", cron="0 9 * * *"
    )["id"]
    assert (
        tools["update_scheduled_task"](id=tid, enabled=False)["task"]["enabled"]
        is False
    )
    assert store.get(tid).next_run is None  # disabled → no next run
    assert tools["delete_scheduled_task"](id=tid)["ok"] is True
    assert tools["update_scheduled_task"](id=tid)["error"]


# -- run persists as a continuable session -------------------------------------
async def test_scheduled_run_persists_continuable_session(tmp_path, monkeypatch):
    from coworker.providers import AssistantTurn, ModelCapabilities, ProviderClient
    from coworker.server.manager import SessionManager, _last_assistant_text

    class ScriptedProvider(ProviderClient):
        def __init__(self, turns):
            self._turns = list(turns)

        def complete(self, *, model, messages, tools=None, **settings):
            return self._turns.pop(0)

        def capabilities(self, model):
            return ModelCapabilities()

    monkeypatch.setenv("COWORKER_STATE_DIR", str(tmp_path / "state"))
    ws = tmp_path / "ws"
    ws.mkdir()
    # two turns: the scheduled run, then a follow-up question
    provider = ScriptedProvider(
        [
            AssistantTurn(text="Daily brief: all quiet.", finish_reason="stop"),
            AssistantTurn(text="Sure — here is more detail.", finish_reason="stop"),
        ]
    )
    manager = SessionManager(data_dir=tmp_path / "data", provider=provider)
    task = _task(workspace=str(ws), agent="cowork")
    manager.task_store.save(task)

    run = await manager._run_scheduled_task(task, trigger="manual")
    assert run.status == "ok" and run.session_id == f"__run__{run.run_id}"
    assert run.result_text == "Daily brief: all quiet."

    # the run is now a real, reopenable session with the transcript
    record = manager.session_store.load(run.session_id)
    assert (
        record is not None
        and record.workspace
        and any("Scheduled run" in (m.get("content") or "") for m in record.messages)
    )
    # …and it is continuable: a follow-up turn reuses the same thread
    engine = manager.get_engine(run.session_id, workspace=str(ws), agent="cowork")
    async for _ in engine.run("tell me more"):
        pass
    assert _last_assistant_text(engine.messages) == "Sure — here is more detail."


# -- a genuine failure after engine.run() still records "error" (anti-regression) --
async def test_scheduled_run_exception_after_engine_run_is_recorded_as_error(
    tmp_path, monkeypatch
):
    """`_run_scheduled_task`'s inner `except Exception` must still catch a real failure
    and record `status="error"` — the new `interrupted` bookkeeping above it must not
    swallow or reclassify it. A plain provider exception doesn't reach this branch
    (engine.py degrades those into an ERROR *event*, see the neighboring
    `..._marks_idle_when_setup_raises` test), so the raise is forced right after
    `engine.run()` completes, at `_last_assistant_text` — the first statement in the
    same try block, still well inside the "did the run actually happen" success path.
    """
    from coworker.providers import AssistantTurn, ModelCapabilities, ProviderClient
    from coworker.server.manager import SessionManager

    class ScriptedProvider(ProviderClient):
        def complete(self, *, model, messages, tools=None, **settings):
            return AssistantTurn(text="done", finish_reason="stop")

        def capabilities(self, model):
            return ModelCapabilities()

    monkeypatch.setenv("COWORKER_STATE_DIR", str(tmp_path / "state"))
    ws = tmp_path / "ws"
    ws.mkdir()
    manager = SessionManager(data_dir=tmp_path / "data", provider=ScriptedProvider())
    task = _task(workspace=str(ws), agent="cowork")
    manager.task_store.save(task)

    def _boom(messages):
        raise RuntimeError("boom")

    monkeypatch.setattr("coworker.server.manager._last_assistant_text", _boom)

    run = await manager._run_scheduled_task(task, trigger="manual")

    assert run.status == "error" and run.error == "boom"
    persisted = manager.task_store.runs(task.id)
    assert len(persisted) == 1 and persisted[0].status == "error"
    assert manager.is_running(run.session_id) is False


# -- concurrency: a scheduled run must mark its session busy --------------------
async def test_scheduled_run_marks_session_busy_while_running(tmp_path, monkeypatch):
    """Bug: _run_scheduled_task never called mark_running, so a concurrent WS turn
    (claim_turn -> try_mark_running) could grab the very same live engine mid-run —
    two turns racing on one TurnEngine. While the scheduled run is in flight,
    is_running must be True and a second claim on the same session must be
    rejected."""
    from coworker.providers import AssistantTurn, ModelCapabilities, ProviderClient
    from coworker.server.manager import SessionManager

    entered = threading.Event()
    release = threading.Event()

    class BlockingProvider(ProviderClient):
        def complete(self, *, model, messages, tools=None, **settings):
            entered.set()
            release.wait(timeout=10)  # backstop: never hang the suite
            return AssistantTurn(text="done", finish_reason="stop")

        def capabilities(self, model):
            return ModelCapabilities()

    monkeypatch.setenv("COWORKER_STATE_DIR", str(tmp_path / "state"))
    ws = tmp_path / "ws"
    ws.mkdir()
    manager = SessionManager(data_dir=tmp_path / "data", provider=BlockingProvider())
    task = _task(workspace=str(ws), agent="cowork")
    manager.task_store.save(task)

    run_task = asyncio.create_task(manager._run_scheduled_task(task, trigger="manual"))
    try:
        for _ in range(500):  # ~5s budget
            if entered.is_set():
                break
            await asyncio.sleep(0.01)
        assert entered.is_set(), "provider.complete was never entered"

        runs = manager.task_store.runs(task.id)
        assert runs, "run was not persisted before the provider call"
        session_id = runs[0].session_id

        assert manager.is_running(session_id) is True
        assert manager.try_mark_running(session_id) is False
    finally:
        release.set()  # never leave the worker thread (and pytest) blocked
        # No pytest-level timeout exists in this repo — if the assertions above ever
        # fail for a reason other than "provider never entered" (e.g. release didn't
        # actually unblock it), awaiting run_task bare could hang the whole suite.
        # wait_for() bounds that wait without masking a real assertion error already
        # in flight (asyncio.wait_for re-raises whatever run_task itself raises;
        # TimeoutError only fires if run_task is still stuck after the deadline).
        await asyncio.wait_for(run_task, timeout=10)


async def test_scheduled_run_marks_busy_before_run_started_broadcast(tmp_path, monkeypatch):
    """Pin down WHEN the busy marker must be set, not just that it eventually is.

    `run.session_id` becomes visible to every open GUI window the moment
    `automation_run_started` is broadcast (see `_run_scheduled_task`) — and that
    broadcast's `await` is the ONLY await between the run's session id existing and
    `engine.run()` beginning (no `await` inside `_build_task_engine` /
    `_seed_task_permissions` — both are plain `def`s). That makes it the one
    concurrency window a WS client could exploit to `claim_turn()` on this session
    before this function ever builds its own engine.

    T1 (`..._marks_session_busy_while_running`) only observes state once the
    provider has been entered — long after this broadcast — so it would stay green
    even if `mark_running` were moved to after the broadcast (e.g. to the top of the
    `try:`). This test guards that ordering directly."""
    from coworker.providers import AssistantTurn, ModelCapabilities, ProviderClient
    from coworker.server.manager import SessionManager

    class ScriptedProvider(ProviderClient):
        def complete(self, *, model, messages, tools=None, **settings):
            return AssistantTurn(text="done", finish_reason="stop")

        def capabilities(self, model):
            return ModelCapabilities()

    monkeypatch.setenv("COWORKER_STATE_DIR", str(tmp_path / "state"))
    ws = tmp_path / "ws"
    ws.mkdir()
    manager = SessionManager(data_dir=tmp_path / "data", provider=ScriptedProvider())
    task = _task(workspace=str(ws), agent="cowork")
    manager.task_store.save(task)

    observed: list[bool] = []
    original_broadcast = manager.broadcast_event

    async def spying_broadcast(event):
        if event.get("type") == "automation_run_started":
            # Record rather than assert here: an exception raised out of this spy
            # would propagate out of _run_scheduled_task's except-less outer `try`
            # (the broadcast call sits above the inner try/except that only wraps
            # engine.run), so it would NOT be swallowed either way — but recording
            # keeps this test robust to future refactors instead of depending on
            # that propagation path.
            observed.append(manager.is_running(event["data"]["session_id"]))
        return await original_broadcast(event)

    monkeypatch.setattr(manager, "broadcast_event", spying_broadcast)

    run = await manager._run_scheduled_task(task, trigger="manual")
    assert run.status == "ok"
    assert observed == [True], (
        "mark_running must happen before automation_run_started is broadcast — that "
        "broadcast is the only await between the run's session id existing and "
        "engine.run() starting, i.e. the concurrency window"
    )


async def test_scheduled_run_marks_idle_after_success(tmp_path, monkeypatch):
    """After a scheduled run finishes normally, the busy marker must be released so a
    later WS turn (or the next scheduled tick) can claim the session again."""
    from coworker.providers import AssistantTurn, ModelCapabilities, ProviderClient
    from coworker.server.manager import SessionManager

    class ScriptedProvider(ProviderClient):
        def complete(self, *, model, messages, tools=None, **settings):
            return AssistantTurn(text="done", finish_reason="stop")

        def capabilities(self, model):
            return ModelCapabilities()

    monkeypatch.setenv("COWORKER_STATE_DIR", str(tmp_path / "state"))
    ws = tmp_path / "ws"
    ws.mkdir()
    manager = SessionManager(data_dir=tmp_path / "data", provider=ScriptedProvider())
    task = _task(workspace=str(ws), agent="cowork")
    manager.task_store.save(task)

    run = await manager._run_scheduled_task(task, trigger="manual")
    assert run.status == "ok"
    assert manager.is_running(run.session_id) is False


async def test_scheduled_run_marks_idle_when_setup_raises(tmp_path, monkeypatch):
    """An exception during the run's setup must still release the busy marker via
    `finally` — mirrors the existing _durable_resume_turn guard shape (no `except`, just a
    `finally` around the busy marker; the exception still escapes to the caller).

    Note: a plain provider exception does NOT exercise this path — the engine's own
    error handling (`engine.py`) catches provider failures internally and degrades into
    an ERROR *event* rather than letting the exception propagate out of `engine.run()`,
    so `_run_scheduled_task`'s inner `except Exception` is unreachable that way. Forcing
    the raise in `_build_task_engine` instead reaches the outer guard directly."""
    from coworker.providers import AssistantTurn, ModelCapabilities, ProviderClient
    from coworker.server.manager import SessionManager

    class ScriptedProvider(ProviderClient):
        def complete(self, *, model, messages, tools=None, **settings):
            return AssistantTurn(text="unused", finish_reason="stop")

        def capabilities(self, model):
            return ModelCapabilities()

    monkeypatch.setenv("COWORKER_STATE_DIR", str(tmp_path / "state"))
    ws = tmp_path / "ws"
    ws.mkdir()
    manager = SessionManager(data_dir=tmp_path / "data", provider=ScriptedProvider())
    task = _task(workspace=str(ws), agent="cowork")
    manager.task_store.save(task)

    def _boom(self, task, *, session_id):
        raise RuntimeError("boom")

    monkeypatch.setattr(SessionManager, "_build_task_engine", _boom)

    with pytest.raises(RuntimeError, match="boom"):
        await manager._run_scheduled_task(task, trigger="manual")

    runs = manager.task_store.runs(task.id)
    assert runs, "the run record should have been persisted before the failure"
    assert manager.is_running(runs[0].session_id) is False


# -- a run stopped mid-flight is "canceled", not "ok" --------------------------
async def test_scheduled_run_interrupted_mid_turn_is_canceled_not_ok(
    tmp_path, monkeypatch
):
    """`request_interrupt()` (the Stop button) ends `engine.run()` NORMALLY — no
    exception — so before the fix `_run_scheduled_task` fell straight into the success
    path and recorded a zero-output, user-stopped run as `status="ok"`. The engine's own
    public signal for "this turn ended because of Stop" is the INTERRUPTED event; the
    provider is made to call `request_interrupt()` on the live engine mid-call (from the
    executor thread `_astream` runs it on — `_StopSignal.set()` is documented safe from
    any thread), which is exactly what a real Stop-button click races against."""
    from coworker.providers import AssistantTurn, ModelCapabilities, ProviderClient
    from coworker.server.manager import SessionManager

    class InterruptingProvider(ProviderClient):
        def __init__(self):
            self.engine = None  # set once _build_task_engine has built it

        def complete(self, *, model, messages, tools=None, **settings):
            assert self.engine is not None, "engine must be captured before first call"
            self.engine.request_interrupt()
            return AssistantTurn(text="ignored", finish_reason="stop")

        def capabilities(self, model):
            return ModelCapabilities()

    monkeypatch.setenv("COWORKER_STATE_DIR", str(tmp_path / "state"))
    ws = tmp_path / "ws"
    ws.mkdir()
    provider = InterruptingProvider()
    manager = SessionManager(data_dir=tmp_path / "data", provider=provider)
    task = _task(workspace=str(ws), agent="cowork")
    manager.task_store.save(task)

    original_build = SessionManager._build_task_engine

    def _capture(self, task, *, session_id):
        engine = original_build(self, task, session_id=session_id)
        provider.engine = engine
        return engine

    monkeypatch.setattr(SessionManager, "_build_task_engine", _capture)

    run = await manager._run_scheduled_task(task, trigger="manual")

    assert run.status == "canceled"
    persisted = manager.task_store.runs(task.id)
    assert len(persisted) == 1 and persisted[0].status == "canceled"
    # The busy marker must still be released like any other ending.
    assert manager.is_running(run.session_id) is False


async def test_scheduled_run_canceled_notification_is_not_marked_done(
    tmp_path, monkeypatch
):
    """The external notify_target message must not say "✓ done" for a run the user
    stopped — that reads as the automation lying about having finished."""
    from coworker.connectors import senders as senders_mod
    from coworker.providers import AssistantTurn, ModelCapabilities, ProviderClient
    from coworker.server.manager import SessionManager

    class InterruptingProvider(ProviderClient):
        def __init__(self):
            self.engine = None

        def complete(self, *, model, messages, tools=None, **settings):
            assert self.engine is not None
            self.engine.request_interrupt()
            return AssistantTurn(text="ignored", finish_reason="stop")

        def capabilities(self, model):
            return ModelCapabilities()

    monkeypatch.setenv("COWORKER_STATE_DIR", str(tmp_path / "state"))
    ws = tmp_path / "ws"
    ws.mkdir()
    provider = InterruptingProvider()
    manager = SessionManager(data_dir=tmp_path / "data", provider=provider)
    task = _task(workspace=str(ws), agent="cowork", notify_target="telegram:12345")
    manager.task_store.save(task)
    manager.secrets.put("telegram:default", {"bot_token": "test-token"})

    original_build = SessionManager._build_task_engine

    def _capture(self, task, *, session_id):
        engine = original_build(self, task, session_id=session_id)
        provider.engine = engine
        return engine

    monkeypatch.setattr(SessionManager, "_build_task_engine", _capture)

    sent: list[tuple] = []

    def fake_sender(token, chat_id, text, thread_id=None):
        sent.append((token, chat_id, text, thread_id))
        from coworker.connectors.base import SendResult

        return SendResult(ok=True, message_id="1")

    monkeypatch.setitem(senders_mod.DEFAULT_SENDERS, "telegram", fake_sender)

    run = await manager._run_scheduled_task(task, trigger="manual")

    assert run.status == "canceled"
    assert len(sent) == 1
    text = sent[0][2]
    assert not text.startswith("✓"), f"canceled run must not use the 'done' checkmark: {text!r}"
    assert "完成" not in text


# -- mark_idle failing must not double-record the run (bug: ok AND error rows) ------
async def test_scheduled_run_survives_mark_idle_failure_with_single_record(
    tmp_path, monkeypatch
):
    """`_run_scheduled_task`'s outer `finally` calls `mark_idle` bare. Before the fix, a
    `mark_idle` exception propagated straight out of `_run_scheduled_task` — even though
    the run's true verdict (`status="ok"`) was already persisted via
    `task_store.add_run(run)` moments earlier. At the manager layer that just means the
    coroutine raises after doing its job; the full double-write only happens one layer up,
    in the scheduler (see the sibling `Scheduler`-level test below) — but a raise escaping
    here at all is the bug, so pin that down directly first."""
    from coworker.providers import AssistantTurn, ModelCapabilities, ProviderClient
    from coworker.server.manager import SessionManager

    class ScriptedProvider(ProviderClient):
        def complete(self, *, model, messages, tools=None, **settings):
            return AssistantTurn(text="done", finish_reason="stop")

        def capabilities(self, model):
            return ModelCapabilities()

    monkeypatch.setenv("COWORKER_STATE_DIR", str(tmp_path / "state"))
    ws = tmp_path / "ws"
    ws.mkdir()
    manager = SessionManager(data_dir=tmp_path / "data", provider=ScriptedProvider())
    task = _task(workspace=str(ws), agent="cowork")
    manager.task_store.save(task)

    def _boom(session_id):
        raise RuntimeError("mark_idle boom")

    monkeypatch.setattr(manager, "mark_idle", _boom)

    # Must NOT raise: mark_idle's failure is logged, not propagated.
    run = await manager._run_scheduled_task(task, trigger="manual")

    assert run.status == "ok"
    persisted = manager.task_store.runs(task.id)
    assert len(persisted) == 1 and persisted[0].status == "ok"


async def test_scheduler_mark_idle_failure_does_not_duplicate_run_record(
    tmp_path, monkeypatch
):
    """End-to-end reproduction of the reported bug through the real `Scheduler`: before
    the fix, `mark_idle`'s exception escaped `_run_scheduled_task` (which had already
    persisted the run as `status="ok"`), so `Scheduler._run_claimed`'s `except Exception`
    caught it and persisted a SECOND `TaskRun` with `status="error"` for the very same
    run — one physical run, two history rows, and the task's own `last_status` clobbered
    to "error" even though it actually succeeded."""
    from coworker.automation import Scheduler
    from coworker.providers import AssistantTurn, ModelCapabilities, ProviderClient
    from coworker.server.manager import SessionManager

    class ScriptedProvider(ProviderClient):
        def complete(self, *, model, messages, tools=None, **settings):
            return AssistantTurn(text="done", finish_reason="stop")

        def capabilities(self, model):
            return ModelCapabilities()

    monkeypatch.setenv("COWORKER_STATE_DIR", str(tmp_path / "state"))
    ws = tmp_path / "ws"
    ws.mkdir()
    manager = SessionManager(data_dir=tmp_path / "data", provider=ScriptedProvider())
    task = _task(workspace=str(ws), agent="cowork")
    manager.task_store.save(task)

    def _boom(session_id):
        raise RuntimeError("mark_idle boom")

    monkeypatch.setattr(manager, "mark_idle", _boom)

    sched = Scheduler(manager.task_store, manager._run_scheduled_task)
    run = await sched.run_task(task, trigger="manual")

    assert run is not None and run.status == "ok"
    persisted = manager.task_store.runs(task.id)
    assert len(persisted) == 1, (
        f"expected exactly one TaskRun, got {len(persisted)}: "
        f"{[r.status for r in persisted]}"
    )
    assert persisted[0].status == "ok"
    fresh = manager.task_store.get(task.id)
    assert fresh.last_status == "ok"


def test_task_engine_has_no_scheduling_tools(tmp_path, monkeypatch):
    """A scheduled run executes its instructions — it must not be able to (re)schedule. With
    instructions like 'every day at 5:32pm, prepare…', an agent holding create_scheduled_task
    creates another automation instead of doing the task."""
    from coworker.providers import (
        AssistantTurn as _AT,
        ModelCapabilities,
        ProviderClient,
    )
    from coworker.server import SessionManager

    class _Provider(ProviderClient):
        def complete(self, *, model, messages, tools=None, **settings):
            return _AT(text="ok", finish_reason="stop")

        def capabilities(self, model):
            return ModelCapabilities()

    monkeypatch.setenv("COWORKER_STATE_DIR", str(tmp_path / "state"))
    ws = tmp_path / "ws"
    ws.mkdir()
    manager = SessionManager(data_dir=tmp_path / "data", provider=_Provider())
    task = _task(workspace=str(ws), agent="cowork")
    manager.task_store.save(task)

    engine = manager._build_task_engine(task, session_id="__run__test")
    names = set(engine.registry.names())
    assert "create_scheduled_task" not in names
    assert "update_scheduled_task" not in names
    assert "write_file" in names  # the deliverable tools are still there


async def test_manual_run_prepare_and_finalize(tmp_path, monkeypatch):
    from coworker.providers import AssistantTurn, ModelCapabilities, ProviderClient
    from coworker.server.manager import SessionManager

    class ScriptedProvider(ProviderClient):
        def __init__(self, turns):
            self._turns = list(turns)

        def complete(self, *, model, messages, tools=None, **settings):
            return self._turns.pop(0)

        def capabilities(self, model):
            return ModelCapabilities()

    monkeypatch.setenv("COWORKER_STATE_DIR", str(tmp_path / "state"))
    ws = tmp_path / "ws"
    ws.mkdir()
    manager = SessionManager(
        data_dir=tmp_path / "data",
        provider=ScriptedProvider(
            [AssistantTurn(text="Done — briefing ready.", finish_reason="stop")]
        ),
    )
    task = _task(workspace=str(ws), agent="cowork")
    manager.task_store.save(task)

    # prepare: a "running" run + a session to open live (NOT executed yet)
    prep = manager.prepare_manual_run(task.id)
    assert prep["ok"] and prep["session_id"] == f"__run__{prep['run_id']}"
    # The prompt wraps the instructions in execute-now framing (so the live agent runs the task
    # instead of re-scheduling it) and carries them verbatim.
    assert prep["agent"] == "cowork"
    assert task.instructions in prep["prompt"]
    assert "do not create or modify any scheduled tasks" in prep["prompt"]
    assert manager.task_store.runs(task.id)[0].status == "running"

    # the GUI drives the run live over the session, then finalize records the outcome
    engine = manager.get_engine(prep["session_id"], workspace=str(ws), agent="cowork")
    async for _ in engine.run(prep["prompt"]):
        pass
    manager.save(prep["session_id"], engine)

    out = manager.finalize_manual_run(task.id, prep["run_id"])
    assert out["ok"] and out["run"]["status"] == "ok"
    assert out["run"]["result_text"] == "Done — briefing ready."
    assert manager.task_store.get(task.id).run_count == 1


async def test_manual_run_interrupted_is_canceled_not_ok(tmp_path, monkeypatch):
    """A manual run never goes through `_run_scheduled_task`'s INTERRUPTED handling — the
    GUI drives the turn straight over the session WS, and `finalize_manual_run` only finds
    out afterward, from the session's transcript. Before the fix it unconditionally wrote
    `status="ok"` once the first turn had ended, so a run the user stopped mid-flight
    (`request_interrupt()`, same public Stop-button path as the scheduled test above) was
    recorded exactly like a real completion."""
    from coworker.providers import AssistantTurn, ModelCapabilities, ProviderClient
    from coworker.server.manager import SessionManager

    class InterruptingProvider(ProviderClient):
        def __init__(self):
            self.engine = None  # set once the manual run's engine exists

        def complete(self, *, model, messages, tools=None, **settings):
            assert self.engine is not None, "engine must be captured before first call"
            self.engine.request_interrupt()
            return AssistantTurn(text="ignored", finish_reason="stop")

        def capabilities(self, model):
            return ModelCapabilities()

    monkeypatch.setenv("COWORKER_STATE_DIR", str(tmp_path / "state"))
    ws = tmp_path / "ws"
    ws.mkdir()
    provider = InterruptingProvider()
    manager = SessionManager(data_dir=tmp_path / "data", provider=provider)
    task = _task(workspace=str(ws), agent="cowork")
    manager.task_store.save(task)

    prep = manager.prepare_manual_run(task.id)
    engine = manager.get_engine(prep["session_id"], workspace=str(ws), agent="cowork")
    provider.engine = engine
    async for _ in engine.run(prep["prompt"]):
        pass
    manager.save(prep["session_id"], engine)

    out = manager.finalize_manual_run(task.id, prep["run_id"])
    assert out["ok"] and out["run"]["status"] == "canceled"
    persisted = manager.task_store.runs(task.id)
    assert len(persisted) == 1 and persisted[0].status == "canceled"
    assert manager.task_store.get(task.id).last_status == "canceled"


async def test_manual_run_engine_error_is_error_not_ok(tmp_path, monkeypatch):
    """A turn that ends on the engine's own public ERROR signal — here a reply the
    endpoint can't parse as a tool call, `engine.py`'s `looks_like_unparsed_tool_call`
    path, persisted as a `role="notice", kind="error"` message — is a crashed run, not a
    successful one. Before the fix `finalize_manual_run` never looked at how the turn
    ended and recorded it "ok" regardless."""
    from coworker.providers import AssistantTurn, ModelCapabilities, ProviderClient
    from coworker.server.manager import SessionManager

    leaked = "Let me check.\n<tool_call>\n<function=nope_not_a_tool>\n<parameter="

    class ScriptedProvider(ProviderClient):
        def complete(self, *, model, messages, tools=None, **settings):
            return AssistantTurn(text=leaked, finish_reason="stop")

        def capabilities(self, model):
            return ModelCapabilities()

    monkeypatch.setenv("COWORKER_STATE_DIR", str(tmp_path / "state"))
    ws = tmp_path / "ws"
    ws.mkdir()
    manager = SessionManager(data_dir=tmp_path / "data", provider=ScriptedProvider())
    task = _task(workspace=str(ws), agent="cowork")
    manager.task_store.save(task)

    prep = manager.prepare_manual_run(task.id)
    engine = manager.get_engine(prep["session_id"], workspace=str(ws), agent="cowork")
    async for _ in engine.run(prep["prompt"]):
        pass
    manager.save(prep["session_id"], engine)
    # Sanity: pin down the public signal this test (and the fix) relies on.
    assert engine.messages[-1]["role"] == "notice"
    assert engine.messages[-1]["kind"] == "error"

    out = manager.finalize_manual_run(task.id, prep["run_id"])
    assert out["ok"] and out["run"]["status"] == "error"
    assert out["run"]["error"]
    persisted = manager.task_store.runs(task.id)
    assert len(persisted) == 1 and persisted[0].status == "error"
    assert manager.task_store.get(task.id).last_status == "error"


async def test_manual_run_unhandled_crash_before_reply_is_error_not_ok(
    tmp_path, monkeypatch
):
    """A real engine bug — an exception raised from inside `_loop()` OUTSIDE the
    provider-call try/except (so the engine itself appends no "error" notice) — leaves
    the transcript ending on the plain `user` message the turn started with, nothing
    else, when nothing else appends a notice either. Over the real WS, `run_turn`'s
    outer `except` (app.py) does append one (see `test_manual_run_crash_over_ws_is_error`);
    this test drives `engine.run()` directly, so it models the turn whose notice never
    got appended (`run_turn` contains a failure of that append and only logs it). Before
    the fix `_run_outcome_from_transcript` treated "no notice at the tail" as "the turn
    completed normally" unconditionally, so this recorded "ok"."""
    from coworker.providers import AssistantTurn, ModelCapabilities, ProviderClient
    from coworker.server.manager import SessionManager
    import coworker.engine as engine_mod

    class ScriptedProvider(ProviderClient):
        def complete(self, *, model, messages, tools=None, **settings):
            return AssistantTurn(text="ignored", finish_reason="stop")

        def capabilities(self, model):
            return ModelCapabilities()

    def _boom(turn):
        raise RuntimeError("injected engine bug")

    # `_sanitize_mangled_calls` runs right after the provider call returns
    # successfully — outside the try/except that surrounds the provider call itself
    # (see `coworker/engine.py` around `_sanitize_mangled_calls(turn)`), so this
    # reproduces an unhandled engine bug rather than a provider failure.
    monkeypatch.setattr(engine_mod, "_sanitize_mangled_calls", _boom)
    monkeypatch.setenv("COWORKER_STATE_DIR", str(tmp_path / "state"))
    ws = tmp_path / "ws"
    ws.mkdir()
    manager = SessionManager(data_dir=tmp_path / "data", provider=ScriptedProvider())
    task = _task(workspace=str(ws), agent="cowork")
    manager.task_store.save(task)

    prep = manager.prepare_manual_run(task.id)
    engine = manager.get_engine(prep["session_id"], workspace=str(ws), agent="cowork")
    with pytest.raises(RuntimeError):
        async for _ in engine.run(prep["prompt"]):
            pass
    # `run_turn`'s `finally` in app.py always saves + broadcasts turn_done even when
    # the awaited turn raised — reproduce that here rather than relying on run_turn.
    manager.save(prep["session_id"], engine)
    # Sanity: pin down the shape this test (and the fix) relies on — no notice at all.
    assert engine.messages[-1]["role"] == "user"

    out = manager.finalize_manual_run(task.id, prep["run_id"])
    assert out["ok"] and out["run"]["status"] == "error"
    assert out["run"]["error"]
    persisted = manager.task_store.runs(task.id)
    assert len(persisted) == 1 and persisted[0].status == "error"
    assert manager.task_store.get(task.id).last_status == "error"


async def test_manual_run_steered_turn_ending_on_iteration_gate_is_ok(
    tmp_path, monkeypatch
):
    """Steering (`engine.queue_steering` — what `deliver_to_session` does with a
    self-wake, a channel message or a team steer that reaches a busy session; a message
    typed in the app mid-turn is rejected by the WS instead) is appended as a `user`
    message after the tool round. When `max_iterations` runs out right then, the
    turn still ends NORMALLY (TURN_END `max_iterations_exceeded`) — on
    `[user, assistant, tool, user]`. The no-reply fallback used to key on the `user`
    tail alone and recorded this as an error "without any response"."""
    from coworker.providers import (
        AssistantTurn,
        ModelCapabilities,
        ProviderClient,
        ToolCall,
    )
    from coworker.server.manager import SessionManager

    class SteeredProvider(ProviderClient):
        def __init__(self):
            self.engine = None  # set once the manual run's engine exists

        def complete(self, *, model, messages, tools=None, **settings):
            self.engine.queue_steering("also check b.txt")
            call = ToolCall(id="call_1", name="read_file", arguments={"path": "a.txt"})
            return AssistantTurn(tool_calls=[call])

        def capabilities(self, model):
            return ModelCapabilities()

    monkeypatch.setenv("COWORKER_STATE_DIR", str(tmp_path / "state"))
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "a.txt").write_text("hello\n", encoding="utf-8")
    provider = SteeredProvider()
    manager = SessionManager(data_dir=tmp_path / "data", provider=provider)
    task = _task(workspace=str(ws), agent="cowork")
    manager.task_store.save(task)

    prep = manager.prepare_manual_run(task.id)
    engine = manager.get_engine(prep["session_id"], workspace=str(ws), agent="cowork")
    engine.max_iterations = 1
    provider.engine = engine

    async def drain():
        return [event async for event in engine.run(prep["prompt"])]

    events = await asyncio.wait_for(drain(), timeout=10)
    manager.save(prep["session_id"], engine)
    # Sanity: pin down the shape — a normal ending on a steering `user` tail.
    (turn_end,) = [e for e in events if e.type.value == "turn_end"]
    assert turn_end.data["status"] == "max_iterations_exceeded"
    roles = [m["role"] for m in engine.messages if m["role"] != "system"]
    assert roles == ["user", "assistant", "tool", "user"], roles

    out = manager.finalize_manual_run(task.id, prep["run_id"])
    assert out["ok"] and out["run"]["status"] == "ok"
    assert out["run"]["error"] is None
    assert manager.task_store.get(task.id).last_status == "ok"


def _notice(kind, text=None):
    message = {"role": "notice", "kind": kind}
    if text:
        message["text"] = text
    return message


_USER = {"role": "user", "content": "run the task"}
_REPLY = {"role": "assistant", "content": "done"}
_CALL = {
    "role": "assistant",
    "content": "",
    "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "read_file"}}],
}
_RESULT = {"role": "tool", "tool_call_id": "c1", "content": "hello"}


@pytest.mark.parametrize(
    "messages, expected",
    [
        pytest.param([], ("ok", None), id="empty"),
        pytest.param([_USER, _REPLY], ("ok", None), id="assistant_tail"),
        pytest.param([_USER, _CALL, _RESULT], ("ok", None), id="tool_tail"),
        pytest.param(
            [_USER, _notice("turn_aborted", "the model returned nothing")],
            ("error", "the model returned nothing"),
            id="turn_aborted",
        ),
        pytest.param(
            [_USER, _notice("error", "boom"), _notice("model_switch", "Model switched")],
            ("error", "boom"),
            id="error_then_model_switch",
        ),
        pytest.param(
            [_USER, _notice("interrupted"), _notice("model_switch", "Model switched")],
            ("canceled", None),
            id="interrupted_then_model_switch",
        ),
        pytest.param(
            [_USER, _REPLY, _notice("turn_truncated", "the reply may be cut off")],
            ("ok", None),
            id="truncated_after_reply",
        ),
        pytest.param(
            [_USER, _CALL, _RESULT, {"role": "user", "content": "also check b.txt"}],
            ("ok", None),
            id="steering_tail_after_reply",
        ),
        pytest.param(
            [{"role": "system", "content": "sys"}, _USER],
            ("error", "the turn ended before any reply"),
            id="user_tail_no_reply",
        ),
    ],
)
def test_run_outcome_from_transcript(messages, expected):
    """The verdict table `finalize_manual_run` applies, one row per tail shape:
    `turn_aborted` is a failed turn exactly like `error`; a `model_switch` after the
    deciding notice changes nothing; `turn_truncated` is appended after an answer that
    DID arrive (engine.py), so the turn completed; a steering `user` tail after a reply
    is a normal ending."""
    from coworker.server.manager import _run_outcome_from_transcript

    assert _run_outcome_from_transcript(messages) == expected


_BOOKKEEPING_KINDS = [
    "model_switch",
    "mode_switch",
    "mode_notice",
    "mcp_error",
    "project_presence",
    "compacted",
    "turn_retry",
    "reviewer_paused",
    "answer_superseded",
]


@pytest.mark.parametrize("kind", _BOOKKEEPING_KINDS)
@pytest.mark.parametrize(
    "deciding, expected",
    [
        pytest.param(_notice("interrupted"), ("canceled", None), id="after_stop"),
        pytest.param(_notice("error", "boom"), ("error", "boom"), id="after_error"),
    ],
)
def test_bookkeeping_notice_does_not_change_the_verdict(kind, deciding, expected):
    """A bookkeeping notice after the deciding one — say a mode switch between the Stop
    and the finalize call — records something about the session, not about how the
    turn ended, so the verdict stays the one the deciding notice gave."""
    from coworker.server.manager import _run_outcome_from_transcript

    messages = [_USER, deciding, _notice(kind, f"{kind} text")]
    assert _run_outcome_from_transcript(messages) == expected


def test_retry_notice_before_a_gate_does_not_read_as_a_reply():
    """`turn_retry` announces a re-send; if the turn's gate stops it right there, what
    precedes the retry notice decides — here nothing but the prompt, so no reply."""
    from coworker.server.manager import _run_outcome_from_transcript

    messages = [_USER, _notice("turn_retry", "Retrying (1/2)")]
    assert _run_outcome_from_transcript(messages) == (
        "error",
        "the turn ended before any reply",
    )


def _answerless_over_budget_provider():
    """Every round comes back empty (no text, no tool call) and bills 1000 prompt
    tokens, twice the 500-token turn budget the test below sets."""
    from coworker.providers import AssistantTurn, ModelCapabilities, ProviderClient
    from coworker.providers.base import TokenUsage

    class AnswerlessProvider(ProviderClient):
        def complete(self, *, model, messages, tools=None, **settings):
            return AssistantTurn(finish_reason="stop", usage=TokenUsage(input=1000))

        def capabilities(self, model):
            return ModelCapabilities()

    return AnswerlessProvider()


@pytest.mark.parametrize("path", ["scheduled", "manual"])
async def test_retry_then_token_gate_reaches_the_no_reply_branch(tmp_path, monkeypatch, path):
    """The shape above, left by the real engine: the empty answer is announced with
    `turn_retry`, then the token gate ends the turn before the re-send (TURN_END
    `max_tokens_exceeded`). The turn does NOT go on past that bookkeeping notice, the
    transcript ends on `[user, turn_retry]`, and both run paths record "error"."""
    from coworker.server.manager import SessionManager

    monkeypatch.setenv("COWORKER_STATE_DIR", str(tmp_path / "state"))
    ws = tmp_path / "ws"
    ws.mkdir()
    manager = SessionManager(
        data_dir=tmp_path / "data", provider=_answerless_over_budget_provider()
    )
    task = _task(workspace=str(ws), agent="cowork")
    manager.task_store.save(task)

    def configure(engine):
        engine.max_turn_tokens = 500
        engine.retry_sleep = _no_wait

    if path == "scheduled":
        original_build = SessionManager._build_task_engine

        def _build(self, task, *, session_id):
            engine = original_build(self, task, session_id=session_id)
            configure(engine)
            return engine

        monkeypatch.setattr(SessionManager, "_build_task_engine", _build)
        run = await asyncio.wait_for(manager._run_scheduled_task(task, trigger="schedule"), 10)
        session_id, verdict = run.session_id, (run.status, run.error)
    else:
        prep = manager.prepare_manual_run(task.id)
        engine = manager.get_engine(prep["session_id"], workspace=str(ws), agent="cowork")
        configure(engine)

        async def drain():
            return [event async for event in engine.run(prep["prompt"])]

        events = await asyncio.wait_for(drain(), timeout=10)
        (turn_end,) = [e for e in events if e.type.value == "turn_end"]
        assert turn_end.data["status"] == "max_tokens_exceeded"
        manager.save(prep["session_id"], engine)
        out = manager.finalize_manual_run(task.id, prep["run_id"])
        session_id, verdict = prep["session_id"], (out["run"]["status"], out["run"]["error"])

    shape = [
        (m["role"], m.get("kind"))
        for m in manager.session_messages(session_id)
        if m["role"] != "system"
    ]
    assert shape == [("user", None), ("notice", "turn_retry")], shape
    assert verdict == ("error", "the turn ended before any reply")


def test_every_notice_kind_is_classified():
    """Every kind passed to `_append_notice` anywhere in coworker/ is either one the
    verdict is read from or a bookkeeping kind the walk looks through. A new kind that
    is neither would silently be read as a completed turn wherever it lands last."""
    import re
    from pathlib import Path

    import coworker
    from coworker.server.manager import (
        _BOOKKEEPING_NOTICE_KINDS,
        _RUN_FAILED_NOTICE_KINDS,
    )

    root = Path(coworker.__file__).parent
    pattern = re.compile(r'_append_notice\(\s*"([a-z_]+)"')
    found = {
        match.group(1)
        for path in root.rglob("*.py")
        for match in pattern.finditer(path.read_text(encoding="utf-8"))
    }
    # Sanity: the scan does see kinds from all three files that append notices.
    assert {"interrupted", "mode_switch", "project_presence"} <= found, found
    verdict_kinds = {"interrupted", "turn_truncated"} | _RUN_FAILED_NOTICE_KINDS
    assert not (verdict_kinds & _BOOKKEEPING_NOTICE_KINDS)
    assert set(_BOOKKEEPING_KINDS) == _BOOKKEEPING_NOTICE_KINDS
    assert found - verdict_kinds - _BOOKKEEPING_NOTICE_KINDS == set()


def test_manual_run_stop_then_mode_switch_is_still_canceled(tmp_path, monkeypatch):
    """Over the real WS, the user stops the manual run, then switches the session to
    plan mode before the GUI's finalize call lands. The `mode_switch` notice that switch
    appends becomes the transcript tail and used to be read as the verdict — "ok"."""
    from coworker.providers import AssistantTurn, ModelCapabilities, ProviderClient
    from coworker.server.manager import SessionManager

    class InterruptingProvider(ProviderClient):
        def __init__(self):
            self.engine = None  # captured once the WS has built the engine

        def complete(self, *, model, messages, tools=None, **settings):
            if messages and "title chat sessions" in str(messages[0].get("content", "")):
                return AssistantTurn(text="small-talk", finish_reason="stop")
            self.engine.request_interrupt()
            return AssistantTurn(text="ignored", finish_reason="stop")

        def capabilities(self, model):
            return ModelCapabilities()

    monkeypatch.setenv("COWORKER_STATE_DIR", str(tmp_path / "state"))
    ws = tmp_path / "ws"
    ws.mkdir()
    provider = InterruptingProvider()
    manager = SessionManager(data_dir=tmp_path / "data", provider=provider)
    task = _task(workspace=str(ws), agent="cowork")
    manager.task_store.save(task)

    def capture(session_id):
        provider.engine = manager._engines[session_id]

    def switch_to_plan(sock):
        sock.send_json({"type": "set_mode", "mode": "plan"})
        while sock.receive_json()["type"] != "mode_changed":
            pass

    prep, out = _drive_manual_run_over_ws(
        manager, task, before_send=capture, after_turn=switch_to_plan
    )

    kinds = [m.get("kind") for m in manager.session_messages(prep["session_id"])[-2:]]
    assert kinds == ["interrupted", "mode_switch"], kinds
    assert out["ok"] and out["run"]["status"] == "canceled"
    assert manager.task_store.get(task.id).last_status == "canceled"


def _stopping_provider():
    """Presses Stop on `.engine` (set it before the run's first model call) during that
    call; a title request just gets a title."""
    from coworker.providers import AssistantTurn, ModelCapabilities, ProviderClient

    class StoppingProvider(ProviderClient):
        engine = None

        def complete(self, *, model, messages, tools=None, **settings):
            if messages and "title chat sessions" in str(messages[0].get("content", "")):
                return AssistantTurn(text="small-talk", finish_reason="stop")
            self.engine.request_interrupt()
            return AssistantTurn(text="ignored", finish_reason="stop")

        def capabilities(self, model):
            return ModelCapabilities()

    return StoppingProvider()


def test_manual_run_stop_then_granted_folder_notice_is_still_canceled(tmp_path, monkeypatch):
    """`project_presence` lands after the turn ended too. Over the real WS the Stop ends
    the manual run's turn; before the finalize call the user grants a folder whose
    project already has memory (`add_root`, what `POST /v1/sessions/{id}/roots` calls).
    The notice lands behind `interrupted`, and the run is still "canceled"."""
    from coworker.memory.base import Scope
    from coworker.server.manager import SessionManager

    monkeypatch.setenv("COWORKER_STATE_DIR", str(tmp_path / "state"))
    ws = tmp_path / "ws"
    ws.mkdir()
    known = tmp_path / "known"
    known.mkdir()
    provider = _stopping_provider()
    manager = SessionManager(data_dir=tmp_path / "data", provider=provider)
    manager.memory_store.add("fact", scope=Scope.WORKSPACE, workspace=str(known.resolve()))
    task = _task(workspace=str(ws), agent="cowork")
    manager.task_store.save(task)
    session: dict = {}

    def capture(session_id):
        session["id"] = session_id
        provider.engine = manager._engines[session_id]

    def grant_known_folder(sock):
        granted = manager.add_root(session["id"], str(known))
        assert granted["ok"] and granted["notice"], granted

    prep, out = _drive_manual_run_over_ws(
        manager, task, before_send=capture, after_turn=grant_known_folder
    )

    kinds = [m.get("kind") for m in manager.session_messages(prep["session_id"])[-2:]]
    assert kinds == ["interrupted", "project_presence"], kinds
    assert out["ok"] and out["run"]["status"] == "canceled"


def test_manual_run_stop_then_mcp_error_on_reconnect_is_still_canceled(tmp_path, monkeypatch):
    """`mcp_error` is appended at a WS connect that builds the session's engine, so it
    can land after the turn ended as well. Over the real WS the Stop ends the manual
    run's turn; the backend then restarts (a new `SessionManager` on the same data)
    before the finalize call, the GUI reconnects, and an MCP server fails to start on
    that rebuild. The notice lands behind `interrupted`, and the run is still
    "canceled". The whole exchange runs on a daemon thread joined with a deadline."""
    from types import SimpleNamespace
    from urllib.parse import quote

    from fastapi.testclient import TestClient

    from coworker.server.app import create_app
    from coworker.server.manager import SessionManager

    monkeypatch.setenv("COWORKER_STATE_DIR", str(tmp_path / "state"))
    ws = tmp_path / "ws"
    ws.mkdir()
    servers: list = []  # no MCP server is configured while the run's turn runs
    monkeypatch.setattr(
        "coworker.server.manager.load_mcp_servers", lambda *a, **k: list(servers)
    )
    provider = _stopping_provider()
    manager = SessionManager(data_dir=tmp_path / "data", provider=provider)
    task = _task(workspace=str(ws), agent="cowork")
    manager.task_store.save(task)
    box: dict = {}

    async def failing_ensure(server, **kwargs):
        raise RuntimeError("spawn failed")

    def drive():
        try:
            client = TestClient(create_app(manager))
            prep = box["prep"] = client.post(f"/v1/automations/{task.id}/run").json()
            url = (
                f"/ws/session/{prep['session_id']}"
                f"?workspace={quote(prep['workspace'])}&agent={prep['agent']}"
            )
            with client.websocket_connect(url) as sock:
                assert sock.receive_json()["type"] == "ready"
                provider.engine = manager._engines[prep["session_id"]]
                sock.send_json({"type": "user_message", "text": prep["prompt"]})
                while sock.receive_json()["type"] != "turn_done":
                    pass
            servers.append(
                SimpleNamespace(
                    name="flaky",
                    transport="stdio",
                    url=None,
                    auth=None,
                    enabled=True,
                    include_tools=None,
                    exclude_tools=None,
                    requires_approval=True,
                )
            )
            restarted = box["restarted"] = SessionManager(
                data_dir=tmp_path / "data", provider=provider
            )
            restarted.mcp.ensure = failing_ensure
            restarted.mcp.last_stderr = lambda name: None
            client = TestClient(create_app(restarted))
            with client.websocket_connect(url) as sock:
                assert sock.receive_json()["type"] == "ready"
            box["finalized"] = client.post(
                f"/v1/automations/{task.id}/runs/{prep['run_id']}/finalize"
            ).json()
        except BaseException as exc:  # re-raised on the test thread below
            box["error"] = exc

    worker = threading.Thread(target=drive, daemon=True)
    worker.start()
    worker.join(timeout=30)
    assert not worker.is_alive(), "manual run or reconnect over WS never finished"
    if "error" in box:
        raise box["error"]

    messages = box["restarted"].session_messages(box["prep"]["session_id"])
    kinds = [m.get("kind") for m in messages[-2:]]
    assert kinds == ["interrupted", "mcp_error"], kinds
    assert box["finalized"]["ok"] and box["finalized"]["run"]["status"] == "canceled"


def _drive_manual_run_over_ws(manager, task, *, before_send=None, after_turn=None):
    """Run a manual run the way the GUI does — `POST .../run`, open the session WS, send
    the prompt, wait for `turn_done`, then `POST .../finalize` — and return
    `(prep, finalize_response)`. The whole exchange runs on a daemon thread joined with a
    deadline: this repo has no pytest timeout, and a regression that never sends
    `turn_done` would otherwise block `receive_json()` forever."""
    from urllib.parse import quote

    from fastapi.testclient import TestClient

    from coworker.server.app import create_app

    client = TestClient(create_app(manager))
    prep = client.post(f"/v1/automations/{task.id}/run").json()
    url = (
        f"/ws/session/{prep['session_id']}"
        f"?workspace={quote(prep['workspace'])}&agent={prep['agent']}"
    )
    finalize_url = f"/v1/automations/{task.id}/runs/{prep['run_id']}/finalize"
    box: dict = {}

    def drive():
        try:
            with client.websocket_connect(url) as ws:
                assert ws.receive_json()["type"] == "ready"
                if before_send is not None:
                    before_send(prep["session_id"])
                ws.send_json({"type": "user_message", "text": prep["prompt"]})
                while ws.receive_json()["type"] != "turn_done":
                    pass
                if after_turn is not None:
                    after_turn(ws)
                box["finalized"] = client.post(finalize_url).json()
        except BaseException as exc:  # re-raised on the test thread below
            box["error"] = exc

    worker = threading.Thread(target=drive, daemon=True)
    worker.start()
    worker.join(timeout=30)
    assert not worker.is_alive(), "manual run over WS never reached turn_done"
    if "error" in box:
        raise box["error"]
    return prep, box["finalized"]


@pytest.mark.parametrize("crash_at_round", [1, 2], ids=["before_reply", "after_tool_round"])
def test_manual_run_crash_over_ws_is_error(tmp_path, monkeypatch, crash_at_round):
    """An engine bug that escapes the turn, driven through the REAL session WS and the
    finalize endpoint: `run_turn`'s outer `except` (app.py) appends a `kind="error"`
    notice before `turn_done`, and `finalize_manual_run` must read that as "error" —
    whether the crash hit before the first reply (round 1) or after a completed tool
    round (round 2, tail `[..., tool, error notice]`). Without that notice the second
    shape ends on a `tool` message, which reads as a completed turn."""
    import coworker.engine as engine_mod
    from coworker.providers import (
        AssistantTurn,
        ModelCapabilities,
        ProviderClient,
        ToolCall,
    )
    from coworker.server.manager import SessionManager

    class ScriptedProvider(ProviderClient):
        def __init__(self):
            self.calls = 0

        def complete(self, *, model, messages, tools=None, **settings):
            if messages and "title chat sessions" in str(messages[0].get("content", "")):
                return AssistantTurn(text="small-talk", finish_reason="stop")
            self.calls += 1
            if self.calls == 1:
                call = ToolCall(id="call_1", name="read_file", arguments={"path": "a.txt"})
                return AssistantTurn(tool_calls=[call])
            return AssistantTurn(text="never reached", finish_reason="stop")

        def capabilities(self, model):
            return ModelCapabilities()

    real_sanitize = engine_mod._sanitize_mangled_calls
    rounds = {"n": 0}

    def sanitize_then_crash(turn):
        # Runs right after each provider call returns, outside the provider-call
        # try/except in `_loop()`: a raise here escapes `engine.run()` unhandled.
        rounds["n"] += 1
        if rounds["n"] == crash_at_round:
            raise RuntimeError("injected engine bug")
        return real_sanitize(turn)

    monkeypatch.setattr(engine_mod, "_sanitize_mangled_calls", sanitize_then_crash)
    monkeypatch.setenv("COWORKER_STATE_DIR", str(tmp_path / "state"))
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "a.txt").write_text("hello\n", encoding="utf-8")
    manager = SessionManager(data_dir=tmp_path / "data", provider=ScriptedProvider())
    task = _task(workspace=str(ws), agent="cowork")
    manager.task_store.save(task)

    prep, out = _drive_manual_run_over_ws(manager, task)

    record = manager.session_store.load(prep["session_id"])
    tail = record.messages[-2:]
    assert tail[-1]["role"] == "notice" and tail[-1]["kind"] == "error", tail
    if crash_at_round == 2:
        assert tail[0]["role"] == "tool", tail  # the crash came after a tool round
    assert out["ok"] and out["run"]["status"] == "error"
    assert out["run"]["error"] == tail[-1]["text"]
    assert manager.task_store.get(task.id).last_status == "error"


def test_manual_run_finalize_reads_the_live_engine_when_saves_fail(tmp_path, monkeypatch):
    """`finalize_manual_run` judges the same messages the GUI shows (`session_messages`):
    the cached engine's list while it lives. Here every `save` fails — the case
    `run_turn`'s own comment names ("if the failure was a save, the `finally`'s save may
    fail too") — so the turn crashes at its `turn_start` checkpoint, `run_turn` appends
    its error notice to the live engine, and nothing ever reaches the session store.
    Reading only the stored record found no messages at all and recorded "ok"."""
    from coworker.providers import AssistantTurn, ModelCapabilities, ProviderClient
    from coworker.server.manager import SessionManager

    class ScriptedProvider(ProviderClient):
        def complete(self, *, model, messages, tools=None, **settings):
            return AssistantTurn(text="never reached", finish_reason="stop")

        def capabilities(self, model):
            return ModelCapabilities()

    monkeypatch.setenv("COWORKER_STATE_DIR", str(tmp_path / "state"))
    ws = tmp_path / "ws"
    ws.mkdir()
    manager = SessionManager(data_dir=tmp_path / "data", provider=ScriptedProvider())
    task = _task(workspace=str(ws), agent="cowork")
    manager.task_store.save(task)

    def fail_every_save(session_id):
        def save(*args, **kwargs):
            raise OSError("disk full")

        manager.save = save

    prep, out = _drive_manual_run_over_ws(manager, task, before_send=fail_every_save)

    assert manager.session_store.load(prep["session_id"]) is None  # nothing got saved
    live = manager._engines[prep["session_id"]].messages
    assert live[-1]["role"] == "notice" and live[-1]["kind"] == "error", live[-2:]
    assert out["ok"] and out["run"]["status"] == "error"
    assert out["run"]["error"] == live[-1]["text"]


# -- scheduled and manual runs judge a turn the same way ---------------------------
def _scenario_provider(scenario):
    """A provider whose one job is to end the run's turn a given way. "stop" needs the
    run's engine: set `.engine` before the first call."""
    from coworker.providers import AssistantTurn, ModelCapabilities, ProviderClient

    class ScenarioProvider(ProviderClient):
        engine = None

        def complete(self, *, model, messages, tools=None, **settings):
            if messages and "title chat sessions" in str(messages[0].get("content", "")):
                return AssistantTurn(text="small-talk", finish_reason="stop")
            if scenario == "provider_error":
                # Not transient (no status, no transient marker): no automatic retry.
                raise ValueError("the endpoint rejected the request")
            if scenario == "empty_answer":
                return AssistantTurn(finish_reason="stop")  # no text, no tool call
            if scenario == "stop":
                self.engine.request_interrupt()
                return AssistantTurn(text="ignored", finish_reason="stop")
            return AssistantTurn(text="Daily brief: all quiet.", finish_reason="stop")

        def capabilities(self, model):
            return ModelCapabilities()

    return ScenarioProvider()


async def _no_wait(delay):
    return True  # stands in for the engine's retry backoff: re-send at once


_OUTCOME_SCENARIOS = [
    pytest.param("completed", "ok", None, id="completed"),
    pytest.param(
        "provider_error", "error", "the endpoint rejected the request", id="provider_error"
    ),
    pytest.param("empty_answer", "error", "turn_aborted", id="empty_answer"),
    pytest.param("stop", "canceled", None, id="stop"),
]


@pytest.mark.parametrize("scenario, status, error", _OUTCOME_SCENARIOS)
async def test_scheduled_run_status_follows_how_the_turn_ended(
    tmp_path, monkeypatch, scenario, status, error
):
    """`_run_scheduled_task` used to look only at the INTERRUPTED event and at an
    exception out of `engine.run()`. A provider failure or an answerless turn ends
    `engine.run()` normally — the engine appends an `error` / `turn_aborted` notice and
    returns — so those runs were recorded "ok". It now reads the run's transcript with
    the same `_run_outcome_from_transcript` the manual path uses."""
    from coworker.server.manager import SessionManager

    monkeypatch.setenv("COWORKER_STATE_DIR", str(tmp_path / "state"))
    ws = tmp_path / "ws"
    ws.mkdir()
    provider = _scenario_provider(scenario)
    manager = SessionManager(data_dir=tmp_path / "data", provider=provider)
    task = _task(workspace=str(ws), agent="cowork")
    manager.task_store.save(task)

    original_build = SessionManager._build_task_engine

    def _capture(self, task, *, session_id):
        engine = original_build(self, task, session_id=session_id)
        engine.retry_sleep = _no_wait
        provider.engine = engine
        return engine

    monkeypatch.setattr(SessionManager, "_build_task_engine", _capture)

    run = await asyncio.wait_for(manager._run_scheduled_task(task, trigger="schedule"), 10)

    assert run.status == status
    persisted = manager.task_store.runs(task.id)
    assert len(persisted) == 1 and persisted[0].status == status
    tail = manager.session_store.load(run.session_id).messages[-1]
    if error == "turn_aborted":
        assert tail["kind"] == "turn_aborted" and run.error == tail["text"]
    else:
        assert run.error == error


@pytest.mark.parametrize("scenario, status, error", _OUTCOME_SCENARIOS)
async def test_manual_run_status_matches_the_scheduled_path(
    tmp_path, monkeypatch, scenario, status, error
):
    """The same four endings through the manual path (`engine.run()` on the session's
    engine, then `finalize_manual_run`) give the same status as the scheduled test
    above: one failure, one verdict, whichever way the run was started."""
    from coworker.server.manager import SessionManager

    monkeypatch.setenv("COWORKER_STATE_DIR", str(tmp_path / "state"))
    ws = tmp_path / "ws"
    ws.mkdir()
    provider = _scenario_provider(scenario)
    manager = SessionManager(data_dir=tmp_path / "data", provider=provider)
    task = _task(workspace=str(ws), agent="cowork")
    manager.task_store.save(task)

    prep = manager.prepare_manual_run(task.id)
    engine = manager.get_engine(prep["session_id"], workspace=str(ws), agent="cowork")
    engine.retry_sleep = _no_wait
    provider.engine = engine

    async def drain():
        async for _ in engine.run(prep["prompt"]):
            pass

    await asyncio.wait_for(drain(), timeout=10)
    manager.save(prep["session_id"], engine)

    out = manager.finalize_manual_run(task.id, prep["run_id"])
    assert out["ok"] and out["run"]["status"] == status


async def test_scheduled_run_error_notification_is_not_marked_done(tmp_path, monkeypatch):
    """A failed scheduled run now reaches `_notify_task_done` with status "error" (it
    only ever saw "ok" or "canceled" before). The notify_target message must not carry
    the "✓" a finished run gets, nor say it completed."""
    from coworker.connectors import senders as senders_mod
    from coworker.connectors.base import SendResult
    from coworker.server.manager import SessionManager

    monkeypatch.setenv("COWORKER_STATE_DIR", str(tmp_path / "state"))
    ws = tmp_path / "ws"
    ws.mkdir()
    manager = SessionManager(
        data_dir=tmp_path / "data", provider=_scenario_provider("provider_error")
    )
    task = _task(workspace=str(ws), agent="cowork", notify_target="telegram:12345")
    manager.task_store.save(task)
    manager.secrets.put("telegram:default", {"bot_token": "test-token"})

    sent: list[str] = []

    def fake_sender(token, chat_id, text, thread_id=None):
        sent.append(text)
        return SendResult(ok=True, message_id="1")

    monkeypatch.setitem(senders_mod.DEFAULT_SENDERS, "telegram", fake_sender)

    run = await asyncio.wait_for(manager._run_scheduled_task(task, trigger="schedule"), 10)

    assert run.status == "error"
    assert len(sent) == 1
    text = sent[0]
    assert not text.startswith("✓"), f"a failed run must not get the 'done' mark: {text!r}"
    assert "完成" not in text
    assert text.startswith(f"✗ {task.title}")


_NOTIFY_TEXTS = [
    pytest.param("completed", "ok", "✓ Daily brief\n\nDaily brief: all quiet.", id="ok"),
    pytest.param(
        "stop", "canceled", "⏹ Daily brief\n\n运行被手动停止，未产生结果。", id="canceled"
    ),
    pytest.param(
        "provider_error",
        "error",
        "✗ Daily brief\n\n运行失败，详情见应用里这次运行的记录。",
        id="error",
    ),
]


@pytest.mark.parametrize("scenario, status, expected", _NOTIFY_TEXTS)
async def test_scheduled_run_notification_text_per_status(
    tmp_path, monkeypatch, scenario, status, expected
):
    """The exact message `notify_target` gets for each way a scheduled run settles. A
    completed run gets "✓ <title>" and its summary; a stopped one and a failed one get
    their own fixed wording. Pinned byte for byte, so a status mix-up (say, every run
    announced as failed) or a changed wording turns this red."""
    from coworker.connectors import senders as senders_mod
    from coworker.connectors.base import SendResult
    from coworker.server.manager import SessionManager

    monkeypatch.setenv("COWORKER_STATE_DIR", str(tmp_path / "state"))
    ws = tmp_path / "ws"
    ws.mkdir()
    provider = _scenario_provider(scenario)
    manager = SessionManager(data_dir=tmp_path / "data", provider=provider)
    task = _task(workspace=str(ws), agent="cowork", notify_target="telegram:12345")
    manager.task_store.save(task)
    manager.secrets.put("telegram:default", {"bot_token": "test-token"})

    original_build = SessionManager._build_task_engine

    def _capture(self, task, *, session_id):
        engine = original_build(self, task, session_id=session_id)
        engine.retry_sleep = _no_wait
        provider.engine = engine
        return engine

    monkeypatch.setattr(SessionManager, "_build_task_engine", _capture)
    sent: list[tuple] = []

    def fake_sender(token, chat_id, text, thread_id=None):
        sent.append((token, chat_id, text))
        return SendResult(ok=True, message_id="1")

    monkeypatch.setitem(senders_mod.DEFAULT_SENDERS, "telegram", fake_sender)

    run = await asyncio.wait_for(manager._run_scheduled_task(task, trigger="schedule"), 10)

    assert run.status == status
    assert sent == [("test-token", "12345", expected)]


async def test_manual_run_verdict_is_the_first_turn_only(tmp_path, monkeypatch):
    """The first turn decides a manual run, as on the scheduled path: a first turn that
    fails and is then retried successfully from the session stays "error", and a second
    finalize call (the GUI only makes one) changes nothing — no re-judging on the later
    turn, no second count."""
    from coworker.providers import AssistantTurn, ModelCapabilities, ProviderClient
    from coworker.server.manager import SessionManager

    class FailsOnceProvider(ProviderClient):
        def __init__(self):
            self.calls = 0

        def complete(self, *, model, messages, tools=None, **settings):
            self.calls += 1
            if self.calls == 1:
                raise ValueError("the endpoint rejected the request")
            return AssistantTurn(text="Daily brief: all quiet.", finish_reason="stop")

        def capabilities(self, model):
            return ModelCapabilities()

    monkeypatch.setenv("COWORKER_STATE_DIR", str(tmp_path / "state"))
    ws = tmp_path / "ws"
    ws.mkdir()
    manager = SessionManager(data_dir=tmp_path / "data", provider=FailsOnceProvider())
    task = _task(workspace=str(ws), agent="cowork")
    manager.task_store.save(task)

    prep = manager.prepare_manual_run(task.id)
    engine = manager.get_engine(prep["session_id"], workspace=str(ws), agent="cowork")

    async def drain(events):
        async for _ in events:
            pass

    await asyncio.wait_for(drain(engine.run(prep["prompt"])), timeout=10)
    manager.save(prep["session_id"], engine)
    first = manager.finalize_manual_run(task.id, prep["run_id"])
    assert first["run"]["status"] == "error"

    # The user presses Retry on the error notice; this time the turn completes.
    await asyncio.wait_for(drain(engine.retry()), timeout=10)
    manager.save(prep["session_id"], engine)
    assert engine.messages[-1]["role"] == "assistant"

    again = manager.finalize_manual_run(task.id, prep["run_id"])
    assert again["run"]["status"] == "error"
    persisted = manager.task_store.runs(task.id)
    assert len(persisted) == 1 and persisted[0].status == "error"
    assert manager.task_store.get(task.id).run_count == 1
    assert manager.task_store.get(task.id).last_status == "error"


def test_every_interrupted_event_follows_an_interrupted_notice():
    """`_run_scheduled_task` takes its verdict from the transcript and keeps the
    INTERRUPTED event only as a second witness. That is sound because the engine appends
    an "interrupted" notice right before every INTERRUPTED event it yields, so a stopped
    turn is "canceled" in the transcript too. Pin that pairing: an INTERRUPTED yield
    without the notice would leave a manual run (which never sees the event) misjudged."""
    from pathlib import Path

    import coworker.engine as engine_mod

    lines = Path(engine_mod.__file__).read_text(encoding="utf-8").splitlines()
    sites = [i for i, line in enumerate(lines) if "Event(EventType.INTERRUPTED" in line]
    assert sites
    for index in sites:
        previous = next(line.strip() for line in reversed(lines[:index]) if line.strip())
        assert previous == 'self._append_notice("interrupted")', (index + 1, previous)


# -- REST ----------------------------------------------------------------------
def test_automations_rest(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from coworker.server.app import create_app
    from coworker.server.manager import SessionManager

    monkeypatch.setenv("COWORKER_STATE_DIR", str(tmp_path / "state"))
    manager = SessionManager(data_dir=tmp_path / "data")
    # seed a task directly via the store
    t = _task(workspace=str(tmp_path / "ws"))
    manager.task_store.save(t)
    client = TestClient(create_app(manager))

    tasks = client.get("/v1/automations").json()["tasks"]
    assert (
        tasks[0]["title"] == "Daily brief"
        and tasks[0]["schedule"] == "每天 ~19:10"
    )
    assert (
        client.patch(f"/v1/automations/{t.id}", json={"enabled": False}).json()["task"][
            "enabled"
        ]
        is False
    )
    assert client.get(f"/v1/automations/{t.id}").json()["task"]["id"] == t.id
    assert client.delete(f"/v1/automations/{t.id}").json()["ok"] is True


# -- unseen-run tracking (UX-023 sidebar badges) --------------------------------
def test_unseen_runs_counted_and_cleared_by_mark_seen(tmp_path, monkeypatch):
    """list_automations surfaces unseen counts (runs after the seen mark), with
    unseen_failed keyed to the NEWEST unseen run; mark_automation_seen clears them
    and later runs count fresh."""
    monkeypatch.setenv("COWORKER_STATE_DIR", str(tmp_path / "state"))
    from coworker.server.manager import SessionManager

    manager = SessionManager(data_dir=tmp_path / "data")
    t = manager.task_store.save(_task())
    manager.task_store.add_run(TaskRun(task_id=t.id, status="ok"))
    manager.task_store.add_run(TaskRun(task_id=t.id, status="error"))

    row = manager.list_automations()["tasks"][0]
    assert row["unseen_runs"] == 2
    assert row["unseen_failed"] is True  # newest unseen run errored

    assert manager.mark_automation_seen(t.id)["ok"]
    row = manager.list_automations()["tasks"][0]
    assert row["unseen_runs"] == 0 and row["unseen_failed"] is False

    time.sleep(0.01)  # a run strictly after the seen mark
    manager.task_store.add_run(TaskRun(task_id=t.id, status="ok"))
    row = manager.list_automations()["tasks"][0]
    assert row["unseen_runs"] == 1 and row["unseen_failed"] is False

    assert not manager.mark_automation_seen("task-nope")["ok"]


@pytest.mark.asyncio
async def test_scheduled_run_broadcasts_run_started_event(tmp_path, monkeypatch):
    """UX-026: the moment a scheduled run starts, every /ws/events socket hears
    automation_run_started (the top-right toast). Dead sockets drop silently."""
    from coworker.providers import AssistantTurn, ModelCapabilities, ProviderClient
    from coworker.server.manager import SessionManager

    class ScriptedProvider(ProviderClient):
        def complete(self, *, model, messages, tools=None, **settings):
            return AssistantTurn(text="done", finish_reason="stop")

        def capabilities(self, model):
            return ModelCapabilities()

    monkeypatch.setenv("COWORKER_STATE_DIR", str(tmp_path / "state"))
    ws = tmp_path / "ws"
    ws.mkdir()
    manager = SessionManager(data_dir=tmp_path / "data", provider=ScriptedProvider())
    task = _task(workspace=str(ws), agent="cowork")
    manager.task_store.save(task)

    heard: list = []

    async def listener(message):
        heard.append(message)

    async def dead(message):
        raise RuntimeError("socket gone")

    manager.register_event_client(listener)
    manager.register_event_client(dead)
    run = await manager._run_scheduled_task(task, trigger="schedule")

    (event,) = [m for m in heard if m["type"] == "automation_run_started"]
    assert event["data"]["task_id"] == task.id
    assert event["data"]["task_title"] == task.title
    assert event["data"]["session_id"] == run.session_id
    assert event["data"]["trigger"] == "schedule"
    assert dead not in manager._event_clients  # dropped, not fatal
