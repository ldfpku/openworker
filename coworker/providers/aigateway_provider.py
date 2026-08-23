"""Cloudflare AI Gateway — GPT, Claude and Gemini on one Access login.

The gateway sits on a custom domain of the company's own zone (`gateway.smjtools.com`)
with Cloudflare Access in front of it. That single choice decides everything else in this
module:

  * **No API token anywhere.** Access is the authentication. Cloudflare's own words:
    "The client does not need to send an AI Gateway token for that request." Each caller
    presents their personal Access session and nothing else — verified 2026-08-23, a
    request carrying only `cf-access-token` returns 200 with real billed cost. Colleagues
    therefore need no Cloudflare credential of their own, which is the whole point: an
    `AI Gateway Run` token cannot be scoped to one gateway, so per-person tokens would
    have bought an audit trail and no isolation at all.
  * **Spend is attributed per person for free.** Access stamps the authenticated user
    onto every request as `cf.user_id`, which drives the gateway's User Insights page and
    per-user spend limits. Nothing has to be passed from the client.
  * **Billing is the account's.** Third-party models are paid from the account's prepaid
    Unified Billing credits; no per-vendor key is stored on the gateway.

**Three wires, and the model id is spelled differently on each.** This is the part that
bites. Every path below was called live against the real gateway on 2026-08-23:

    author        wire         URL                              model sent upstream
    ───────────────────────────────────────────────────────────────────────────────
    anthropic/    messages     {base}/anthropic  (+ /v1/messages) prefix STRIPPED,
                                                                  vendor spelling
    openai/       responses    {base}/openai/v1  (+ /responses)   prefix STRIPPED
    everything    chat         {base}/compat (+ /chat/completions) prefix KEPT —
    else                                                          `/compat` requires it

`/compat` is a genuine OpenAI-compatible translation layer, not a router: OpenAI-shaped
`tools` go in and standard `tool_calls` come out even for Anthropic, and `stream: true`
returns ordinary SSE. It still cannot serve the GPT-5.6 tiers with tools, because OpenAI
itself refuses — "Function tools with reasoning_effort are not supported for gpt-5.6-sol
in /v1/chat/completions. To use function tools, use /v1/responses" — which is why the
`responses` wire exists rather than collapsing everything onto `/compat`.

**Vendor spelling, not Cloudflare's.** On this host the gateway forwards the model id to
the vendor untouched, so Anthropic wants dashes where Cloudflare's REST API writes dots:
`claude-haiku-4-5`, not `claude-haiku-4.5`. Anthropic says so itself — "model:
claude-sonnet-4.6 was not found. Did you mean claude-sonnet-4-6?". The matrix carries the
spelling that goes on the wire, so nothing here translates.

**The SDKs' placeholder credentials are harmless.** Both SDKs insist on *some* key and
will send `Authorization: Bearer …` / `x-api-key: …`; the gateway ignores them whenever
Unified Billing applies (checked with a deliberate junk value on all three wires).

**Reading a failure.** `errors.py` keeps the two meanings of 402 apart. Beyond that, the
gateway's own log is the source of truth: `GET /accounts/{id}/ai-gateway/gateways/{gw}/
logs` carries a `wholesale` field saying whether Unified Billing was applied to that
exact request, and a `cached` field — the gateway's response cache will happily replay a
previous answer and make a broken probe look healthy.
"""

from __future__ import annotations

import os
from typing import Any, Optional

from .base import ModelCapabilities, ProviderClient
from .capabilities import capabilities_for

ENV_BASE_URL = "CLOUDFLARE_AIGW_BASE_URL"
ENV_ACCESS_TOKEN = "CLOUDFLARE_AIGW_ACCESS_TOKEN"

# The Test button's probe. Cheap, and on the wire most likely to be misconfigured
# (`/compat`, where the provider prefix has to survive).
PROBE_MODEL = "anthropic/claude-haiku-4-5"

# Access takes the session in this header; `cloudflared access token` prints exactly what
# goes in it. Not `Authorization` — that slot belongs to the upstream vendor.
ACCESS_HEADER = "cf-access-token"

# Neither SDK will build a client without a credential, and the gateway ignores whatever
# is in that slot. Named so it is obvious in a packet capture that it means nothing.
_UNUSED_UPSTREAM_KEY = "unused-access-authenticates-this"

# Both SDKs default to a User-Agent of the form `OpenAI/Python 1.2.3` / `Anthropic/Python
# 1.2.3`, which Cloudflare's bot signatures classify as an AI crawler. On a zone with that
# protection on, every request dies at the edge as `403 Your request was blocked.` — long
# before Access, the gateway, or the model. Verified 2026-08-23: those two UAs 403 while
# `openworker/…`, `curl/8.0` and even a bare `OpenAI` all pass.
#
# Saying who we actually are is the honest fix as well as the working one — the caller is
# this app, not a generic SDK — and AI Gateway logs the user agent, so it doubles as
# "which client sent this" in the gateway's own records.
def _user_agent() -> str:
    from .. import __version__

    return f"openworker/{__version__}"

_WIRE_PATHS = {
    "messages": "/anthropic",
    "responses": "/openai/v1",
    "chat": "/compat",
}


def normalise_base(base_url: str) -> str:
    """Trim a pasted gateway URL down to its origin.

    People paste whatever the dashboard showed them, which may carry a path. Everything
    here is built by appending, so a stray `/compat` or trailing slash would produce
    `…/compat/compat/chat/completions` and a 404 nobody enjoys diagnosing.
    """
    url = (base_url or "").strip().rstrip("/")
    if not url:
        return ""
    if "://" not in url:
        url = "https://" + url
    scheme, _, rest = url.partition("://")
    host, _, _path = rest.partition("/")
    return f"{scheme}://{host}"


def wire_url(base_url: str, wire: str) -> str:
    """Base URL for one wire, in the form its SDK expects to append to."""
    return normalise_base(base_url) + _WIRE_PATHS[wire]


def access_headers(access_token: str) -> dict[str, str]:
    """Everything this provider adds to a request: the Access session, and a User-Agent
    that will not be mistaken for an AI crawler (see `_user_agent`)."""
    headers = {"User-Agent": _user_agent()}
    token = (access_token or "").strip()
    if token:
        headers[ACCESS_HEADER] = token
    return headers


def resolve_settings(profile: dict[str, Any]) -> tuple[str, str]:
    """(base_url, access_token) from the stored profile, else the environment.

    Same precedence as every other provider — an explicitly saved value wins, and the env
    vars let a headless/CI run work without touching the SecretStore.
    """
    p = profile or {}

    def pick(key: str, env: str) -> str:
        return (str(p.get(key) or "").strip()) or os.environ.get(env, "").strip()

    return (pick("base_url", ENV_BASE_URL), pick("access_token", ENV_ACCESS_TOKEN))


def wire_for(model: str) -> str:
    """Which of the three request schemas this gateway model id needs.

    Keyed on the author segment, because that is what the gateway routes on. Anything not
    special-cased takes Chat Completions on `/compat`, which is where Gemini lives
    (`google-ai-studio/…`) along with every other provider the gateway fronts.
    """
    author = model.split("/", 1)[0].strip().lower() if "/" in model else ""
    if author == "anthropic":
        return "messages"
    if author == "openai":
        return "responses"
    return "chat"


def upstream_model(model: str, wire: str) -> str:
    """The model id as the upstream endpoint wants to see it.

    The provider-native wires talk to the vendor's own API, which has never heard of
    Cloudflare's `author/` namespace and 404s on it. `/compat` is the opposite: the prefix
    is how it picks a provider, and without one it answers `2008 Invalid provider`.
    """
    if wire == "chat":
        return model
    _author, _, bare = model.partition("/")
    return bare or model


class AIGatewayProvider(ProviderClient):
    """Routes each model to the sub-client whose wire the gateway expects for it."""

    def __init__(
        self,
        *,
        base_url: str = "",
        access_token: str = "",
        thinking_budget: Optional[int] = None,
        clients: Optional[dict[str, ProviderClient]] = None,
    ):
        # Sub-clients are built lazily per wire (they are cheap wrappers whose own SDK
        # clients stay lazy too), so a missing setting surfaces on the first real call with
        # this provider's own message rather than OpenAI's. Tests inject `clients`.
        self._base_url = normalise_base(base_url)
        self._access_token = (access_token or "").strip()
        self._thinking_budget = thinking_budget
        self._clients: dict[str, ProviderClient] = dict(clients or {})

    def _build(self, wire: str) -> ProviderClient:
        if not self._base_url:
            raise RuntimeError(
                "Cloudflare AI Gateway is missing its gateway address — add it in "
                "Settings ▸ Models."
            )
        if not self._access_token:
            raise RuntimeError(
                "Cloudflare AI Gateway has no Access session — sign in again in "
                "Settings ▸ Models."
            )
        headers = access_headers(self._access_token)
        base = wire_url(self._base_url, wire)
        if wire == "messages":
            from .anthropic_provider import AnthropicProvider, DEFAULT_THINKING_BUDGET

            budget = (
                DEFAULT_THINKING_BUDGET
                if self._thinking_budget is None
                else self._thinking_budget
            )
            return AnthropicProvider(
                base_url=base,
                auth_token=_UNUSED_UPSTREAM_KEY,
                default_headers=headers,
                thinking_budget=budget,
                # Off here: the beta names its fallback by a bare Anthropic model id and
                # whether the gateway serves that beta endpoint at all is unverified.
                # Consequence, since Fable 5 IS available here: a safety-classifier refusal
                # surfaces as an error instead of being silently re-served on Opus, the way
                # the direct Anthropic path does it.
                refusal_fallback=False,
            )
        if wire == "responses":
            from .openai_responses import OpenAIResponsesProvider

            return OpenAIResponsesProvider(
                api_key=_UNUSED_UPSTREAM_KEY,
                base_url=base,
                default_headers=headers,
            )
        from .openai_provider import OpenAIProvider

        return OpenAIProvider(
            api_key=_UNUSED_UPSTREAM_KEY,
            base_url=base,
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
        wire = wire_for(model)
        return self._client_for(model).complete(
            model=upstream_model(model, wire), messages=messages, tools=tools, **settings
        )

    def stream(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: Optional[list[dict[str, Any]]] = None,
        **settings: Any,
    ):
        wire = wire_for(model)
        return self._client_for(model).stream(
            model=upstream_model(model, wire), messages=messages, tools=tools, **settings
        )

    def capabilities(self, model: str) -> ModelCapabilities:
        # The router strips the `aigw:` prefix before delegating, but the matrix is keyed on
        # the full routed id — put it back so curated entries answer from the matrix.
        return capabilities_for(model if ":" in model else f"aigw:{model}")
