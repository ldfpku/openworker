"""来源与升级 §1–§4 over the server: source endpoints, external rows in /v1/skills,
read-only refusals, the session menu, manual-invocation gating and the catalog budget.

ScriptedProvider only — no LLM, no network. Skill folders live under the fake home the
conftest provides (COWORKER_SKILL_HOME)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from coworker.providers import AssistantTurn, ModelCapabilities, ProviderClient, ToolCall
from coworker.providers.base import SYSTEM_CONTEXT_OPEN
from coworker.server import SessionManager, create_app
from coworker.skills import reset_shared_loaders
from coworker.skills.base import SkillLoader, skill_catalog_text
from coworker.skills.external import skill_home
from coworker.testing.autotitle import autotitle_reply, is_autotitle_call
from coworker.testing.guidance import diagnosis_reply, is_diagnosis_call


class ScriptedProvider(ProviderClient):
    """Same shape as tests/test_skills_api.py's: title/diagnosis side calls diverted."""

    def __init__(self, turns=None):
        self._turns = list(turns or [])
        self.seen: list[list[dict]] = []

    def complete(self, *, model, messages, tools=None, **settings):
        if is_autotitle_call(messages):
            return autotitle_reply()
        if is_diagnosis_call(messages):
            return diagnosis_reply()
        self.seen.append(messages)
        return self._turns.pop(0)

    def capabilities(self, model):
        return ModelCapabilities()


def _skill(folder: Path, name: str, description: str = "d", extra: str = "") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n{extra}---\n\nDo the {name} thing.\n",
        encoding="utf-8",
    )
    return folder


@pytest.fixture(autouse=True)
def _fresh_loaders():
    reset_shared_loaders()
    yield
    reset_shared_loaders()


@pytest.fixture
def home() -> Path:
    h = skill_home()
    _skill(h / ".agents/skills/translate-pdf", "translate-pdf", "Translate a PDF to Chinese")
    _skill(h / ".agents/skills/mermaid", "mermaid", "Pretty mermaid diagrams")
    _skill(
        h / ".agents/skills/deploy",
        "deploy",
        "Deploy the thing",
        extra="disable-model-invocation: true\n",
    )
    return h


def _client(tmp_path, turns=None):
    provider = ScriptedProvider(turns)
    manager = SessionManager(workspace=tmp_path, provider=provider)
    return TestClient(create_app(manager)), manager, provider


def _rows(client):
    return {r["name"]: r for r in client.get("/v1/skills").json()["skills"]}


def _context_blocks(provider) -> str:
    return "\n".join(
        str(m["content"])
        for msgs in provider.seen
        for m in msgs
        if m["role"] == "user" and str(m["content"]).startswith(SYSTEM_CONTEXT_OPEN)
    )


# -- sources --------------------------------------------------------------------------


def test_sources_listed_off_by_default_and_toggle(tmp_path, home):
    client, _m, _p = _client(tmp_path)
    sources = {s["id"]: s for s in client.get("/v1/skills/sources").json()["sources"]}
    assert sources["agents"]["count"] == 3 and sources["agents"]["enabled"] is False
    assert _rows(client) == {}  # off → nothing external listed
    res = client.patch("/v1/skills/sources/agents", json={"enabled": True}).json()
    assert res["ok"] is True
    rows = _rows(client)
    assert set(rows) == {"translate-pdf", "mermaid", "deploy"}
    row = rows["mermaid"]
    assert row["origin"] == "external" and row["read_only"] is True
    assert row["scope"] == "external" and row["source_id"] == "agents"
    assert row["invocation"] == "manual" and row["invocation_locked"] is False
    # No ~/.agents/.skill-lock.json entry → known untracked without asking GitHub.
    assert row["update"]["status"] == "untracked"
    assert rows["deploy"]["invocation_locked"] is True
    assert client.patch("/v1/skills/sources/nope", json={"enabled": True}).json()["ok"] is False
    assert client.patch("/v1/skills/sources/agents", json={"enabled": "yes"}).json()["ok"] is False


def test_custom_source_endpoints(tmp_path, home):
    client, _m, _p = _client(tmp_path)
    folder = tmp_path / "team"
    _skill(folder / "team-one", "team-one")
    added = client.post("/v1/skills/sources", json={"path": str(folder), "label": "团队"}).json()
    assert added["ok"] is True and added["id"].startswith("custom-")
    assert "team-one" in _rows(client)
    assert client.post("/v1/skills/sources", json={"path": "relative"}).json()["ok"] is False
    assert client.delete("/v1/skills/sources/agents").json()["ok"] is False
    assert client.delete(f"/v1/skills/sources/{added['id']}").json()["ok"] is True
    assert "team-one" not in _rows(client)


def test_external_skills_are_read_only(tmp_path, home):
    client, _m, _p = _client(tmp_path)
    client.patch("/v1/skills/sources/agents", json={"enabled": True})
    for res in (
        client.patch("/v1/skills/mermaid", json={"description": "x"}).json(),
        client.delete("/v1/skills/mermaid").json(),
        client.post("/v1/skills/mermaid/move", json={"scope": "global"}).json(),
    ):
        assert res["ok"] is False and "只读" in res["error"]
    assert (home / ".agents/skills/mermaid/SKILL.md").is_file()
    # The per-skill switch is personal state, not a write into the folder.
    assert client.patch("/v1/skills/mermaid", json={"enabled": False}).json()["ok"] is True
    assert _rows(client)["mermaid"]["enabled"] is False


def test_own_skill_shadows_external(tmp_path, home):
    client, _m, _p = _client(tmp_path)
    client.patch("/v1/skills/sources/agents", json={"enabled": True})
    client.post(
        "/v1/skills", json={"name": "mermaid", "description": "mine", "instructions": "Mine."}
    )
    rows = client.get("/v1/skills").json()["skills"]
    mine = [r for r in rows if r["name"] == "mermaid"]
    assert [r["origin"] for r in mine] == ["own", "external"]
    assert mine[1]["shadowed_by"] == "global"
    # Edits now reach the own copy, not the external folder.
    assert client.patch("/v1/skills/mermaid", json={"description": "x"}).json()["ok"] is True
    view = client.get("/v1/sessions/s1/skills").json()["skills"]
    assert [v["scope"] for v in view if v["name"] == "mermaid"] == ["global"]


def test_invocation_switch(tmp_path, home):
    client, _m, _p = _client(tmp_path)
    client.patch("/v1/skills/sources/agents", json={"enabled": True})
    assert client.patch("/v1/skills/mermaid", json={"invocation": "auto"}).json()["ok"] is True
    assert _rows(client)["mermaid"]["invocation"] == "auto"
    locked = client.patch("/v1/skills/deploy", json={"invocation": "auto"}).json()
    assert locked["ok"] is False and "disable-model-invocation" in locked["error"]
    bad = client.patch("/v1/skills/mermaid", json={"invocation": "maybe"}).json()
    assert bad["ok"] is False
    client.post("/v1/skills", json={"name": "greet", "description": "d", "instructions": "x"})
    own = client.patch("/v1/skills/greet", json={"invocation": "manual"}).json()
    assert own["ok"] is False


def test_session_view_marks_external_and_manual(tmp_path, home):
    client, _m, _p = _client(tmp_path)
    client.patch("/v1/skills/sources/agents", json={"enabled": True})
    client.patch("/v1/skills/mermaid", json={"invocation": "auto"})
    view = {v["name"]: v for v in client.get("/v1/sessions/s1/skills").json()["skills"]}
    assert view["translate-pdf"]["scope"] == "external"
    assert view["translate-pdf"]["manual"] is True
    assert view["translate-pdf"]["source_label"]
    assert view["translate-pdf"]["source_id"] == "agents"  # the GUI localizes by id
    assert view["mermaid"]["manual"] is False


# -- the engine: catalog + load gate ---------------------------------------------------


def test_manual_skills_stay_out_of_the_catalog_and_force_run_loads(tmp_path, home):
    load = AssistantTurn(
        tool_calls=[ToolCall(id="c1", name="load_skill", arguments={"name": "translate-pdf"})]
    )
    client, _m, provider = _client(tmp_path, [load, AssistantTurn(text="done")])
    client.patch("/v1/skills/sources/agents", json={"enabled": True})
    client.patch("/v1/skills/mermaid", json={"invocation": "auto"})
    with client.websocket_connect("/ws/session/s1?agent=chat") as ws:
        assert ws.receive_json()["type"] == "ready"
        ws.send_json({"type": "user_message", "text": "a.pdf", "skill": "translate-pdf"})
        while ws.receive_json()["type"] != "turn_done":
            pass
    context = _context_blocks(provider)
    assert "mermaid" in context  # auto → listed
    assert "translate-pdf" not in context and "deploy" not in context  # manual → zero cost
    stored = client.get("/v1/sessions/s1/messages").json()["messages"]
    result = next(m for m in stored if m["role"] == "tool")
    body = json.loads(result["content"]) if isinstance(result["content"], str) else {}
    assert "Do the translate-pdf thing." in str(result["content"])
    assert body.get("origin") == "external"


def test_model_cannot_load_a_manual_skill_unasked(tmp_path, home):
    load = AssistantTurn(
        tool_calls=[ToolCall(id="c1", name="load_skill", arguments={"name": "translate-pdf"})]
    )
    client, _m, provider = _client(tmp_path, [load, AssistantTurn(text="done")])
    client.patch("/v1/skills/sources/agents", json={"enabled": True})
    with client.websocket_connect("/ws/session/s1?agent=chat") as ws:
        assert ws.receive_json()["type"] == "ready"
        ws.send_json({"type": "user_message", "text": "translate a.pdf"})
        while ws.receive_json()["type"] != "turn_done":
            pass
    stored = client.get("/v1/sessions/s1/messages").json()["messages"]
    result = str(next(m for m in stored if m["role"] == "tool")["content"])
    assert "unknown skill" in result
    assert "translate-pdf" not in result.split("available", 1)[-1]  # not even named


def test_settings_disable_beats_force_run(tmp_path, home):
    client, _m, _p = _client(tmp_path, [AssistantTurn(text="ok")])
    client.patch("/v1/skills/sources/agents", json={"enabled": True})
    client.patch("/v1/skills/translate-pdf", json={"enabled": False})
    with client.websocket_connect("/ws/session/s1?agent=chat") as ws:
        assert ws.receive_json()["type"] == "ready"
        ws.send_json({"type": "user_message", "text": "x", "skill": "translate-pdf"})
        assert ws.receive_json()["type"] == "input_rejected"


def test_own_manual_only_skill_is_out_of_catalog_but_force_runnable(tmp_path, home):
    client, manager, _p = _client(tmp_path)
    folder = manager.skill_store.global_dir / "release"
    _skill(folder, "release", "Cut a release", extra="disable-model-invocation: true\n")
    assert "release" in manager.manual_skill_names("s1")
    assert "release" in manager.effective_skill_names("s1")  # force-run validation passes
    manager.note_skill_invoked("s1", "release")
    manual, invoked = manager.skill_invocation_state("s1")
    assert "release" in manual and "release" in invoked


def test_source_switched_on_mid_session_applies_next_turn(tmp_path, home):
    from coworker.agent import build_engine
    from coworker.agents.chat import chat_agent

    _client_, manager, _p = _client(tmp_path)
    engine = build_engine(
        agent=chat_agent(),
        provider=ScriptedProvider(),
        skill_filter=lambda: manager.effective_skill_names("s1"),
        external_skill_dirs=manager.skill_sources.loader_dirs,
        skill_invocation=lambda: manager.skill_invocation_state("s1"),
    )
    assert "mermaid" not in engine.context_provider()
    manager.skill_sources.set_enabled("agents", True)
    manager.skill_sources.set_invocation("mermaid", "auto")
    assert "mermaid" in engine.context_provider()
    assert "translate-pdf" not in engine.context_provider()


# -- catalog budget (来源与升级 §4) -----------------------------------------------------


def test_catalog_unchanged_under_budget(tmp_path):
    root = tmp_path / "skills"
    _skill(root / "a", "a", "alpha")
    _skill(root / "b", "b", "beta")
    text = skill_catalog_text(SkillLoader([root]))
    assert text == (
        "Available skills — call load_skill(name) to load one's full instructions when "
        "it's relevant to the task:\n- a: alpha\n- b: beta"
    )


def test_catalog_budget_gives_descriptions_to_higher_layers_first(tmp_path):
    low, high = tmp_path / "external", tmp_path / "global"
    for i in range(40):
        _skill(low / f"ext-{i:02d}", f"ext-{i:02d}", "x" * 150)
    _skill(high / "mine", "mine", "my own skill")
    text = skill_catalog_text(SkillLoader([low, high]))
    lines = text.splitlines()
    assert lines[1] == "- mine: my own skill"  # the higher layer is described first
    assert len(text) < 4000 + 2000  # descriptions capped, names-only tail is short
    tail = lines[-1]
    assert tail.startswith("Also available")
    assert "ext-39" in tail
    described = [line for line in lines if line.startswith("- ")]
    assert sum(len(line) + 1 for line in described) <= 4000


def test_catalog_skips_manual_only_skills(tmp_path):
    root = tmp_path / "skills"
    _skill(root / "a", "a", "alpha")
    _skill(root / "m", "m", "manual", extra="disable-model-invocation: true\n")
    assert "- m:" not in skill_catalog_text(SkillLoader([root]))
