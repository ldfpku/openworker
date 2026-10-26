"""gateway-guard's per-person model list, client side.

The company gateway's guard Worker is an ALLOWLIST: `GET {base}/gate/models` returns
exactly the models this person's administrator ticked for them, and it is the single
source of truth for what the app may offer under `aigw:`. (The old denylist — `/gate/policy`
`blocked` / `uncovered` / `families` — is gone, and so is every helper that read it.)

What these pin, all offline:

* the curated matrix never offers a gateway model on its own — no server list, no `aigw:`
  models; with a list, only what is on it (the matrix just labels those);
* a failed refresh keeps the last successfully fetched list — it neither empties the picker
  nor falls back to the matrix;
* every successful pull reconciles local picks against the list (custom ids, hidden ids);
* a default model that has left the list is NOT silently replaced: `model_ready` goes
  false, `model_notice` says why, and the dead id is no longer offered;
* the auto-title sibling is used only when it is on the list;
* the dynamic-route "has a stand-in" badge needs both ends of the route on the list.

Enforcement is server-side either way (the guard answers 403 `model_restricted`); the
client's job is to not offer what it already knows will be refused.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from coworker.providers.aigateway_provider import _ROUTES, route_allowed
from coworker.providers.matrix import MATRIX
from coworker.server.manager import SessionManager

_AIGW_MATRIX = [m for m in MATRIX if m.startswith("aigw:")]


def _rows(*ids: str) -> list[dict]:
    return [{"id": i, "label": f"{i} · via Cloudflare", "context_window": None} for i in ids]


def _mgr(tmp_path, monkeypatch, *listed: str, default: str = "gpt-5.6-sol") -> SessionManager:
    """A real manager, signed in to the gateway with a pasted session, whose `aigw`
    catalog already holds `listed` (as if a pull had succeeded earlier). No `listed` →
    no pull has ever succeeded."""
    monkeypatch.delenv("CLOUDFLARE_AIGW_BASE_URL", raising=False)
    monkeypatch.delenv("CLOUDFLARE_AIGW_ACCESS_TOKEN", raising=False)
    mgr = SessionManager(data_dir=tmp_path / "data")
    # Merged into the profile, not put over it: the manager has just stamped the gateway
    # generation there, and losing the stamp would make the next start "migrate" again —
    # retiring this session and dropping the cached list with it.
    profile = dict(mgr.secrets.get("provider:aigw") or {})
    mgr.secrets.put("provider:aigw", {**profile, "access_token": "jwt"})
    mgr.model = default
    if listed:
        mgr._model_catalog["aigw"] = {
            "fetched_at": "2026-10-13T00:00:00+00:00",
            "models": _rows(*listed),
            "error": None,
            "failed_at": None,
        }
    return mgr


def _pull(monkeypatch, result: dict) -> None:
    """What the next `/gate/models` pull answers (overrides conftest's offline stub)."""
    monkeypatch.setattr(
        SessionManager, "_fetch_model_catalog", lambda self, name, fields=None: dict(result)
    )


def _pull_ok(monkeypatch, *ids: str) -> None:
    _pull(monkeypatch, {"ok": True, "models": _rows(*ids)})


# -- the list is re-pulled often, and without a visit to Settings -------------------------


def _stamp(mgr: SessionManager, seconds_ago: float) -> None:
    from datetime import datetime, timedelta, timezone

    mgr._model_catalog["aigw"]["fetched_at"] = (
        datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)
    ).isoformat()


def test_the_gateway_list_goes_stale_in_minutes_not_hours(tmp_path, monkeypatch):
    """An administrator's untick has to reach the picker soon: the gateway catalog uses
    its own short TTL, while every other provider's roster keeps the six-hour one."""
    mgr = _mgr(tmp_path, monkeypatch, "anthropic/claude-sonnet-5")
    _stamp(mgr, SessionManager.AIGW_CATALOG_TTL - 60)
    assert not mgr._catalog_is_stale("aigw")
    _stamp(mgr, SessionManager.AIGW_CATALOG_TTL + 60)
    assert mgr._catalog_is_stale("aigw")
    assert SessionManager.AIGW_CATALOG_TTL < SessionManager.MODEL_CATALOG_TTL
    mgr._model_catalog["gemini"] = dict(mgr._model_catalog["aigw"])
    assert not mgr._catalog_is_stale("gemini")  # same age, ordinary TTL


def test_get_settings_repulls_a_stale_gateway_list(tmp_path, monkeypatch):
    """`get_settings` is the call every open GUI makes; it is what keeps a long-running
    app following the list without anyone opening Settings ▸ Models. Fresh list → no
    pull; stale list → exactly one background pull is started."""
    mgr = _mgr(tmp_path, monkeypatch, "anthropic/claude-sonnet-5")
    kicked: list[str] = []
    monkeypatch.setattr(SessionManager, "kick_catalog_refresh", lambda self, name: kicked.append(name))
    _stamp(mgr, 30)
    mgr.get_settings()
    assert kicked == []
    _stamp(mgr, SessionManager.AIGW_CATALOG_TTL + 60)
    mgr.get_settings()
    assert kicked == ["aigw"]


def test_a_signed_out_gateway_is_never_pulled_from_get_settings(tmp_path, monkeypatch):
    monkeypatch.delenv("CLOUDFLARE_AIGW_BASE_URL", raising=False)
    monkeypatch.delenv("CLOUDFLARE_AIGW_ACCESS_TOKEN", raising=False)
    mgr = SessionManager(data_dir=tmp_path / "data")
    kicked: list[str] = []
    monkeypatch.setattr(SessionManager, "kick_catalog_refresh", lambda self, name: kicked.append(name))
    mgr.get_settings()
    assert kicked == []


# -- the server list is the only list ----------------------------------------------------
def test_the_dead_gate_policy_helpers_are_gone():
    # Removed with the denylist, not shimmed: nothing may quietly keep depending on
    # `/gate/policy` keys the guard no longer sends.
    import coworker.providers.aigateway_provider as provider_mod

    for name in (
        "fetch_gate_policy",
        "blocked_model_ids",
        "is_blocked_model",
        "gate_families",
        "is_out_of_scope",
        "is_gated_model",
        "family_form",
        "PROBE_MODEL",
    ):
        assert not hasattr(provider_mod, name), name
    for name in ("_refresh_aigw_gate", "_aigw_blocked", "_aigw_families"):
        assert not hasattr(SessionManager, name), name


def test_the_matrix_never_offers_a_gateway_model_without_a_server_list(tmp_path, monkeypatch):
    mgr = _mgr(tmp_path, monkeypatch)  # signed in, but no pull has ever succeeded
    assert mgr._aigw_allowed() is None
    assert not any(m.startswith("aigw:") for m in mgr._matrix_ids_in_effect())
    assert not any(m.startswith("aigw:") for m in mgr._curated_models())
    assert not any(m.startswith("aigw:") for m in mgr.get_settings()["models"])
    # …and the Cloudflare card has nothing to suggest either — no matrix stand-in.
    assert mgr._suggested_models("aigw") == []
    # Every other provider still trusts its matrix rows with no catalog, as before.
    assert "anthropic:claude-fable-5" in mgr._matrix_ids_in_effect()
    assert "glm-5.2" in mgr._suggested_models("zai")


def test_with_a_server_list_only_listed_models_are_offered(tmp_path, monkeypatch):
    mgr = _mgr(
        tmp_path,
        monkeypatch,
        "anthropic/claude-sonnet-5",  # a curated row
        "openai/gpt-6-luna",  # on the list, unknown to the matrix
    )
    offered = [m for m in mgr.get_settings()["models"] if m.startswith("aigw:")]
    # The one matrix row that is on the list — and none of the others the matrix carries.
    assert offered == ["aigw:anthropic/claude-sonnet-5"]
    assert len(_AIGW_MATRIX) > 1
    # The card lists the whole server list (matrix-known ids first), nothing else.
    assert mgr._suggested_models("aigw") == ["anthropic/claude-sonnet-5", "openai/gpt-6-luna"]
    # The matrix's part is the label: its vetted name wins for the id it knows, and the
    # id it does not know keeps the label the catalog gave it.
    labels = mgr.get_settings()["model_labels"]
    assert labels["aigw:anthropic/claude-sonnet-5"] == MATRIX["aigw:anthropic/claude-sonnet-5"].label
    assert labels["aigw:openai/gpt-6-luna"] == "openai/gpt-6-luna · via Cloudflare"


def test_the_list_only_judges_gateway_ids(tmp_path, monkeypatch):
    # The same flagship reached directly (own API key) is none of the gateway's business.
    mgr = _mgr(tmp_path, monkeypatch, "anthropic/claude-sonnet-5")
    models = mgr._curated_models()
    assert "gpt-5.6-sol" in models
    assert "anthropic:claude-fable-5" in models
    assert "aigw:anthropic/claude-fable-5" not in models


def test_a_ticked_non_matrix_model_stays_only_while_it_is_listed(tmp_path, monkeypatch):
    mgr = _mgr(tmp_path, monkeypatch, "anthropic/claude-sonnet-5", "openai/gpt-6-luna")
    assert mgr.add_model("aigw:openai/gpt-6-luna")["ok"] is True
    assert "aigw:openai/gpt-6-luna" in mgr.get_settings()["models"]
    # An id that is not on the list is refused outright rather than stored and filtered.
    res = mgr.add_model("aigw:grok/grok-4.7")
    assert res["ok"] is False and "model list" in res["error"]
    assert "aigw:grok/grok-4.7" not in (mgr._prefs.get("models") or [])


def test_a_stale_custom_id_is_not_offered_even_before_reconciliation(tmp_path, monkeypatch):
    # Saved by an older version, or before the administrator unticked it: the filter in
    # `_curated_models` covers the window until the next successful pull tidies prefs.
    mgr = _mgr(tmp_path, monkeypatch, "anthropic/claude-sonnet-5")
    mgr._prefs["models"] = ["aigw:grok/grok-4.7", "zai:glm-9"]
    models = mgr._curated_models()
    assert "aigw:grok/grok-4.7" not in models
    assert "zai:glm-9" in models


# -- a failed refresh keeps the last list --------------------------------------------------
@pytest.mark.parametrize(
    "error",
    [
        "Couldn't reach Cloudflare AI Gateway (ConnectError).",
        "网关配置暂时读不到，请稍后重试。[gateway-guard]",  # 503 gate_unavailable
        "你的账号暂未开通任何模型，请联系管理员。[gateway-guard]",  # 502 catalog_unavailable
    ],
)
def test_a_failed_refresh_keeps_the_last_fetched_list(tmp_path, monkeypatch, error):
    mgr = _mgr(tmp_path, monkeypatch)
    _pull_ok(monkeypatch, "anthropic/claude-sonnet-5", "openai/gpt-5.6-terra")
    assert mgr.refresh_model_catalog("aigw")["ok"] is True
    before = mgr.get_settings()["models"]
    assert "aigw:openai/gpt-5.6-terra" in before

    _pull(monkeypatch, {"ok": False, "error": error})
    res = mgr.refresh_model_catalog("aigw")
    assert res["ok"] is False and res["error"] == error
    # Same list, not an empty one and not the matrix's.
    assert mgr._aigw_allowed() == frozenset({"anthropic/claude-sonnet-5", "openai/gpt-5.6-terra"})
    assert mgr.get_settings()["models"] == before
    assert "aigw:anthropic/claude-fable-5" not in mgr.get_settings()["models"]
    # The status row dates the last list that arrived and shows the guard's sentence verbatim.
    status = mgr._catalog_status("aigw")
    assert status["live"] is True and status["error"] == error and status["fetched_at"]

    # …and it is still the list after a restart.
    reborn = SessionManager(data_dir=tmp_path / "data")
    assert reborn._aigw_allowed() == frozenset({"anthropic/claude-sonnet-5", "openai/gpt-5.6-terra"})


def test_a_first_pull_that_fails_offers_nothing(tmp_path, monkeypatch):
    mgr = _mgr(tmp_path, monkeypatch)
    _pull(monkeypatch, {"ok": False, "error": "offline"})
    mgr.refresh_model_catalog("aigw")
    assert mgr._aigw_allowed() is None
    assert not any(m.startswith("aigw:") for m in mgr.get_settings()["models"])
    assert mgr._catalog_status("aigw")["error"] == "offline"


def test_signing_in_does_not_auto_add_the_recommended_model_without_a_list(tmp_path, monkeypatch):
    # `set_provider` used to fall back to the matrix when the pull failed; for the gateway
    # that would be the matrix adding a model on its own.
    mgr = _mgr(tmp_path, monkeypatch)
    _pull(monkeypatch, {"ok": False, "error": "offline"})
    assert mgr.set_provider("aigw", {})["ok"] is True
    assert not any(m.startswith("aigw:") for m in mgr.get_settings()["models"])
    # With a list that carries it, the same sign-in lands it in the composer as before.
    _pull_ok(monkeypatch, "anthropic/claude-sonnet-5")
    mgr.set_provider("aigw", {})
    assert "aigw:anthropic/claude-sonnet-5" in mgr.get_settings()["models"]


# -- reconciliation ------------------------------------------------------------------------
def test_a_successful_pull_drops_local_picks_that_left_the_list(tmp_path, monkeypatch):
    mgr = _mgr(tmp_path, monkeypatch, "anthropic/claude-sonnet-5", "openai/gpt-6-luna")
    mgr._prefs["models"] = [
        "aigw:openai/gpt-6-luna",  # still listed after the pull below
        "aigw:workers-ai/@cf/zai-org/glm-5.3",  # no longer listed
        "zai:glm-9",  # another provider's custom id: never looked at
        "my-own-finetune",
    ]
    mgr._prefs["hidden_models"] = [
        "aigw:anthropic/claude-sonnet-5",  # still listed → still hidden
        "aigw:anthropic/claude-fable-5",  # gone from the list → tidied away
        "anthropic:claude-haiku-5-5",
    ]
    _pull_ok(monkeypatch, "anthropic/claude-sonnet-5", "openai/gpt-6-luna")
    assert mgr.refresh_model_catalog("aigw")["ok"] is True

    assert mgr._prefs["models"] == ["aigw:openai/gpt-6-luna", "zai:glm-9", "my-own-finetune"]
    assert mgr._prefs["hidden_models"] == [
        "aigw:anthropic/claude-sonnet-5",
        "anthropic:claude-haiku-5-5",
    ]
    # Persisted with the list itself, not only in memory.
    reborn = SessionManager(data_dir=tmp_path / "data")
    assert reborn._prefs["models"] == ["aigw:openai/gpt-6-luna", "zai:glm-9", "my-own-finetune"]


def test_reconciliation_runs_on_every_path_that_lands_a_pull(tmp_path, monkeypatch):
    import coworker.server.manager as manager_mod

    stale = "aigw:grok/grok-4.7"

    def fresh(name: str) -> SessionManager:
        mgr = _mgr(tmp_path / name, monkeypatch)
        mgr._prefs["models"] = [stale]
        return mgr

    _pull_ok(monkeypatch, "anthropic/claude-sonnet-5")

    # 1. Settings ▸ Models "Refresh" (and `set_provider` on sign-in, which calls the same).
    mgr = fresh("refresh")
    mgr.refresh_model_catalog("aigw")
    assert stale not in mgr._prefs["models"]

    # 2. The background pull: server start (`warm_model_catalogs`) and the TTL refresh
    #    behind `get_providers` both go through `kick_catalog_refresh`.
    mgr = fresh("kick")
    assert "aigw" in mgr.warm_model_catalogs()
    for _ in range(200):
        if "aigw" not in mgr._catalog_inflight and mgr._aigw_allowed() is not None:
            break
        time.sleep(0.01)
    assert stale not in mgr._prefs["models"]

    # 3. The Test button.
    mgr = fresh("test")
    monkeypatch.setattr(manager_mod, "verify_provider_key", lambda name, **k: {"ok": True})
    monkeypatch.setattr(
        manager_mod,
        "list_provider_models",
        lambda name, **k: {"ok": True, "models": _rows("anthropic/claude-sonnet-5")},
    )
    assert mgr.verify_provider("aigw", {}) == {"ok": True}
    assert stale not in mgr._prefs["models"]


def test_a_failed_pull_reconciles_nothing(tmp_path, monkeypatch):
    mgr = _mgr(tmp_path, monkeypatch, "anthropic/claude-sonnet-5")
    mgr._prefs["models"] = ["aigw:grok/grok-4.7"]
    _pull(monkeypatch, {"ok": False, "error": "offline"})
    mgr.refresh_model_catalog("aigw")
    assert mgr._prefs["models"] == ["aigw:grok/grok-4.7"]  # untouched, merely not offered


# -- the default model left the list ---------------------------------------------------------
def test_a_dead_default_is_reported_not_silently_replaced(tmp_path, monkeypatch):
    mgr = _mgr(
        tmp_path,
        monkeypatch,
        "anthropic/claude-fable-5",
        "anthropic/claude-sonnet-5",
        default="aigw:anthropic/claude-fable-5",
    )
    mgr._prefs["default_model"] = "aigw:anthropic/claude-fable-5"
    ok = mgr.get_settings()
    assert ok["model_ready"] is True and ok["model_notice"] is None
    assert ok["models"][0] == "aigw:anthropic/claude-fable-5"

    _pull_ok(monkeypatch, "anthropic/claude-sonnet-5")  # the administrator unticked Fable
    mgr.refresh_model_catalog("aigw")

    after = mgr.get_settings()
    # No substitution: the default is still what the person chose, in memory and on disk…
    assert mgr.model == "aigw:anthropic/claude-fable-5"
    assert mgr._prefs["default_model"] == "aigw:anthropic/claude-fable-5"
    assert after["model"] == "aigw:anthropic/claude-fable-5"
    # …but it is no longer offered, and the composer is told to ask for a choice.
    assert "aigw:anthropic/claude-fable-5" not in after["models"]
    assert after["model_ready"] is False
    assert after["model_notice"] == "default_model_gone"
    assert "aigw:anthropic/claude-sonnet-5" in after["models"]  # what there is to choose from

    # Choosing clears the state.
    picked = mgr.set_default_model("aigw:anthropic/claude-sonnet-5")
    assert picked["model_ready"] is True and picked["model_notice"] is None


def test_a_dead_default_comes_back_if_the_administrator_reticks_it(tmp_path, monkeypatch):
    mgr = _mgr(
        tmp_path, monkeypatch, "anthropic/claude-sonnet-5", default="aigw:anthropic/claude-fable-5"
    )
    assert mgr.get_settings()["model_notice"] == "default_model_gone"
    _pull_ok(monkeypatch, "anthropic/claude-sonnet-5", "anthropic/claude-fable-5")
    mgr.refresh_model_catalog("aigw")
    back = mgr.get_settings()
    assert back["model_ready"] is True and back["model_notice"] is None
    assert back["models"][0] == "aigw:anthropic/claude-fable-5"


def test_an_unknown_list_does_not_declare_the_default_dead(tmp_path, monkeypatch):
    # Signed in, first pull not landed yet (or only ever failed): nothing is known, so no
    # alarm — the notice is for "a successful refresh says it is gone", nothing weaker.
    mgr = _mgr(tmp_path, monkeypatch, default="aigw:anthropic/claude-fable-5")
    s = mgr.get_settings()
    assert s["model_notice"] is None and s["model_ready"] is True
    # The default stays; no OTHER gateway model is offered without a list.
    assert [m for m in s["models"] if m.startswith("aigw:")] == ["aigw:anthropic/claude-fable-5"]


def test_only_a_gateway_default_can_be_gone(tmp_path, monkeypatch):
    mgr = _mgr(tmp_path, monkeypatch, "anthropic/claude-sonnet-5", default="anthropic:claude-fable-5")
    s = mgr.get_settings()
    assert s["model_notice"] is None
    assert s["models"][0] == "anthropic:claude-fable-5"


async def test_a_changed_list_tells_open_guis_to_reload_their_settings(tmp_path, monkeypatch):
    # Pulls mostly land on background threads (server start, the TTL refresh) while the
    # composer sits on whatever it loaded at startup. A list that actually changed — or a
    # default that just went dead — is pushed on the app-wide event stream; an identical
    # list is not, so an idle app does not reload settings on every refresh.
    mgr = _mgr(
        tmp_path,
        monkeypatch,
        "anthropic/claude-fable-5",
        "anthropic/claude-sonnet-5",
        default="aigw:anthropic/claude-fable-5",
    )
    mgr._loop = asyncio.get_running_loop()
    events: list[dict] = []

    async def client(message: dict) -> None:
        events.append(message)

    mgr.register_event_client(client)

    async def pull(*ids: str) -> None:
        _pull_ok(monkeypatch, *ids)
        await asyncio.to_thread(mgr.refresh_model_catalog, "aigw")  # off the loop, as in prod
        await asyncio.sleep(0.05)

    await pull("anthropic/claude-fable-5", "anthropic/claude-sonnet-5")  # same list
    assert events == []
    await pull("anthropic/claude-sonnet-5")  # Fable unticked → the default is gone
    assert events == [{"type": "models_changed"}]
    assert mgr.get_settings()["model_notice"] == "default_model_gone"
    await pull("anthropic/claude-sonnet-5")
    assert len(events) == 1


# -- the auto-title sibling ----------------------------------------------------------------
def test_the_utility_sibling_is_used_only_when_it_is_listed(tmp_path, monkeypatch):
    mgr = _mgr(tmp_path, monkeypatch, "anthropic/claude-fable-5", "anthropic/claude-haiku-5.5")
    assert mgr._utility_model("aigw:anthropic/claude-fable-5") == "aigw:anthropic/claude-haiku-5.5"

    # Haiku unticked: the session's own model titles its own session.
    mgr = _mgr(tmp_path / "b", monkeypatch, "anthropic/claude-fable-5", "openai/gpt-5.6-sol")
    assert mgr._utility_model("aigw:anthropic/claude-fable-5") == "aigw:anthropic/claude-fable-5"
    assert mgr._utility_model("aigw:openai/gpt-5.6-sol") == "aigw:openai/gpt-5.6-sol"

    # No list at all: the sibling is not known to be allowed either.
    mgr = _mgr(tmp_path / "c", monkeypatch)
    assert mgr._utility_model("aigw:anthropic/claude-fable-5") == "aigw:anthropic/claude-fable-5"

    # Other providers are not the gateway's business — their sibling stands.
    assert mgr._utility_model("anthropic:claude-opus-4-8") == "anthropic:claude-haiku-5-5"
    assert mgr._utility_model("gpt-5.6-sol") == "gpt-5.6-luna"
    assert mgr._utility_model("together:zai-org/GLM-5.2") == "together:zai-org/GLM-5.2"


# -- dynamic-route stand-ins -----------------------------------------------------------------
def test_route_allowed_needs_both_ends_on_the_list():
    opus, terra = "anthropic/claude-opus-5", "openai/gpt-5.6-terra"
    assert _ROUTES[opus].fallback == terra
    assert route_allowed(opus, {opus, terra}) is True
    assert route_allowed(f"aigw:{opus}", {opus, terra}) is True  # routed spelling too
    assert route_allowed(opus, {opus}) is False  # stand-in not ticked
    assert route_allowed(opus, {terra}) is False  # primary not ticked
    assert route_allowed(opus, None) is False  # no list
    assert route_allowed(opus, frozenset()) is False
    assert route_allowed("anthropic/claude-haiku-5.5", {"anthropic/claude-haiku-5.5"}) is False  # unrouted


def test_the_stand_in_badge_only_shows_for_routes_this_person_can_use(tmp_path, monkeypatch):
    monkeypatch.delenv("CLOUDFLARE_AIGW_DYNAMIC_ROUTING", raising=False)
    mgr = _mgr(
        tmp_path,
        monkeypatch,
        "anthropic/claude-opus-5",
        "anthropic/claude-sonnet-5",
        "anthropic/claude-fable-5",
        "openai/gpt-5.6-terra",
    )
    badges = mgr.get_settings()["model_fallbacks"]
    # opus → terra and sonnet → terra: both ends listed.
    assert badges["aigw:anthropic/claude-opus-5"] == "GPT-5.6 Terra · via Cloudflare"
    assert "aigw:anthropic/claude-sonnet-5" in badges
    # fable → gpt-5.6-sol: the stand-in is not on this person's list, so no promise.
    assert "aigw:anthropic/claude-fable-5" not in badges
    # No list → no badges at all.
    assert _mgr(tmp_path / "b", monkeypatch).get_settings()["model_fallbacks"] == {}


def test_the_manager_hands_the_gateway_provider_its_list_reader(tmp_path, monkeypatch):
    # The provider is built from a SecretStore profile and cannot see the catalog cache;
    # the router's `on_build` hook is how the list reaches its re-send gate.
    mgr = _mgr(tmp_path, monkeypatch, "anthropic/claude-opus-5")
    client = mgr.provider._client_for("aigw:anthropic/claude-opus-5")
    assert client._allowed_models() == frozenset({"anthropic/claude-opus-5"})
    assert client._route_allowed("anthropic/claude-opus-5") is False  # terra not listed
    _pull_ok(monkeypatch, "anthropic/claude-opus-5", "openai/gpt-5.6-terra")
    mgr.refresh_model_catalog("aigw")
    # Read at retry time, so a refreshed list applies without rebuilding the provider.
    assert client._route_allowed("anthropic/claude-opus-5") is True


# -- list prices and the "limited" tier reach the settings payload ---------------------------
# The guard's rows may carry `price_in` / `price_out` (USD per 1,000,000 tokens) and `tier`.
# They ride the same cached rows as the list itself and come out of `get_settings` as
# `model_prices` / `model_tiers`, keyed by the routed id — for gateway models only, and only
# for what the guard actually said.


def _priced(model_id: str, **extra) -> dict:
    return {
        "id": model_id,
        "label": f"{model_id} · via Cloudflare",
        "context_window": None,
        **extra,
    }


def _mgr_priced(tmp_path, monkeypatch, *rows: dict) -> SessionManager:
    mgr = _mgr(tmp_path, monkeypatch, *[r["id"] for r in rows])
    mgr._model_catalog["aigw"]["models"] = [dict(r) for r in rows]
    return mgr


def test_prices_and_tiers_reach_the_settings_payload(tmp_path, monkeypatch):
    mgr = _mgr_priced(
        tmp_path,
        monkeypatch,
        _priced("openai/gpt-6.1-sol", price_in=3.0, price_out=15.0, tier="limited"),
        _priced("google-ai-studio/gemini-3.7-flash", price_in=0.15, price_out=0.6, tier="all"),
        _priced("anthropic/claude-haiku-5.5", price_in=1.0),  # only one side priced
        _priced("openai/gpt-6-luna"),  # the guard listed no price
    )
    s = mgr.get_settings()
    assert s["model_prices"] == {
        "aigw:openai/gpt-6.1-sol": {"in": 3.0, "out": 15.0},
        "aigw:google-ai-studio/gemini-3.7-flash": {"in": 0.15, "out": 0.6},
        "aigw:anthropic/claude-haiku-5.5": {"in": 1.0},
    }
    # "all" is the unmarked case: only restricted models are named.
    assert s["model_tiers"] == {"aigw:openai/gpt-6.1-sol": "limited"}


def test_an_older_guard_yields_empty_price_and_tier_maps(tmp_path, monkeypatch):
    mgr = _mgr(tmp_path, monkeypatch, "anthropic/claude-sonnet-5", "openai/gpt-6-luna")
    s = mgr.get_settings()
    assert s["model_prices"] == {}
    assert s["model_tiers"] == {}
    # …and with no list at all.
    fresh = _mgr(tmp_path / "b", monkeypatch).get_settings()
    assert (fresh["model_prices"], fresh["model_tiers"]) == ({}, {})


def test_garbage_in_the_cached_rows_never_reaches_the_payload(tmp_path, monkeypatch):
    # The cache is a prefs file: rows written by an older build, or edited by hand, are
    # re-checked on the way out — a bad side is dropped, not shown and not guessed.
    mgr = _mgr_priced(
        tmp_path,
        monkeypatch,
        _priced("a/strings", price_in="3", price_out="15", tier="LIMITED"),
        _priced("a/negative", price_in=-3, price_out=15),
        _priced("a/bools", price_in=True, price_out=False, tier=True),
        _priced("a/nan", price_in=float("nan"), price_out=float("inf")),
        _priced("a/zero", price_in=0, price_out=0, tier="vip"),
    )
    s = mgr.get_settings()
    assert s["model_prices"] == {
        "aigw:a/negative": {"out": 15.0},
        "aigw:a/zero": {"in": 0.0, "out": 0.0},
    }
    assert s["model_tiers"] == {}


def test_prices_are_reported_for_gateway_models_only(tmp_path, monkeypatch):
    mgr = _mgr_priced(
        tmp_path,
        monkeypatch,
        _priced("openai/gpt-6.1-sol", price_in=3.0, price_out=15.0, tier="limited"),
    )
    # Another configured provider whose cached rows happen to carry the same keys (an
    # OpenRouter-style catalog, a hand-edited prefs file): not the guard, so not a price.
    mgr.secrets.put("provider:zai", {"api_key": "k"})
    mgr._model_catalog["zai"] = {
        "fetched_at": "2026-10-13T00:00:00+00:00",
        "models": [
            {
                "id": "glm-5.2",
                "label": "GLM-5.2 · Z AI",
                "context_window": None,
                "price_in": 1.0,
                "price_out": 2.0,
                "tier": "limited",
            }
        ],
        "error": None,
        "failed_at": None,
    }
    s = mgr.get_settings()
    assert "zai:glm-5.2" in s["model_labels"]  # the row itself is read…
    assert set(s["model_prices"]) == {"aigw:openai/gpt-6.1-sol"}  # …its "price" is not
    assert set(s["model_tiers"]) == {"aigw:openai/gpt-6.1-sol"}
    assert all(k.startswith("aigw:") for k in (*s["model_prices"], *s["model_tiers"]))


def test_a_signed_out_gateway_reports_no_prices(tmp_path, monkeypatch):
    mgr = _mgr_priced(
        tmp_path,
        monkeypatch,
        _priced("openai/gpt-6.1-sol", price_in=3.0, price_out=15.0, tier="limited"),
    )
    assert mgr.get_settings()["model_prices"]
    profile = dict(mgr.secrets.get("provider:aigw") or {})
    profile.pop("access_token", None)
    mgr.secrets.put("provider:aigw", profile)
    s = mgr.get_settings()
    assert (s["model_prices"], s["model_tiers"]) == ({}, {})


def test_a_pull_stores_prices_and_they_survive_a_restart(tmp_path, monkeypatch):
    mgr = _mgr(tmp_path, monkeypatch, "openai/gpt-6.1-sol")
    assert mgr.get_settings()["model_prices"] == {}
    _pull(
        monkeypatch,
        {
            "ok": True,
            "models": [
                _priced("openai/gpt-6.1-sol", price_in=3.0, price_out=15.0, tier="limited"),
                _priced("openai/gpt-6-luna"),
            ],
        },
    )
    mgr.refresh_model_catalog("aigw")
    expected = {"aigw:openai/gpt-6.1-sol": {"in": 3.0, "out": 15.0}}
    assert mgr.get_settings()["model_prices"] == expected
    reborn = SessionManager(data_dir=tmp_path / "data")
    s = reborn.get_settings()
    assert s["model_prices"] == expected
    assert s["model_tiers"] == {"aigw:openai/gpt-6.1-sol": "limited"}
    # A failed pull afterwards keeps the last list, prices included.
    _pull(monkeypatch, {"ok": False, "error": "boom"})
    mgr.refresh_model_catalog("aigw")
    assert mgr.get_settings()["model_prices"] == expected


async def test_new_prices_on_an_unchanged_list_tell_open_guis_to_reload(tmp_path, monkeypatch):
    # The day the guard starts sending prices (or an administrator re-prices / re-tiers a
    # model) the ids do not change at all — open composers must still hear about it.
    mgr = _mgr(tmp_path, monkeypatch, "openai/gpt-6.1-sol", "openai/gpt-6-luna")
    mgr._loop = asyncio.get_running_loop()
    events: list[dict] = []

    async def client(message: dict) -> None:
        events.append(message)

    mgr.register_event_client(client)

    async def pull(*rows: dict) -> None:
        _pull(monkeypatch, {"ok": True, "models": [dict(r) for r in rows]})
        await asyncio.to_thread(mgr.refresh_model_catalog, "aigw")
        await asyncio.sleep(0.05)

    plain = (_priced("openai/gpt-6.1-sol"), _priced("openai/gpt-6-luna"))
    priced = (
        _priced("openai/gpt-6.1-sol", price_in=3.0, price_out=15.0),
        _priced("openai/gpt-6-luna", price_in=0.2, price_out=1.0),
    )
    await pull(*plain)
    assert events == []
    await pull(*priced)  # same ids, prices appear
    assert len(events) == 1
    await pull(*priced)  # identical → quiet
    assert len(events) == 1
    await pull(priced[0] | {"tier": "limited"}, priced[1])  # a tier change alone
    assert len(events) == 2
    assert events[-1] == {"type": "models_changed"}
