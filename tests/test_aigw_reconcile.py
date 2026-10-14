"""Reconciling everything that REMEMBERS a company-gateway model against the server list.

`tests/test_aigw_gate.py` covers what the picker offers. This file covers the places a
model id is stored and used later without anyone looking at a picker: the compaction and
auto-title overrides, an automation's model, a team worker's staffing note, and — the big
one — a session's own model (loaded engines, re-targeting drafts, stored conversations).

One rule, asserted for each of them (`SessionManager._aigw_delisted`):

* only `aigw:` ids — another provider's id is never touched;
* only when the list is KNOWN — no successful pull ever means nothing is touched;
* only ids that are NOT on it — a listed id stays exactly as it was.

And one rule for sessions on top: a session moves to the current default model, at a turn
boundary — unless the default is itself gone, in which case nothing else is picked and the
session waits in the "choose a model" state until the person chooses.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from coworker.automation.models import Schedule, ScheduledTask
from coworker.providers import AssistantTurn, ModelCapabilities, ProviderClient
from coworker.server import SessionManager, create_app
from coworker.sessions import SessionRecord
from coworker.teams.registry import TeamRegistry, TeamWorker
from coworker.testing.autotitle import autotitle_reply, is_autotitle_call
from coworker.testing.guidance import diagnosis_reply, is_diagnosis_call

FABLE = "aigw:anthropic/claude-fable-5"
SONNET = "aigw:anthropic/claude-sonnet-5"
GPT_SOL = "aigw:openai/gpt-5.6-sol"
DIRECT = "anthropic:claude-fable-5"  # the same lab reached with the person's own key
DEFAULT = "gpt-5.6-sol"


class _Provider(ProviderClient):
    """Answers every chat turn with "ok" and records which model each one went out on."""

    def __init__(self) -> None:
        self.models: list[str] = []

    def complete(self, *, model, messages, tools=None, **settings):
        if is_autotitle_call(messages):
            return autotitle_reply()
        if is_diagnosis_call(messages):  # 开工前核对, same divert as the title call
            return diagnosis_reply()
        self.models.append(model)
        return AssistantTurn(text="ok", finish_reason="stop")

    def capabilities(self, model):
        return ModelCapabilities()


def _rows(*ids: str) -> list[dict]:
    return [{"id": i[len("aigw:") :], "label": i, "context_window": None} for i in ids]


def _mgr(tmp_path, *listed: str, default: str = DEFAULT) -> SessionManager:
    """A manager whose gateway list is `listed` (routed `aigw:` ids), as if a pull had
    already succeeded. No `listed` → no pull has ever succeeded (the list is unknown)."""
    mgr = SessionManager(workspace=tmp_path, provider=_Provider(), model=default)
    if listed:
        _pull(mgr, *listed)
    return mgr


def _pull(mgr: SessionManager, *listed: str) -> None:
    """A successful `/gate/models` pull landing — the choke point every refresh path
    ends in (server start, TTL refresh, Refresh, Test, sign-in)."""
    mgr._store_model_catalog("aigw", {"ok": True, "models": _rows(*listed)})


async def _turn(mgr: SessionManager, sid: str, text: str = "hello") -> None:
    engine = mgr.get_engine(sid, agent="chat")
    mgr.mark_running(sid)
    async for _ in engine.run(text):
        pass
    mgr.save(sid, engine)
    mgr.mark_idle(sid)


async def _session_on(mgr: SessionManager, sid: str, model: str, *, turns: int = 1):
    """A loaded session hand-picked onto `model`, with `turns` finished turns of history."""
    engine = mgr.get_engine(sid, agent="chat")
    engine.switch_model(model)
    engine.model_pinned = True
    for _ in range(turns):
        await _turn(mgr, sid)
    return engine


def _switch_notices(engine) -> list[str]:
    return [m["text"] for m in engine.messages if m.get("kind") == "model_switch"]


# -- the predicate everything goes through -------------------------------------------------
def test_delisted_means_a_gateway_id_missing_from_a_known_list(tmp_path):
    mgr = _mgr(tmp_path, SONNET)
    assert mgr._aigw_delisted(FABLE) is True
    assert mgr._aigw_delisted(SONNET) is False  # listed
    assert mgr._aigw_delisted(DIRECT) is False  # not the gateway's business
    assert mgr._aigw_delisted("gpt-5.6-sol") is False
    assert mgr._aigw_delisted("") is False and mgr._aigw_delisted(None) is False
    # Unknown list: nothing is "de-listed", however dead it may turn out to be.
    assert _mgr(tmp_path / "b")._aigw_delisted(FABLE) is False


# -- 1. prefs: the compaction / auto-title overrides -----------------------------------------
def test_delisted_override_models_go_back_to_auto(tmp_path):
    mgr = _mgr(tmp_path, FABLE, SONNET, GPT_SOL)
    mgr.set_compaction_settings(model=FABLE)
    mgr._prefs["autotitle_model"] = GPT_SOL
    _pull(mgr, FABLE, SONNET, GPT_SOL)  # still listed → untouched
    assert mgr._prefs["compaction_model"] == FABLE
    assert mgr._prefs["autotitle_model"] == GPT_SOL

    _pull(mgr, SONNET)
    # "" is the value both readers already treat as "no override".
    assert mgr._prefs["compaction_model"] == ""
    assert mgr._prefs["autotitle_model"] == ""
    assert mgr.compaction_settings()["model"] == ""
    assert mgr.get_settings()["compaction_model"] == ""
    # Written with the list, not only in memory.
    reborn = SessionManager(workspace=tmp_path, provider=_Provider())
    assert reborn._prefs["compaction_model"] == "" and reborn._prefs["autotitle_model"] == ""


@pytest.mark.parametrize("kept", [SONNET, DIRECT, "gpt-4o-mini", ""])
def test_listed_and_non_gateway_overrides_are_left_alone(tmp_path, kept):
    mgr = _mgr(tmp_path, FABLE, SONNET)
    mgr._prefs["compaction_model"] = kept
    mgr._prefs["autotitle_model"] = kept
    _pull(mgr, SONNET)
    assert mgr._prefs["compaction_model"] == kept
    assert mgr._prefs["autotitle_model"] == kept


def test_overrides_are_untouched_while_the_list_is_unknown(tmp_path):
    mgr = _mgr(tmp_path)  # no successful pull ever
    mgr._prefs["compaction_model"] = FABLE
    mgr._prefs["autotitle_model"] = FABLE
    assert mgr._reconcile_aigw_selections() is False
    # A FAILED pull is not a list either.
    mgr._store_model_catalog("aigw", {"ok": False, "error": "offline"})
    assert mgr._prefs["compaction_model"] == FABLE
    assert mgr._prefs["autotitle_model"] == FABLE


async def test_a_reset_autotitle_override_falls_back_to_the_auto_pick(tmp_path):
    mgr = _mgr(tmp_path, FABLE, SONNET)
    mgr._prefs["autotitle_model"] = FABLE
    _pull(mgr, SONNET)
    # Auto = `_utility_model(session model)`; the dead override is no longer consulted.
    title_model = str(mgr._prefs.get("autotitle_model") or "") or mgr._utility_model(DEFAULT)
    assert title_model == "gpt-5.6-luna"


# -- 2. automations --------------------------------------------------------------------------
def _task(mgr: SessionManager, tmp_path, model) -> ScheduledTask:
    return mgr.task_store.save(
        ScheduledTask(
            title="daily",
            instructions="do the thing",
            schedule=Schedule(kind="cron", cron="0 9 * * *"),
            workspace=str(tmp_path),
            model=model,
        )
    )


def test_a_delisted_automation_model_is_cleared_so_it_follows_the_default(tmp_path):
    mgr = _mgr(tmp_path, FABLE, SONNET)
    dead, listed = _task(mgr, tmp_path, FABLE), _task(mgr, tmp_path, SONNET)
    direct, unset = _task(mgr, tmp_path, DIRECT), _task(mgr, tmp_path, None)
    _pull(mgr, SONNET)

    assert mgr.task_store.get(dead.id).model is None
    assert mgr.task_store.get(listed.id).model == SONNET
    assert mgr.task_store.get(direct.id).model == DIRECT
    assert mgr.task_store.get(unset.id).model is None
    # What "cleared" buys: the next run is built on the default model.
    engine = mgr._build_task_engine(mgr.task_store.get(dead.id), session_id="__run__r1")
    assert engine.model == DEFAULT
    assert mgr._build_task_engine(
        mgr.task_store.get(listed.id), session_id="__run__r2"
    ).model == SONNET
    # Even a task object read BEFORE the pull (the scheduler holding a due list) does not
    # get to run on the id it still carries in memory.
    assert dead.model == FABLE
    assert mgr._build_task_engine(dead, session_id="__run__r3").model == DEFAULT


def test_clearing_an_automation_model_never_reschedules_it(tmp_path):
    # A task that is DUE but not yet picked up by the scheduler tick: `TaskStore.save`
    # would recompute `next_run` from now and the pending fire would be gone.
    mgr = _mgr(tmp_path, FABLE, SONNET)
    task = _task(mgr, tmp_path, FABLE)
    mgr.task_store._conn.execute(
        "UPDATE scheduled_tasks SET next_run=? WHERE id=?", (1.0, task.id)
    )
    mgr.task_store._conn.commit()
    assert [t.id for t in mgr.task_store.due()] == [task.id]

    _pull(mgr, SONNET)
    due = mgr.task_store.due()
    assert [t.id for t in due] == [task.id]  # still due
    assert due[0].model is None  # …and already off the dead model
    assert due[0].schedule.cron == "0 9 * * *" and due[0].enabled is True


def test_automations_are_untouched_while_the_list_is_unknown(tmp_path):
    mgr = _mgr(tmp_path)
    task = _task(mgr, tmp_path, FABLE)
    assert mgr._reconcile_aigw_stores() is False
    mgr._store_model_catalog("aigw", {"ok": False, "error": "offline"})
    assert mgr.task_store.get(task.id).model == FABLE


# -- 3. the team roster's staffing note ------------------------------------------------------
def _team(mgr: SessionManager, *models: str):
    return mgr.teams.create(
        space="space-1",
        lead_session="lead-1",
        lead_actor="cowork:lead-1",
        workers=[
            TeamWorker(actor=f"w{i}", persona="cowork", session_id=f"ws{i}", model=m)
            for i, m in enumerate(models)
        ],
    )


def test_a_delisted_team_worker_model_note_is_cleared(tmp_path):
    mgr = _mgr(tmp_path, FABLE, SONNET)
    team = _team(mgr, FABLE, SONNET, DIRECT, "")
    _pull(mgr, SONNET)
    assert [w.model for w in mgr.teams.get(team.team_id).workers] == ["", SONNET, DIRECT, ""]
    # Persisted to teams.json, not only in memory.
    reread = TeamRegistry(mgr.teams.path).get(team.team_id)
    assert [w.model for w in reread.workers] == ["", SONNET, DIRECT, ""]
    # The rest of the roster is as it was.
    assert [w.actor for w in reread.workers] == ["w0", "w1", "w2", "w3"]


def test_the_team_roster_is_untouched_while_the_list_is_unknown(tmp_path):
    mgr = _mgr(tmp_path)
    team = _team(mgr, FABLE)
    mgr._store_model_catalog("aigw", {"ok": False, "error": "offline"})
    assert mgr.teams.get(team.team_id).workers[0].model == FABLE


def test_a_new_worker_is_never_staffed_on_a_delisted_model(tmp_path):
    # `create_team` resolves a member's model through the same target function a session
    # uses; the resolution itself is what matters here.
    mgr = _mgr(tmp_path, SONNET)
    assert (mgr._session_model_target(FABLE) or FABLE) == DEFAULT
    assert (mgr._session_model_target(SONNET) or SONNET) == SONNET
    assert (mgr._session_model_target(DIRECT) or DIRECT) == DIRECT


# -- 4. sessions: loaded and idle --------------------------------------------------------------
async def test_an_idle_session_on_a_delisted_model_moves_to_the_default(tmp_path):
    mgr = _mgr(tmp_path, FABLE, SONNET)
    engine = await _session_on(mgr, "s1", FABLE)
    assert mgr.session_store.load("s1").model == FABLE

    _pull(mgr, SONNET)
    assert engine.model == DEFAULT
    assert engine.model_pinned is False  # the pick it protected no longer exists
    # The transcript marks where it happened, with the ordinary switch marker…
    assert _switch_notices(engine)[-1].startswith("Model switched to GPT-5.6 Sol")
    # …and the stored row no longer names the dead id.
    record = mgr.session_store.load("s1")
    assert record.model == DEFAULT
    assert record.messages[-1].get("kind") == "model_switch"
    # The next turn really goes out on the default.
    await _turn(mgr, "s1")
    assert mgr.provider.models[-1] == DEFAULT


async def test_listed_and_non_gateway_sessions_are_left_alone(tmp_path):
    mgr = _mgr(tmp_path, FABLE, SONNET)
    listed = await _session_on(mgr, "listed", SONNET)
    direct = await _session_on(mgr, "direct", DIRECT)
    _pull(mgr, SONNET)
    assert listed.model == SONNET and listed.model_pinned is True
    assert direct.model == DIRECT and direct.model_pinned is True
    assert _switch_notices(listed) == _switch_notices(direct) == []  # nothing was switched


async def test_sessions_are_untouched_while_the_list_is_unknown(tmp_path):
    mgr = _mgr(tmp_path)
    engine = await _session_on(mgr, "s1", FABLE)
    assert mgr._reconcile_live_sessions() == []
    mgr._store_model_catalog("aigw", {"ok": False, "error": "offline"})
    assert engine.model == FABLE and engine.model_pinned is True


async def test_a_draft_on_a_delisted_model_moves_silently_and_earns_no_row(tmp_path):
    mgr = _mgr(tmp_path, FABLE, SONNET)
    engine = await _session_on(mgr, "draft1", FABLE, turns=0)
    _pull(mgr, SONNET)
    assert engine.model == DEFAULT
    # A setting, not history: no marker in a conversation that has not started, and no
    # Recents row conjured by the reconcile.
    assert "model_switch" not in [m.get("kind") for m in engine.messages]
    assert mgr.session_store.load("draft1") is None


async def test_viewers_are_told_about_a_switched_session(tmp_path):
    # With a running server the pass runs on the event loop and each switched session's
    # sockets get the same `model_changed` echo a hand switch sends — the GUI's existing
    # handler updates the composer and appends the marker; nothing new on the client.
    mgr = _mgr(tmp_path, FABLE, SONNET)
    engine = await _session_on(mgr, "s1", FABLE)
    mgr._loop = asyncio.get_running_loop()
    seen: list[dict] = []
    app_events: list[dict] = []

    async def viewer(message: dict) -> None:
        seen.append(message)

    async def app_client(message: dict) -> None:
        app_events.append(message)

    mgr.register_session_client("s1", viewer)
    mgr.register_event_client(app_client)
    await asyncio.to_thread(_pull, mgr, SONNET)  # off the loop, like a real pull
    await asyncio.sleep(0.05)

    assert engine.model == DEFAULT
    changed = [m for m in seen if m["type"] == "model_changed"]
    assert len(changed) == 1
    assert changed[0]["data"]["model"] == DEFAULT
    assert changed[0]["data"]["text"].startswith("Model switched to")
    # The app-wide push still goes out, so every window re-reads its settings.
    assert {"type": "models_changed"} in app_events


# -- 4. sessions: mid-turn → next turn boundary ------------------------------------------------
async def test_a_running_session_is_switched_at_its_next_turn_boundary(tmp_path):
    mgr = _mgr(tmp_path, FABLE, SONNET)
    engine = await _session_on(mgr, "s1", FABLE)
    mgr.mark_running("s1")  # a turn is in flight
    _pull(mgr, SONNET)
    assert engine.model == FABLE  # never swapped under a turn
    assert mgr.session_store.load("s1").model == FABLE

    mgr.mark_idle("s1")  # the turn ended
    assert engine.model == DEFAULT
    assert mgr.session_store.load("s1").model == DEFAULT
    assert _switch_notices(engine)[-1].startswith("Model switched to")


# -- 4. sessions: re-targeting drafts ------------------------------------------------------------
def test_a_carried_draft_pick_on_a_delisted_model_follows_the_default(tmp_path):
    mgr = _mgr(tmp_path, FABLE, SONNET)
    carry = lambda model: {  # noqa: E731
        "model": model, "model_pinned": True, "mode": mgr.mode, "messages": [], "extra_roots": []
    }
    mgr._draft_carry.update(dead=carry(FABLE), listed=carry(SONNET), direct=carry(DIRECT))
    _pull(mgr, SONNET)
    assert mgr._draft_carry["dead"]["model"] == DEFAULT
    assert "model_pinned" not in mgr._draft_carry["dead"]
    assert mgr._draft_carry["listed"] == carry(SONNET)
    assert mgr._draft_carry["direct"] == carry(DIRECT)


# -- 4. sessions: stored, not loaded → lazily, when next built -----------------------------------
def _stored(mgr: SessionManager, tmp_path, sid: str, model: str) -> None:
    mgr.session_store.save(
        SessionRecord(
            session_id=sid,
            workspace=str(tmp_path),
            model=model,
            mode="interactive",
            # Shaped like a record a real engine saved: the system prompt leads.
            messages=[
                {"role": "system", "content": "you are a helpful coworker"},
                {"role": "user", "content": "an old question"},
                {"role": "assistant", "content": "an old answer"},
            ],
            agent="chat",
        )
    )


def test_a_stored_session_is_reconciled_when_it_is_next_opened_not_on_the_pull(tmp_path):
    mgr = _mgr(tmp_path, FABLE, SONNET)
    for sid, model in (("old-dead", FABLE), ("old-listed", SONNET), ("old-direct", DIRECT)):
        _stored(mgr, tmp_path, sid, model)

    _pull(mgr, SONNET)
    # The pull does not walk the conversation store: nothing unloaded is rewritten.
    assert mgr.session_store.load("old-dead").model == FABLE
    assert mgr._engines == {}

    # Opening it (a socket connect, a resume, a channel delivery — all `get_engine`).
    engine = mgr.get_engine("old-dead", agent="chat")
    assert engine.model == DEFAULT
    assert engine.messages[-1].get("kind") == "model_switch"
    record = mgr.session_store.load("old-dead")
    assert record.model == DEFAULT
    assert record.messages[-1].get("kind") == "model_switch"
    # Exactly one line was appended to the stored conversation — the marker.
    assert [m["role"] for m in record.messages] == ["system", "user", "assistant", "notice"]

    assert mgr.get_engine("old-listed", agent="chat").model == SONNET
    assert mgr.get_engine("old-direct", agent="chat").model == DIRECT
    assert mgr.session_store.load("old-listed").messages[-1]["role"] == "assistant"


def test_a_stored_session_opens_untouched_while_the_list_is_unknown(tmp_path):
    mgr = _mgr(tmp_path)
    _stored(mgr, tmp_path, "old", FABLE)
    assert mgr.get_engine("old", agent="chat").model == FABLE
    assert mgr.session_store.load("old").model == FABLE


# -- 4. sessions: the default is gone too → nothing else is picked -------------------------------
async def test_with_a_dead_default_sessions_are_not_silently_moved_anywhere(
    tmp_path, monkeypatch
):
    mgr = _mgr(tmp_path, FABLE, SONNET, GPT_SOL, default=FABLE)
    # Signed in to the gateway (merged, so the generation stamp survives), which makes
    # `model_ready` below a statement about the LIST rather than about a missing sign-in.
    monkeypatch.delenv("CLOUDFLARE_AIGW_BASE_URL", raising=False)
    profile = dict(mgr.secrets.get("provider:aigw") or {})
    mgr.secrets.put("provider:aigw", {**profile, "access_token": "jwt"})
    assert mgr.get_settings()["model_ready"] is True
    on_other = await _session_on(mgr, "other", GPT_SOL)  # a different gateway model
    on_default = await _session_on(mgr, "dflt", FABLE)  # the default itself
    _stored(mgr, tmp_path, "old", GPT_SOL)

    _pull(mgr, SONNET)  # the default AND the other model both left the list
    settings = mgr.get_settings()
    assert settings["model_ready"] is False
    assert settings["model_notice"] == "default_model_gone"
    assert mgr.model == FABLE  # the default is reported, not replaced…
    # …and no session was handed some third model in its place.
    assert on_other.model == GPT_SOL and on_default.model == FABLE
    assert mgr.get_engine("old", agent="chat").model == GPT_SOL
    assert mgr.session_store.load("old").model == GPT_SOL
    # Neither dead id is offered: the composer is in its "choose a model" state.
    assert FABLE not in settings["models"] and GPT_SOL not in settings["models"]
    # A stale client cannot re-assert either of them.
    assert mgr.model_pick_allowed(FABLE) is False and mgr.model_pick_allowed(GPT_SOL) is False

    # The person chooses: every stranded session now has somewhere to go.
    picked = mgr.set_default_model(SONNET)
    assert picked["model_ready"] is True and picked["model_notice"] is None
    assert SONNET in picked["models"]
    assert on_other.model == SONNET and on_default.model == SONNET
    assert mgr._engines["old"].model == SONNET
    assert mgr.session_store.load("other").model == SONNET
    assert mgr.session_store.load("old").model == SONNET


# -- the socket: a stale composer cannot re-pin a de-listed model --------------------------------
def _drain(ws) -> list[str]:
    types = []
    while True:
        event = ws.receive_json()
        types.append(event["type"])
        if event["type"] == "turn_done":
            return types


def test_the_socket_refuses_a_pick_of_a_delisted_model_and_echoes_the_truth(tmp_path):
    mgr = _mgr(tmp_path, SONNET)
    client = TestClient(create_app(mgr))
    with client.websocket_connect("/ws/session/stale1?agent=chat") as ws:
        assert ws.receive_json()["data"]["model"] == DEFAULT
        ws.send_json({"type": "set_model", "model": FABLE})
        echo = ws.receive_json()
        assert echo == {"type": "model_changed", "data": {"model": DEFAULT}}
        engine = mgr._engines["stale1"]
        assert engine.model == DEFAULT
        assert not getattr(engine, "model_pinned", False)  # refused before it pinned
        # The composer re-sends its visible model with every message: the stale id
        # must not ride in on a send either — the turn goes out on the real model.
        ws.send_json({"type": "user_message", "text": "hi", "model": FABLE})
        _drain(ws)
        assert mgr.provider.models == [DEFAULT]
        # A listed gateway model and a direct one are ordinary picks.
        ws.send_json({"type": "set_model", "model": SONNET})
        assert ws.receive_json()["data"]["model"] == SONNET
        ws.send_json({"type": "set_model", "model": DIRECT})
        assert ws.receive_json()["data"]["model"] == DIRECT
    assert mgr._engines["stale1"].model == DIRECT


def test_the_socket_takes_any_pick_while_the_list_is_unknown(tmp_path):
    mgr = _mgr(tmp_path)
    client = TestClient(create_app(mgr))
    with client.websocket_connect("/ws/session/nolist?agent=chat") as ws:
        ws.receive_json()
        ws.send_json({"type": "set_model", "model": FABLE})
        assert ws.receive_json() == {"type": "model_changed", "data": {"model": FABLE}}
    assert mgr._engines["nolist"].model == FABLE
