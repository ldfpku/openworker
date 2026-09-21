"""`SessionManager._generate_autotitle` must contain its own failures.

The title call runs as a fire-and-forget task (`_maybe_autotitle` → `spawn_retained`, which
never retrieves an exception). Its `try`/`finally` covered the completion call but not the
two statements before it — the `utility_model_for` import and the title-model pick — so a
raise there escaped the task unseen AND skipped the `finally` that clears the
`_autotitle_inflight` guard, after which `_maybe_autotitle` refuses that session forever:
it is never titled again for the life of the process.
"""

from __future__ import annotations

import asyncio
import logging

from coworker.providers import AssistantTurn, ModelCapabilities, ProviderClient
from coworker.server.manager import SessionManager

MANAGER_LOGGER = "coworker.manager"


class _TitleProvider(ProviderClient):
    def complete(self, *, model, messages, tools=None, **settings):
        return AssistantTurn(text="Trip Planning Help", finish_reason="stop")

    def capabilities(self, model):
        return ModelCapabilities()


async def test_title_model_pick_failure_is_contained_and_frees_the_guard(
    tmp_path, monkeypatch, caplog
):
    mgr = SessionManager(
        workspace=tmp_path, provider=_TitleProvider(), model="gpt-5.6-sol"
    )
    sid = "autotitle-escape"
    engine = mgr.get_engine(sid, agent="chat")
    engine.messages.append({"role": "user", "content": "help me plan a trip"})
    mgr.save(sid, engine)

    def boom(model):
        raise RuntimeError("utility-model-boom")

    monkeypatch.setattr("coworker.providers.matrix.utility_model_for", boom)
    caplog.set_level(logging.INFO, logger=MANAGER_LOGGER)

    mgr._maybe_autotitle(sid)
    assert len(mgr._autotitle_tasks) == 1
    (task,) = mgr._autotitle_tasks
    await asyncio.wait({task}, timeout=5)

    assert task.done()
    assert task.exception() is None, "the failure escaped into a task nobody awaits"
    assert sid not in mgr._autotitle_inflight, "the in-flight guard was stranded"
    logged = [
        r
        for r in caplog.records
        if r.name == MANAGER_LOGGER and r.levelno >= logging.WARNING and r.exc_info
    ]
    assert logged, "the failure must be logged with its traceback"
