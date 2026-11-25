"""Image input declared by an endpoint's own /models row (custom / self-hosted gateways).

Owner-hit 2026-11-25: `custom:localai` and `custom:inkling-2-mini` (the SMJ local-model
gateway) both read images, but their ids match none of the vendor-name heuristics in
capabilities.py, so the engine fell to `vision=False` and swapped every image for the
"[image attachment — not viewable by this model]" placeholder before sending. The gateway
now declares `architecture.input_modalities`; these tests pin that the declaration is read
and honoured — and that curated models and endpoints that say nothing are unaffected.
"""

from __future__ import annotations

from coworker.engine import TurnEngine
from coworker.permissions import PermissionEngine
from coworker.providers import ProviderClient, capabilities_for
from coworker.providers.catalog import CatalogModel, parse_openai_compat
from coworker.providers.matrix import model_labels
from coworker.server.manager import SessionManager
from coworker.tools import ToolRegistry

IMAGE = {"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBORw0KGgo="}}
PLACEHOLDER = "[image attachment — not viewable by this model]"


# -- catalog parsing -----------------------------------------------------------------


def _vision_of(entry):
    return parse_openai_compat({"data": [{"id": "localai", **entry}]}, "custom", "SMJ")[0].vision


def test_openrouter_architecture_input_modalities():
    assert _vision_of({"architecture": {"input_modalities": ["text", "image"]}}) is True
    assert _vision_of({"architecture": {"input_modalities": ["text"]}}) is False


def test_top_level_input_modalities_and_capabilities_spellings():
    assert _vision_of({"input_modalities": ["text", "Image"]}) is True
    assert _vision_of({"capabilities": {"vision": True}}) is True
    assert _vision_of({"capabilities": {"vision": False}}) is False
    assert _vision_of({"capabilities": ["tools", "vision"]}) is True


def test_silent_row_stays_unknown_and_out_of_the_cache():
    assert _vision_of({"context_window": 262144}) is None
    assert "vision" not in CatalogModel("localai", "SMJ", 262144).to_dict()
    assert CatalogModel("localai", "SMJ", 262144, vision=True).to_dict()["vision"] is True


def test_the_smj_gateway_models_body():
    # Exactly what smj-local-ai's /v1/models returns (src/models.ts).
    payload = {
        "object": "list",
        "data": [
            {
                "id": "localai",
                "object": "model",
                "created": 1,
                "owned_by": "smj-local-ai",
                "name": "SMJ 本地模型（自动）",
                "context_length": 262144,
                "context_window": 262144,
                "architecture": {"input_modalities": ["text", "image"], "output_modalities": ["text"]},
            }
        ],
    }
    [m] = parse_openai_compat(payload, "custom", "SMJ")
    assert (m.id, m.context_window, m.vision) == ("localai", 262144, True)


# -- manager getter ------------------------------------------------------------------


def _bare_manager(rows, configured=True):
    m = object.__new__(SessionManager)
    m._model_catalog = {"custom": {"models": rows}}
    m._provider_configured = lambda name: configured and name == "custom"
    return m


def test_manager_catalog_vision_reads_cached_rows():
    m = _bare_manager(
        [
            {"id": "localai", "label": "SMJ", "vision": True},
            {"id": "text-only", "label": "T", "vision": False},
            {"id": "silent", "label": "S"},
        ]
    )
    assert m.catalog_vision("custom:localai") is True
    assert m.catalog_vision("custom:text-only") is False
    assert m.catalog_vision("custom:silent") is None
    assert m.catalog_vision("custom:missing") is None


def test_manager_ignores_an_unconfigured_providers_cache():
    m = _bare_manager([{"id": "localai", "label": "SMJ", "vision": True}], configured=False)
    assert m.catalog_vision("custom:localai") is None


# -- engine --------------------------------------------------------------------------


class _Provider(ProviderClient):
    def complete(self, *, model, messages, tools=None, **settings):  # pragma: no cover
        raise AssertionError("not called")

    def capabilities(self, model):
        return capabilities_for(model)


def _engine(tmp_path, model, declared):
    engine = TurnEngine(
        provider=_Provider(),
        registry=ToolRegistry(),
        permissions=PermissionEngine(workspace_root=tmp_path),
        model=model,
    )
    engine.catalog_vision = lambda m: declared.get(m)
    return engine


def test_declared_vision_lifts_the_conservative_default(tmp_path):
    engine = _engine(tmp_path, "custom:localai", {"custom:localai": True})
    assert capabilities_for("custom:localai").vision is False  # the heuristic alone
    assert engine._model_capabilities("custom:localai").vision is True


def test_silent_endpoint_keeps_the_heuristic(tmp_path):
    engine = _engine(tmp_path, "custom:localai", {})
    assert engine._model_capabilities("custom:localai").vision is False


def test_curated_models_ignore_the_catalog(tmp_path):
    curated = next(iter(model_labels()))
    engine = _engine(tmp_path, curated, {curated: not capabilities_for(curated).vision})
    assert engine._model_capabilities(curated).vision is capabilities_for(curated).vision


def _outbound_parts(engine):
    engine.messages = [
        {"role": "system", "content": "be helpful"},
        {"role": "user", "content": [{"type": "text", "text": "translate this"}, IMAGE]},
    ]
    return [
        p
        for msg in engine._outbound_messages()
        if isinstance(msg.get("content"), list)
        for p in msg["content"]
    ]


def test_image_reaches_a_model_whose_endpoint_declares_vision(tmp_path):
    parts = _outbound_parts(_engine(tmp_path, "custom:localai", {"custom:localai": True}))
    assert IMAGE in parts
    assert not any(p.get("text") == PLACEHOLDER for p in parts)


def test_image_still_replaced_when_the_endpoint_says_nothing(tmp_path):
    parts = _outbound_parts(_engine(tmp_path, "custom:localai", {}))
    assert IMAGE not in parts
    assert any(p.get("text") == PLACEHOLDER for p in parts)


def test_model_switch_notice_drops_the_no_vision_suffix(tmp_path):
    engine = _engine(tmp_path, "custom:other", {"custom:inkling-2-mini": True})
    engine.messages = [
        {"role": "system", "content": "be helpful"},
        {"role": "user", "content": [{"type": "text", "text": "translate this"}, IMAGE]},
        {"role": "assistant", "content": "ok"},
    ]
    text = engine.switch_model("custom:inkling-2-mini")
    assert text and "earlier images can't be read" not in text
