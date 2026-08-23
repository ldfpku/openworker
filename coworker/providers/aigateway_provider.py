"""Cloudflare AI Gateway — one Cloudflare token, many vendors' models.

Cloudflare's AI REST API fronts OpenAI, Anthropic, xAI, DeepSeek, Alibaba, MiniMax,
Moonshot and Cloudflare's own Workers AI behind a single host, billed against the
account's prepaid AI Gateway credits (Unified Billing). For this fork that solves the
same problem the Gemini relay solves — mainland China cannot reach most vendors
directly — but for every vendor at once, and without handing each colleague a
per-vendor API key: they get one Cloudflare token, and the gateway's own dashboard
shows who spent what.

**Three wires, not one.** The endpoint family is OpenAI-shaped in name only; each
provider keeps its native request schema, verified against the live API 2026-08-23:

  anthropic/*   → POST {base}/v1/messages          Anthropic Messages
                  (OpenAI-style `{"type": "function"}` tools are rejected outright —
                   the gateway forwards `tools` to Anthropic unchanged)
  openai/*      → POST {base}/v1/responses         OpenAI Responses
                  (chat/completions answers "Invalid value at input" for the whole
                   GPT-5.6 family; Responses serves them fine)
  everything    → POST {base}/v1/chat/completions  OpenAI Chat Completions
  else            (deepseek, xai, alibaba, minimax, moonshotai, and @cf/… Workers AI)

Those are the three wires this app already speaks, so this module is a dispatcher over
the existing providers rather than a fourth implementation. Streaming and tool calling
were confirmed on all three.

**Model ids are the gateway's, verbatim** — `aigw:anthropic/claude-sonnet-4.6`, not the
vendor's own spelling. The author segment is what selects the wire, and Cloudflare's
spelling differs from the vendor's often enough (dots for dashes on Claude) that
translating would be a bug factory. See `matrix.py` for the curated set.

**HTTP 402 means two different things here**, and only the body says which: a model that
is genuinely off Unified Billing ("not available via unified billing"), or the shared
wholesale pool for that model simply being busy ("wholesale rate limit exceeded"). The
second is transient and the flagships hit it easily. `errors.py` keeps them apart; do not
conclude a model is unavailable from the status code alone.
"""

from __future__ import annotations

import os
from typing import Any, Optional

from .base import ModelCapabilities, ProviderClient
from .capabilities import capabilities_for

# The AI REST API lives under the account, not on gateway.ai.cloudflare.com. The older
# `/{gateway}/compat/chat/completions` host is documented as deprecated for single-model
# calls and is not a Unified Billing endpoint — it needs a provider key per request.
API_ROOT = "https://api.cloudflare.com/client/v4"

ENV_ACCOUNT_ID = "CLOUDFLARE_ACCOUNT_ID"
ENV_API_TOKEN = "CLOUDFLARE_API_TOKEN"
ENV_GATEWAY_ID = "CLOUDFLARE_AI_GATEWAY_ID"

# Cheapest text model in the Workers AI catalog — the Test button's one-token probe.
PROBE_MODEL = "@cf/meta/llama-3.2-1b-instruct"


def ai_base_url(account_id: str) -> str:
    """Root the Anthropic SDK wants: it appends `/v1/messages` itself."""
    return f"{API_ROOT}/accounts/{account_id.strip()}/ai"


def openai_base_url(account_id: str) -> str:
    """Root the OpenAI SDK wants: it appends `/chat/completions` or `/responses`."""
    return ai_base_url(account_id) + "/v1"


def gateway_headers(gateway_id: str) -> dict[str, str]:
    """`cf-aig-gateway-id` picks the gateway. Required for Workers AI models; without it
    third-party calls land in the account's auto-created `default` gateway, which has
    none of the caching, rate limiting, or spend rules configured on ours."""
    gid = (gateway_id or "").strip()
    return {"cf-aig-gateway-id": gid} if gid else {}


def resolve_settings(profile: dict[str, Any]) -> tuple[str, str, str]:
    """(account_id, api_token, gateway_id) from the stored profile, else the environment.

    Same precedence as every other provider — an explicitly saved value wins, and the env
    vars let a headless/CI run work without touching the SecretStore.
    """
    p = profile or {}

    def pick(key: str, env: str) -> str:
        return (str(p.get(key) or "").strip()) or os.environ.get(env, "").strip()

    return (
        pick("account_id", ENV_ACCOUNT_ID),
        pick("api_token", ENV_API_TOKEN),
        pick("gateway_id", ENV_GATEWAY_ID),
    )


def wire_for(model: str) -> str:
    """Which of the three request schemas this gateway model id needs.

    Keyed on the author segment, because that is what Cloudflare routes on. Workers AI
    ids (`@cf/zai-org/glm-5.2`) have `@cf` as their author and take Chat Completions,
    which is also the fallback for every author we have not special-cased.
    """
    author = model.split("/", 1)[0].strip().lower() if "/" in model else ""
    if author == "anthropic":
        return "messages"
    if author == "openai":
        return "responses"
    return "chat"


class AIGatewayProvider(ProviderClient):
    """Routes each model to the sub-client whose wire the gateway expects for it."""

    def __init__(
        self,
        *,
        account_id: str = "",
        api_token: str = "",
        gateway_id: str = "",
        thinking_budget: Optional[int] = None,
        clients: Optional[dict[str, ProviderClient]] = None,
    ):
        # Sub-clients are built eagerly (they are cheap dataclass-ish wrappers whose own SDK
        # clients stay lazy), so a missing credential surfaces on the first real call with
        # this provider's own message rather than OpenAI's. Tests inject `clients`.
        self._account_id = (account_id or "").strip()
        self._api_token = (api_token or "").strip()
        self._gateway_id = (gateway_id or "").strip()
        self._thinking_budget = thinking_budget
        self._clients: dict[str, ProviderClient] = dict(clients or {})

    def _build(self, wire: str) -> ProviderClient:
        if not self._account_id or not self._api_token:
            missing = "account ID" if not self._account_id else "API token"
            raise RuntimeError(
                f"Cloudflare AI Gateway is missing its {missing} — add it in "
                "Settings ▸ Models."
            )
        headers = gateway_headers(self._gateway_id)
        if wire == "messages":
            from .anthropic_provider import AnthropicProvider, DEFAULT_THINKING_BUDGET

            budget = (
                DEFAULT_THINKING_BUDGET
                if self._thinking_budget is None
                else self._thinking_budget
            )
            return AnthropicProvider(
                base_url=ai_base_url(self._account_id),
                auth_token=self._api_token,
                default_headers=headers,
                thinking_budget=budget,
                # Off here: the beta names its fallback by Anthropic's own model id
                # (`claude-opus-4-8`), which is not what the gateway calls that model
                # (`anthropic/claude-opus-4.8`), and whether the gateway serves the beta
                # endpoint at all is unverified. Consequence, since Fable 5 IS available
                # here: a safety-classifier refusal surfaces as an error instead of being
                # silently re-served on Opus, the way the direct Anthropic path does it.
                refusal_fallback=False,
            )
        if wire == "responses":
            from .openai_responses import OpenAIResponsesProvider

            return OpenAIResponsesProvider(
                api_key=self._api_token,
                base_url=openai_base_url(self._account_id),
                default_headers=headers,
            )
        from .openai_provider import OpenAIProvider

        return OpenAIProvider(
            api_key=self._api_token,
            base_url=openai_base_url(self._account_id),
            default_headers=headers,
        )

    def _client_for(self, model: str) -> ProviderClient:
        wire = wire_for(model)
        client = self._clients.get(wire)
        if client is None:
            client = self._build(wire)
            self._clients[wire] = client
        return client

    # -- ProviderClient ---------------------------------------------------------
    def complete(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: Optional[list[dict[str, Any]]] = None,
        **settings: Any,
    ):
        return self._client_for(model).complete(
            model=model, messages=messages, tools=tools, **settings
        )

    def stream(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: Optional[list[dict[str, Any]]] = None,
        **settings: Any,
    ):
        return self._client_for(model).stream(
            model=model, messages=messages, tools=tools, **settings
        )

    def capabilities(self, model: str) -> ModelCapabilities:
        # The router strips the `aigw:` prefix before delegating, but the matrix is keyed on
        # the full routed id — put it back so curated entries answer from the matrix.
        return capabilities_for(model if ":" in model else f"aigw:{model}")
