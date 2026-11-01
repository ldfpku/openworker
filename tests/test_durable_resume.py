"""Durable resume: a prompt pending when the process 'restarts' is answered later and the turn
continues — rebuilt from the persisted thread, with no live await."""

import asyncio

from coworker.providers import (
    AssistantTurn,
    ModelCapabilities,
    ProviderClient,
    ToolCall,
)
from coworker.providers.base import SYSTEM_CONTEXT_OPEN
from coworker.server.manager import SessionManager
from coworker.testing.autotitle import autotitle_reply, is_autotitle_call


class ScriptedProvider(ProviderClient):
    def __init__(self, turns):
        self._turns = list(turns)

    def complete(self, *, model, messages, tools=None, **settings):
        # `_durable_resume`'s `mark_idle` (manager.py) fires with a freshly rebuilt
        # engine in place, so `_maybe_autotitle` CAN reach this same provider once
        # `engine.resume()` has drained `_turns` — an empty-queue `pop(0)` there is
        # swallowed by `_generate_autotitle`'s own try/except, but guard it anyway so it
        # can never eat a turn this file's scripts still need.
        if is_autotitle_call(messages):
            return autotitle_reply()
        return self._turns.pop(0)

    def capabilities(self, model):
        return ModelCapabilities()


def _tool(name, args, call_id):
    return AssistantTurn(tool_calls=[ToolCall(id=call_id, name=name, arguments=args)])


def _text(text):
    return AssistantTurn(text=text, finish_reason="stop")


async def _run_until_pending(mgr, sid, engine):
    async def first():
        async for _ in engine.run("go"):
            pass

    task = asyncio.create_task(first())
    pend = []
    for _ in range(100):
        await asyncio.sleep(0.02)
        pend = mgr.inbox.pending(sid)
        if pend:
            break
    assert pend, "prompt never became a pending Inbox item"
    # simulate a restart: cancel the suspended turn + drop the live engine
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    mgr._engines.pop(sid, None)
    mgr.mark_idle(sid)
    return pend[0]


def _final_assistant_texts(mgr, sid):
    rec = mgr.session_store.load(sid)
    return [
        m.get("content")
        for m in rec.messages
        if m.get("role") == "assistant" and m.get("content")
    ]


def test_durable_resume_question(tmp_path):
    mgr = SessionManager(
        workspace=tmp_path,
        provider=ScriptedProvider(
            [
                _tool(
                    "ask_user",
                    {
                        "question": "Which region?",
                        "options": ["us-east-1", "us-west-2"],
                    },
                    "call_q",
                ),
                _text("You chose us-west-2."),
            ]
        ),
    )
    sid = "dur-q"

    async def scenario():
        engine = mgr.get_engine(sid, agent="cowork", workspace=str(tmp_path))
        item = await _run_until_pending(mgr, sid, engine)
        assert item.kind == "question" and item.tool_call_id == "call_q"
        await mgr.resolve_inbox(item.id, "us-west-2")  # restart-style resume

    asyncio.run(scenario())
    assert any("us-west-2" in (t or "") for t in _final_assistant_texts(mgr, sid))
    assert mgr.inbox.pending(sid) == []  # nothing left pending


def test_resume_payload_keeps_the_suspended_tool_call(tmp_path):
    # `_outbound_messages` drops a TRAILING assistant turn (the partial a mid-stream death
    # leaves behind). A suspended turn is also stored ending on an assistant turn, so this
    # pins that resume is unaffected: the pending calls are answered first, making the tail a
    # `tool` message, and the assistant turn that made the call still reaches the model.
    class Recording(ScriptedProvider):
        def __init__(self, turns):
            super().__init__(turns)
            self.payloads = []

        def complete(self, *, model, messages, tools=None, **settings):
            self.payloads.append(messages)
            return super().complete(
                model=model, messages=messages, tools=tools, **settings
            )

    provider = Recording(
        [
            _tool("ask_user", {"question": "Which region?", "options": ["a", "b"]}, "call_q"),
            _text("You chose b."),
        ]
    )
    mgr = SessionManager(workspace=tmp_path, provider=provider)
    sid = "dur-payload"

    async def scenario():
        engine = mgr.get_engine(sid, agent="cowork", workspace=str(tmp_path))
        item = await _run_until_pending(mgr, sid, engine)
        await mgr.resolve_inbox(item.id, "b")

    asyncio.run(scenario())

    resumed = next(
        p for p in provider.payloads if any(m.get("role") == "tool" for m in p)
    )
    # This fork appends the ephemeral `<system-context>` block as its own trailing user
    # message; look at the conversation before it.
    if resumed and str(resumed[-1].get("content") or "").startswith(SYSTEM_CONTEXT_OPEN):
        resumed = resumed[:-1]
    assert [m.get("role") for m in resumed][-2:] == ["assistant", "tool"]
    assert any(
        m.get("role") == "assistant" and m.get("tool_calls") for m in resumed
    ), "the assistant turn that made the call must still reach the model"


def test_durable_resume_approval_executes_tool(tmp_path):
    # The model wants a write (needs approval); on durable resume "allow" must RE-EXECUTE the tool.
    target = tmp_path / "scratch_marker.txt"
    mgr = SessionManager(
        workspace=tmp_path,
        provider=ScriptedProvider(
            [
                _tool("write_file", {"path": str(target), "content": "ok"}, "call_w"),
                _text("Done — file written."),
            ]
        ),
    )
    sid = "dur-a"

    async def scenario():
        engine = mgr.get_engine(sid, agent="cowork", workspace=str(tmp_path))
        item = await _run_until_pending(mgr, sid, engine)
        assert item.kind == "approval" and item.tool_call_id == "call_w"
        assert not target.exists()  # not executed before approval
        await mgr.resolve_inbox(
            item.id, "allow"
        )  # restart-style resume → re-execute the tool

    asyncio.run(scenario())
    assert (
        target.exists() and target.read_text() == "ok"
    )  # the approved write actually ran
    assert any("Done" in (t or "") for t in _final_assistant_texts(mgr, sid))


def test_durable_resume_broadcasts_turn_lifecycle(tmp_path):
    """Regression: `_durable_resume_turn` used to discard every `engine.resume()` event
    (`async for _event ...: pass`) and never broadcast `turn_done`. A socket viewing the
    session therefore never saw the resume's `turn_start` — its `running` stayed false and
    the composer looked idle over a turn the server was actually running, so a plain
    message hit `claim_turn` and was rejected with "already running a turn" (owner report).

    A resume must now stream its events to every registered session client and emit a
    trailing `turn_done`, exactly like a foreground `run_turn` or a background
    `deliver_to_session` turn."""
    mgr = SessionManager(
        workspace=tmp_path,
        provider=ScriptedProvider(
            [
                _tool(
                    "ask_user",
                    {"question": "Which region?", "options": ["us-east-1", "us-west-2"]},
                    "call_q",
                ),
                _text("You chose us-west-2."),
            ]
        ),
    )
    sid = "dur-broadcast"
    seen: list[str] = []

    async def collect(message):
        seen.append(message.get("type"))

    async def scenario():
        engine = mgr.get_engine(sid, agent="cowork", workspace=str(tmp_path))
        item = await _run_until_pending(mgr, sid, engine)
        # Register the viewer AFTER the suspend/restart, the way a reconnecting GUI socket
        # attaches before the answer comes in.
        mgr.register_session_client(sid, collect)
        await mgr.resolve_inbox(item.id, "us-west-2")

    asyncio.run(scenario())

    assert "turn_start" in seen, (
        "the resume's turn_start must reach the viewer so the GUI marks the session running"
    )
    assert "turn_done" in seen, (
        "the resume must emit a trailing turn_done so the GUI clears running"
    )
    # Order: the session must look running before it looks idle.
    assert seen.index("turn_start") < seen.index("turn_done")


def test_durable_resume_survives_mark_idle_failure(tmp_path, monkeypatch):
    """`_durable_resume_turn`'s `finally` contains a `mark_idle` failure (logged, not
    raised) so a resume that already ran and was saved is not reported as a failure. Adding
    the `turn_done` broadcast after it must keep that containment: the broadcast sits in its
    own contained step and the whole thing must not raise out of the resume."""
    mgr = SessionManager(
        workspace=tmp_path,
        provider=ScriptedProvider(
            [
                _tool(
                    "ask_user",
                    {"question": "Which region?", "options": ["a", "b"]},
                    "call_q",
                ),
                _text("You chose b."),
            ]
        ),
    )
    sid = "dur-markidle-boom"

    real_mark_idle = mgr.mark_idle

    def boom(session_id):
        if session_id == sid:
            raise RuntimeError("mark_idle boom")
        return real_mark_idle(session_id)

    async def scenario():
        engine = mgr.get_engine(sid, agent="cowork", workspace=str(tmp_path))
        item = await _run_until_pending(mgr, sid, engine)
        # Arm the failure only for the resume's own finally — `_run_until_pending` above
        # legitimately calls mark_idle during its restart simulation.
        monkeypatch.setattr(mgr, "mark_idle", boom)
        # Must NOT raise despite mark_idle blowing up in the finally.
        await mgr.resolve_inbox(item.id, "b")

    asyncio.run(scenario())
    # The resume's answer still landed and was persisted.
    assert any("b" in (t or "") for t in _final_assistant_texts(mgr, sid))
