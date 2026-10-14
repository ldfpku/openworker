"""开工前核对 — the engine round-trip (coworker/engine.py `_preflight`), the manager wiring,
and the WebSocket surface. Scripted providers, no network."""

import asyncio
import json

from fastapi.testclient import TestClient

from coworker.engine import PREFLIGHT_ID_PREFIX, TurnEngine
from coworker.events import EventType
from coworker.permissions import PermissionEngine
from coworker.providers import AssistantTurn, ModelCapabilities, ProviderClient
from coworker.server import SessionManager, create_app
from coworker.testing.autotitle import autotitle_reply, is_autotitle_call
from coworker.testing.guidance import diagnosis_reply, is_diagnosis_call
from coworker.tools import ToolRegistry
from coworker.tools.ask import PREFLIGHT_SKIP, answer_result, question_item_fields

from test_compaction_engine import CompactingProvider, long_history

WEAK = {
    "is_task": True,
    "task_kind": "数据整理汇总",
    "domain": "质量管理",
    "scores": {"deliverable": 1, "audience": 0, "sources": 2, "rules": 2},
    "known": {"sources": "文件夹里的检验记录"},
    "options": {
        "deliverable": [{"label": "Word 周报", "description": "沿用上周格式"}],
        "audience": [{"label": "生产部长"}],
    },
    "matched_skills": ["quality-weekly-report"],
    "matched_experts": ["quality-system"],
}
CLEAR = {**WEAK, "scores": {"deliverable": 2, "audience": 2, "sources": 2, "rules": 2}}
GREETING = {"is_task": False}
CANDS = {
    "skills": [
        {"id": "quality-weekly-report", "name": "quality-weekly-report", "installed": True,
         "category_name": "质量管理", "description": "质量周报", "score": 1.0},
        {"id": "ncr-8d-report", "name": "ncr-8d-report", "installed": False,
         "category_name": "质量管理", "description": "8D", "score": 0.5},
    ],
    "experts": [{"id": "quality-system", "name": "质量体系", "kind": "persona", "description": "", "score": 0.4}],
}
ANSWERS = json.dumps({"要什么": "Word 周报", "给谁看": "生产部长", "技能": "quality-weekly-report"})


class GuidanceProvider(ProviderClient):
    """Scripted main turns; diagnosis calls (recognized by DIAGNOSIS_MARKER) answered
    out-of-band so they never consume the main script."""

    def __init__(self, turns, *, diagnosis=None, fail=False):
        self._turns = list(turns)
        self.diagnosis = diagnosis
        self.fail = fail
        self.diagnosis_calls = []
        self.main_calls = []

    def complete(self, *, model, messages, tools=None, **settings):
        if is_autotitle_call(messages):
            return autotitle_reply()
        if is_diagnosis_call(messages):
            self.diagnosis_calls.append({"model": model, "messages": messages, **settings})
            if self.fail:
                raise RuntimeError("diagnosis down")
            return diagnosis_reply(self.diagnosis)
        self.main_calls.append(messages)
        return self._turns.pop(0)

    def capabilities(self, model):
        return ModelCapabilities()


class Asker:
    """A question_asker double in the server's shape: records (args, id), answers from
    the scripted resolution through the real answer_result()."""

    def __init__(self, resolution=ANSWERS):
        self.resolution = resolution
        self.calls = []

    async def __call__(self, args, tool_call_id=None):
        self.calls.append((args, tool_call_id))
        fields = question_item_fields(
            args, preflight=str(tool_call_id or "").startswith(PREFLIGHT_ID_PREFIX)
        )
        self.last_fields = fields
        return answer_result(fields["questions"], self.resolution)


def make_engine(tmp_path, provider, *, asker=None, attended=True, enabled=True,
                candidates=CANDS, installed=("quality-weekly-report",), messages=None):
    engine = TurnEngine(
        provider=provider,
        registry=ToolRegistry(),
        permissions=PermissionEngine(workspace_root=tmp_path),
        model="gpt-5.5",
        question_asker=asker,
        messages=messages,
    )
    engine.is_attended = None if attended is None else (lambda: attended)
    engine.guidance_config = lambda: {
        "enabled": enabled,
        "model": "cheap-model",
        "timeout": 5,
        "recommend": lambda text: candidates,
        "installed_skills": set(installed),
    }
    engine.guidance_context = lambda: {
        "memories": "Known memories:\n- 周报给生产部长",
        "rules": "",
        "roots": [str(tmp_path)],
        "skills_catalog": "Available skills — …\n- quality-weekly-report: 质量周报",
    }
    return engine


def collect(engine, text="帮我做个质量周报", **kw):
    async def _run():
        return [e async for e in engine.run(text, **kw)]

    return asyncio.run(_run())


def text_turn(t="开工"):
    return AssistantTurn(text=t, finish_reason="stop")


# -- the round trip ---------------------------------------------------------------


def test_round_trip_persists_a_synthetic_ask_user_and_the_brief(tmp_path):
    provider = GuidanceProvider([text_turn()], diagnosis=WEAK)
    asker = Asker()
    engine = make_engine(tmp_path, provider, asker=asker)
    events = collect(engine)

    types = [e.type for e in events]
    assert EventType.PREFLIGHT in types
    assert any(e.type == EventType.TOOL_PROPOSED and e.data["name"] == "ask_user" for e in events)
    assert any(e.type == EventType.TOOL_FINISHED and e.data["status"] == "ok" for e in events)
    assert not any(e.type == EventType.ERROR for e in events)

    # the diagnosis went to the cheap model with the context the manager supplies
    call = provider.diagnosis_calls[0]
    assert call["model"] == "cheap-model"
    user_section = call["messages"][1]["content"]
    assert "生产部长" in user_section and "quality-weekly-report" in user_section

    # the card: worst dimension first, recommended defaults, the installed skill, marked preflight
    args, call_id = asker.calls[0]
    assert call_id == "preflight:1"
    assert [q["header"] for q in args["questions"]] == ["给谁看", "要什么", "技能"]
    assert asker.last_fields["data"] == {"preflight": True}

    # history: user (sidecar) → synthetic assistant tool_call → tool result with the brief
    user, assistant, tool = engine.messages[-4:-1]
    assert user["role"] == "user" and user["_preflight"] == {"state": "done"}
    assert assistant["role"] == "assistant" and assistant["tool_calls"][0]["id"] == "preflight:1"
    assert assistant["tool_calls"][0]["function"]["name"] == "ask_user"
    assert json.loads(assistant["tool_calls"][0]["function"]["arguments"])["preflight"] is True
    result = json.loads(tool["content"])
    assert result["answers"]["给谁看"] == "生产部长"
    assert "<task-brief>" in result["brief"] and 'load_skill("quality-weekly-report")' in result["brief"]
    assert "推荐专家：质量体系" in result["brief"]
    assert engine.messages[-1]["content"] == "开工"

    # the main model saw the brief as a USER message — never the synthetic tool call
    # (Anthropic rejects the id's colon, Gemini 3+ the missing thought_signature) — and
    # the sidecar never reaches a provider
    seen = provider.main_calls[0]
    assert not any(m.get("role") == "tool" for m in seen)
    assert not any(m.get("tool_calls") for m in seen if m.get("role") == "assistant")
    folded = [m for m in seen if m.get("role") == "user" and "<task-brief>" in str(m.get("content"))]
    assert len(folded) == 1 and "开工前核对" in folded[0]["content"]
    assert not any("_preflight" in m for m in seen)


def test_outbound_view_folds_the_preflight_exchange_only(tmp_path):
    provider = GuidanceProvider([text_turn()], diagnosis=WEAK)
    engine = make_engine(tmp_path, provider, asker=Asker())
    collect(engine)
    # a real (model-authored) tool exchange after the pre-flight stays a tool exchange
    engine.messages.append(
        {"role": "assistant", "content": "", "tool_calls": [{"id": "call_1", "type": "function",
         "function": {"name": "read_file", "arguments": "{}"}}]}
    )
    engine.messages.append({"role": "tool", "tool_call_id": "call_1", "content": "ok"})
    out = engine._outbound_messages()
    roles = [(m["role"], [c["id"] for c in m.get("tool_calls") or []]) for m in out]
    assert ("assistant", ["preflight:1"]) not in roles
    assert ("assistant", ["call_1"]) in roles
    assert [m for m in out if m.get("role") == "tool"] == [{"role": "tool", "tool_call_id": "call_1", "content": "ok"}]
    # canonical history is untouched
    assert any(m.get("role") == "tool" and m.get("tool_call_id") == "preflight:1" for m in engine.messages)


def test_skip_button_authorizes_defaults_and_counts_as_answered(tmp_path):
    provider = GuidanceProvider([text_turn()], diagnosis=WEAK)
    engine = make_engine(tmp_path, provider, asker=Asker(PREFLIGHT_SKIP))
    events = collect(engine)
    finished = [e for e in events if e.type == EventType.TOOL_FINISHED]
    assert finished and finished[0].data["status"] == "ok"
    result = json.loads([m for m in engine.messages if m.get("role") == "tool"][-1]["content"])
    assert result["skipped"] is True and "跳过" in result["brief"]


def test_clear_brief_with_recommendations_rides_the_system_context(tmp_path):
    provider = GuidanceProvider([text_turn()], diagnosis={**CLEAR, "matched_skills": ["ncr-8d-report"]})
    asker = Asker()
    engine = make_engine(tmp_path, provider, asker=asker, installed=())
    collect(engine)
    assert asker.calls == []  # nothing to ask
    user = [m for m in engine.messages if m.get("role") == "user"][0]
    assert user["_preflight"]["state"] == "done"
    assert "推荐但未安装的技能：ncr-8d-report" in user["_preflight"]["brief"]
    tail = provider.main_calls[0][-1]
    assert tail["role"] == "user" and "<system-context>" in tail["content"]
    assert "<task-brief>" in tail["content"]
    # the brief is gone once the next user message arrives
    provider._turns.append(text_turn("ok"))
    collect(engine, "改一下格式")
    assert "<task-brief>" not in str(provider.main_calls[1][-1].get("content"))


def test_one_installed_match_on_a_clear_brief_names_the_skill_without_a_card(tmp_path):
    provider = GuidanceProvider([text_turn()], diagnosis=CLEAR)
    asker = Asker()
    engine = make_engine(tmp_path, provider, asker=asker)
    collect(engine)
    assert asker.calls == []
    brief = [m for m in engine.messages if m.get("role") == "user"][0]["_preflight"]["brief"]
    assert 'load_skill("quality-weekly-report")' in brief


# -- skip paths ----------------------------------------------------------------------


def test_greeting_is_not_done_so_the_next_task_message_is_checked(tmp_path):
    provider = GuidanceProvider([text_turn("你好！"), text_turn()], diagnosis=GREETING)
    asker = Asker()
    engine = make_engine(tmp_path, provider, asker=asker)
    collect(engine, "你好")
    assert asker.calls == [] and engine.messages[-2]["_preflight"] == {"state": "not-task"}
    provider.diagnosis = WEAK
    collect(engine)
    assert len(provider.diagnosis_calls) == 2
    assert asker.calls and asker.calls[0][1] == "preflight:2"


def test_once_done_later_messages_are_not_checked_unless_forced(tmp_path):
    provider = GuidanceProvider([text_turn(), text_turn(), text_turn()], diagnosis=WEAK)
    asker = Asker()
    engine = make_engine(tmp_path, provider, asker=asker)
    collect(engine)
    collect(engine, "改一下格式")
    assert len(provider.diagnosis_calls) == 1 and len(asker.calls) == 1
    collect(engine, "再来一份交期风险排查", preflight=True)
    assert len(provider.diagnosis_calls) == 2 and asker.calls[-1][1] == "preflight:3"


def test_gates_skip_force_run_unattended_channel_and_disabled(tmp_path):
    def run(**kw):
        provider = GuidanceProvider([text_turn()], diagnosis=WEAK)
        asker = Asker()
        engine_kw = {k: kw.pop(k) for k in ("attended", "enabled") if k in kw}
        engine = make_engine(tmp_path, provider, asker=asker, **engine_kw)
        collect(engine, **kw)
        return provider, asker

    provider, asker = run(display="/quality-weekly-report 本周")
    assert provider.diagnosis_calls == [] and asker.calls == []
    provider, asker = run(attended=None)
    assert provider.diagnosis_calls == []
    provider, asker = run(attended=False)
    assert provider.diagnosis_calls == []
    provider, asker = run(source={"kind": "weixin"})
    assert provider.diagnosis_calls == []
    provider, asker = run(enabled=False)
    assert provider.diagnosis_calls == []
    provider, asker = run(preflight=False)
    assert provider.diagnosis_calls == []
    # forced beats the Settings switch
    provider, asker = run(enabled=False, preflight=True)
    assert len(provider.diagnosis_calls) == 1 and asker.calls


def test_after_three_user_messages_the_automatic_check_stops(tmp_path):
    provider = GuidanceProvider([text_turn()] * 4, diagnosis=GREETING)
    engine = make_engine(tmp_path, provider, asker=Asker())
    for text in ("你好", "在吗", "嗯", "帮我做个质量周报"):
        collect(engine, text)
    assert len(provider.diagnosis_calls) == 3


def test_diagnosis_failure_never_blocks_the_turn(tmp_path, caplog):
    provider = GuidanceProvider([text_turn()], diagnosis=WEAK, fail=True)
    asker = Asker()
    engine = make_engine(tmp_path, provider, asker=asker)
    events = collect(engine)
    assert asker.calls == []
    assert any(e.type == EventType.ASSISTANT_MESSAGE for e in events)
    assert not any(e.type == EventType.ERROR for e in events)
    assert "pre-flight skipped" in caplog.text
    assert "_preflight" not in [m for m in engine.messages if m.get("role") == "user"][0]


def test_unusable_diagnosis_is_skipped(tmp_path):
    class Garbage(GuidanceProvider):
        def complete(self, *, model, messages, tools=None, **settings):
            if is_diagnosis_call(messages):
                return AssistantTurn(text="sure thing, boss", finish_reason="stop")
            return super().complete(model=model, messages=messages, tools=tools, **settings)

    provider = Garbage([text_turn()])
    asker = Asker()
    engine = make_engine(tmp_path, provider, asker=asker)
    events = collect(engine)
    assert asker.calls == [] and any(e.type == EventType.ASSISTANT_MESSAGE for e in events)


def test_model_cannot_summon_the_preflight_card_by_imitating_the_arguments(tmp_path):
    from coworker.providers import ToolCall

    args = {"questions": [{"question": "继续？", "header": "要什么"}], "preflight": True, "brief": {}}
    provider = GuidanceProvider(
        [AssistantTurn(tool_calls=[ToolCall(id="call_m", name="ask_user", arguments=args)]), text_turn()],
        diagnosis=GREETING,
    )
    asker = Asker(json.dumps({"要什么": "周报"}))
    engine = make_engine(tmp_path, provider, asker=asker)
    collect(engine)
    _, call_id = asker.calls[-1]
    assert call_id == "call_m" and "data" not in asker.last_fields
    result = json.loads([m for m in engine.messages if m.get("role") == "tool"][-1]["content"])
    assert "brief" not in result


# -- compaction self-ask id (defect fix) ---------------------------------------------


def test_compaction_failure_prompt_carries_a_stable_attempt_suffixed_id(tmp_path):
    provider = CompactingProvider([text_turn("done")], summary_fails=2)
    ids = []

    async def asker(args, tool_call_id=None):
        ids.append(tool_call_id)
        return {"answer": "Trim oldest 10%"}

    engine = TurnEngine(
        provider=provider,
        registry=ToolRegistry(),
        permissions=PermissionEngine(workspace_root=tmp_path),
        model="gpt-5.5",
        messages=long_history(),
        question_asker=asker,
    )
    engine.compaction_settings = lambda: {"cap_tokens": 400, "threshold_pct": 0.8, "context_window": 100_000}
    engine.is_attended = lambda: True
    events = collect(engine, "continue")
    assert any(e.type == EventType.COMPACTED for e in events)
    assert ids and ids[0].startswith("compaction:") and ids[0].endswith(":1")


# -- manager + server ------------------------------------------------------------------


def test_manager_settings_round_trip_and_config(tmp_path):
    mgr = SessionManager(workspace=tmp_path, provider=GuidanceProvider([]))
    assert mgr.guidance_settings() == {"enabled": True, "model": ""}
    assert mgr.set_guidance_settings(enabled="no")["ok"] is False
    assert mgr.set_guidance_settings(model=3)["ok"] is False
    out = mgr.set_guidance_settings(enabled=False, model="gpt-4o-mini")
    assert out == {"ok": True, "enabled": False, "model": "gpt-4o-mini"}
    assert mgr.guidance_settings_payload() == {"guidance_enabled": False, "guidance_model": "gpt-4o-mini"}
    engine = mgr.get_engine("s-cfg", agent="cowork", workspace=str(tmp_path))
    cfg = engine.guidance_config()
    assert cfg["enabled"] is False and cfg["model"] == "gpt-4o-mini"
    assert callable(cfg["recommend"]) and isinstance(cfg["installed_skills"], set)
    assert set(cfg["recommend"]("帮我做个质量周报")) == {"skills", "experts"}
    ctx = engine.guidance_context()
    assert set(ctx) == {"memories", "rules", "roots", "skills_catalog"}
    assert ctx["roots"] and ctx["roots"][0] == str(tmp_path)


def test_inbox_asker_marks_the_item_and_accepts_the_skip(tmp_path):
    mgr = SessionManager(workspace=tmp_path, provider=GuidanceProvider([]))
    ask = mgr.inbox_question_asker("s-inbox", "cowork")
    args = {"questions": [{"question": "交付什么？", "header": "要什么", "options": ["Word"]}]}

    async def scenario():
        task = asyncio.create_task(ask(args, "preflight:1"))
        for _ in range(100):
            await asyncio.sleep(0.01)
            if mgr.inbox.pending("s-inbox"):
                break
        item = mgr.inbox.pending("s-inbox")[0]
        assert item.data == {"preflight": True} and item.tool_call_id == "preflight:1"
        await mgr.resolve_inbox(item.id, PREFLIGHT_SKIP)
        return await task

    assert asyncio.run(scenario()) == {"answers": {}, "skipped": True}


def test_ws_turn_surfaces_the_preflight_card_and_the_settings_routes(tmp_path):
    provider = GuidanceProvider([text_turn()], diagnosis=WEAK)
    mgr = SessionManager(workspace=tmp_path, provider=provider)
    client = TestClient(create_app(mgr))

    assert client.get("/v1/settings").json()["guidance_enabled"] is True
    assert client.post("/v1/settings/guidance", json={"guidance_model": "m1"}).json()["model"] == "m1"
    assert client.get("/v1/settings").json()["guidance_model"] == "m1"

    with client.websocket_connect("/ws/session/pre1") as ws:
        assert ws.receive_json()["type"] == "ready"
        ws.send_json({"type": "user_message", "text": "帮我做个质量周报"})
        seen = []
        while True:
            ev = ws.receive_json()
            seen.append(ev["type"])
            if ev["type"] == "question_requested":
                assert ev["data"]["preflight"] is True
                # the real recommender runs here: the matched skill is not installed in
                # this fresh workspace, so no 技能 question — just the two weak dimensions
                assert [q["header"] for q in ev["data"]["questions"]] == ["给谁看", "要什么"]
                ws.send_json({"type": "question_response", "answer": ANSWERS})
            if ev["type"] == "turn_done":
                break
    assert "preflight" in seen and "tool_proposed" in seen and "assistant_message" in seen
    rec = mgr.session_store.load("pre1")
    tool = [m for m in rec.messages if m.get("role") == "tool"][-1]
    assert "<task-brief>" in json.loads(tool["content"])["brief"]
    assert provider.diagnosis_calls[0]["model"] == "m1"
