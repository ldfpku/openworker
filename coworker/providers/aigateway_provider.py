"""Cloudflare AI Gateway — GPT, Claude and Gemini on one Access login.

The gateway sits on a custom domain of the company's own zone (`gateway.smjtools.com`)
with Cloudflare Access in front of it. That address is baked in as `DEFAULT_BASE_URL`
(owner call 2026-08-27: nothing to fill in, nothing to configure — signing in is the whole
setup), overridable per profile/env for a fork or a staging gateway. The custom-domain +
Access choice decides everything else in this module:

  * **No API token anywhere.** Access is the authentication. Cloudflare's own words:
    "The client does not need to send an AI Gateway token for that request." Each caller
    presents their personal Access session and nothing else — verified 2026-08-23, a
    request carrying only `cf-access-token` returns 200 with real billed cost. Colleagues
    therefore need no Cloudflare credential of their own, which is the whole point: an
    `AI Gateway Run` token cannot be scoped to one gateway, so per-person tokens would
    have bought an audit trail and no isolation at all. There are two ways to present
    that session, and this module treats them as equals: an OAuth bearer obtained by
    signing in (`aigw_auth`, renews itself, nothing to paste) or a `cloudflared`-printed
    JWT typed into Settings (lapses daily). The former wins when both are present.
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

import logging
import os
import re
from typing import Any, Callable, Iterable, NamedTuple, Optional

from ..compaction import estimate_tokens
from .base import ModelCapabilities, ProviderClient
from .capabilities import capabilities_for
from .errors import is_gateway_busy
from .matrix import MATRIX

logger = logging.getLogger(__name__)

ENV_BASE_URL = "CLOUDFLARE_AIGW_BASE_URL"
ENV_ACCESS_TOKEN = "CLOUDFLARE_AIGW_ACCESS_TOKEN"
# Rollback switch for the dynamic-routing retry below (`0`/`off`/`false`/`no` turn it
# off). Env-only on purpose, same shape as `ENV_BASE_URL`: this is an operational escape
# hatch for the day a Cloudflare-side route is broken or deleted, not a preference —
# nothing in Settings should invite people to toggle it.
ENV_DYNAMIC_ROUTING = "CLOUDFLARE_AIGW_DYNAMIC_ROUTING"

# The company gateway, the address of last resort in `resolve_settings` — which is what
# lets the settings pane drop the address field entirely. Publishing the host is fine:
# it is Access-protected (an anonymous visitor gets a login page) and, unlike the
# `gateway.ai.cloudflare.com/v1/{account}/...` form, carries no account id — that stays
# out of this public fork.
DEFAULT_BASE_URL = "https://gateway.smjtools.com"

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


def bearer_headers(token: str) -> dict[str, str]:
    """The same, for an OAuth session from `aigw_auth`.

    Managed OAuth asks for its token in the slot its own challenge names —
    `WWW-Authenticate: Bearer realm="OAuth"` — which is a different header from the pasted
    JWT's `cf-access-token`. Access accepts either (both verified against the live gateway
    on 2026-08-23, on all three wires and with no vendor credential present at all), so
    each credential simply travels where its own protocol says it should.
    """
    headers = {"User-Agent": _user_agent()}
    value = (token or "").strip()
    if value:
        headers["Authorization"] = f"Bearer {value}"
    return headers


def resolve_settings(profile: dict[str, Any]) -> tuple[str, str]:
    """(base_url, access_token) from the stored profile, else the environment, else — for
    the address only — the built-in company gateway.

    Same precedence as every other provider — an explicitly saved value wins, and the env
    vars let a headless/CI run work without touching the SecretStore. The
    `DEFAULT_BASE_URL` tail is what makes a fresh install zero-config: sign in and go.
    """
    p = profile or {}

    def pick(key: str, env: str) -> str:
        return (str(p.get(key) or "").strip()) or os.environ.get(env, "").strip()

    return (
        pick("base_url", ENV_BASE_URL) or DEFAULT_BASE_URL,
        pick("access_token", ENV_ACCESS_TOKEN),
    )


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


class _Route(NamedTuple):
    """One Cloudflare Dynamic Route, from this client's point of view."""

    name: str  # the route id on the gateway — sent as `dynamic/<name>` on `/compat`
    fallback: str  # the same-tier stand-in that route falls back to, gateway id


# Model → its dynamic route, for the handful of models the shared wholesale pool actually
# rate-limits. A Dynamic Route is a tiny graph on the gateway (start → primary model →
# fallback model → end); addressing it means POSTing `model: "dynamic/<name>"` to
# `/compat`, and the gateway picks the live one. Cloudflare's fallback edge fires on
# "error or timeout" only — it cannot be told "429 specifically" — which is why the
# decision to reach for a route at all is made HERE, on a 429/402-busy body, rather than
# routing every request through the graph and losing the provider-native wires.
#
# Two rules the table has to keep:
#   * **Same tier, and never up.** A fallback must not be a model the guard restricts more
#     tightly than the primary, or a 429 would quietly hand someone a model they are not
#     cleared for. Today's restricted set is exactly {claude-fable-5, gpt-5.6-sol}, and
#     each of those is only ever a fallback for a peer that is itself restricted.
#   * **It mirrors gateway-guard's `ROUTE_MODELS`.** The guard has to resolve
#     `dynamic/<name>` back to BOTH endpoints to keep the gate honest; the two tables ship
#     together or the gate is bypassable.
#
# Not routed: the utility tier (haiku / luna — the limiter never fires there) and every
# `google-ai-studio/*` id, which reaches `/compat` unchanged.
_ROUTES: dict[str, _Route] = {
    "anthropic/claude-fable-5": _Route(
        "ow-anthropic-claude-fable-5", "openai/gpt-5.6-sol"
    ),
    "openai/gpt-5.6-sol": _Route("ow-openai-gpt-5-6-sol", "anthropic/claude-opus-5"),
    "anthropic/claude-opus-5": _Route(
        "ow-anthropic-claude-opus-5", "openai/gpt-5.6-terra"
    ),
    "anthropic/claude-sonnet-5": _Route(
        "ow-anthropic-claude-sonnet-5", "openai/gpt-5.6-terra"
    ),
    "openai/gpt-5.6-terra": _Route(
        "ow-openai-gpt-5-6-terra", "anthropic/claude-sonnet-5"
    ),
}


def _bare_gateway_id(model: str) -> str:
    """`aigw:anthropic/claude-opus-5` / `anthropic/claude-opus-5` → the latter, lowercased.

    The provider is handed the bare gateway id (the router strips `aigw:`), but the matrix
    and everything shipped to the GUI are keyed on the routed id — so both spellings reach
    the lookups below.
    """
    ident = (model or "").strip().lower()
    return ident[len("aigw:") :] if ident.startswith("aigw:") else ident


def route_for(model: str) -> Optional[str]:
    """The dynamic route serving this model, or None when it has no stand-in.

    Pure table lookup — the rollback switch is checked separately by the caller
    (`dynamic_routing_enabled`), so this stays usable for "does a stand-in exist at all"
    questions like the picker badge.
    """
    entry = _ROUTES.get(_bare_gateway_id(model))
    return entry.name if entry else None


def fallback_for(model: str) -> Optional[str]:
    """The same-tier stand-in this model's route falls back to (gateway id), or None."""
    entry = _ROUTES.get(_bare_gateway_id(model))
    return entry.fallback if entry else None


def dynamic_routing_enabled() -> bool:
    """False only when the env switch says so — absent means on."""
    raw = os.environ.get(ENV_DYNAMIC_ROUTING, "").strip().lower()
    return raw not in ("0", "off", "false", "no")


# How full the stand-in's window a turn may be before a re-send stops being worth trying.
# `estimate_tokens` counts the outbound prompt only — the reply needs room too — and it is
# a chars/4 approximation that runs light on CJK text. 10% covers both.
_STAND_IN_HEADROOM = 0.9


def context_window(model: str) -> Optional[int]:
    """The matrix's context window for a gateway id, or None when it carries no number."""
    entry = MATRIX.get(f"aigw:{_bare_gateway_id(model)}")
    return entry.context_window if entry else None


def fits_the_stand_in(route: _Route, messages: list[dict[str, Any]]) -> bool:
    """Would the stand-in even accept this turn?

    **Same tier does not mean same window.** `claude-opus-5` and `claude-sonnet-5` carry
    1,000,000 and both fail over to `gpt-5.6-terra`, whose 400,000 is smaller *and* is
    itself the one unverified number in the table. Re-sending a turn that cannot fit buys
    a guaranteed second failure, and — because `complete`/`stream` deliberately surface
    the ORIGINAL 429 when the route fails too — the user would be told "the shared pool is
    busy" about a context overflow. Better to let the 429 stand: it is at least the error
    that actually happened first.

    Auto-compaction normally keeps a turn far below this (it fires at
    min(0.8 × window, 250k)), so this is a backstop for what it does not catch: one
    uncompacted tool loop, a giant paste, a window shrunk by a matrix correction.

    No matrix number for the stand-in → no ceiling to test against, so allow the re-send;
    inventing a limit would be the worse guess.
    """
    window = context_window(route.fallback)
    if not window:
        return True
    return estimate_tokens(messages) <= int(window * _STAND_IN_HEADROOM)


def fetch_gate_policy(
    fields: dict[str, Any], timeout: float = 5.0
) -> Optional[dict[str, Any]]:
    """Best-effort read of the guard Worker's per-user gate: `GET {base}/gate/policy`.

    The company gateway's guard (gateway-guard, smj-help-website repo) restricts some
    models to certain roles and answers this endpoint with
    `{"email", "role", "active", "blocked": ["author/model", ...], "enforce"}` for the
    signed-in caller. The picker uses `blocked` to hide those models up front instead of
    letting people select one and hit the guard's 403.

    Returns the parsed dict on a well-shaped 200, else None — the guard may not be
    deployed yet (this endpoint 404s on the bare AI Gateway custom domain), the user may
    be signed out, or the network may be down. None means "don't filter"; enforcement is
    server-side either way, so this can never be a security hole, only a cosmetic miss.

    `fields` is the stored provider profile plus an optional `oauth_token` the caller
    injects — the same contract as the Test probe (`registry._verify_aigw`).
    """
    import httpx

    base_url, access_token = resolve_settings(fields or {})
    oauth_token = str((fields or {}).get("oauth_token") or "").strip()
    if not oauth_token and not access_token:
        return None
    headers = bearer_headers(oauth_token) if oauth_token else access_headers(access_token)
    try:
        resp = httpx.get(
            normalise_base(base_url) + "/gate/policy", headers=headers, timeout=timeout
        )
    except Exception:  # noqa: BLE001 - cosmetic feature, never let it surface
        logger.debug("aigw: gate policy fetch failed", exc_info=True)
        return None
    if resp.status_code != 200:
        return None
    try:
        data = resp.json()
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(data, dict) or not isinstance(data.get("blocked"), list):
        return None
    return data


def blocked_model_ids(policy: Optional[dict[str, Any]]) -> frozenset[str]:
    """`fetch_gate_policy` result → normalized bare ids ("author/model", lowercase).
    None / malformed → empty set (no filtering)."""
    if not policy:
        return frozenset()
    blocked = policy.get("blocked")
    if not isinstance(blocked, list):
        return frozenset()
    return frozenset(
        str(m).strip().lower() for m in blocked if isinstance(m, str) and str(m).strip()
    )


# A blocked base id also covers its dated/tagged variants — the same shape
# gateway-guard's canonicalModels() strips server-side before its own equality check.
# Keep this pattern text-identical to that one.
_VARIANT_SUFFIX_RE = re.compile(r"^(?:-\d{8}|-latest|@\d{8})?(?::batch|:beta)?$")


def is_blocked_model(model_id: str, blocked: Iterable[str]) -> bool:
    """True when `model_id` — a bare "author/model" id, or one prefixed "aigw:" — is
    exactly one of `blocked`'s entries, or a known dated/tagged variant of one: same
    base id followed by an optional `-YYYYMMDD` / `-latest` / `@YYYYMMDD` date suffix
    and an optional `:batch` / `:beta` tag suffix, in that order. Mirrors the server's
    matching exactly so the picker hides what the gateway would 403 on anyway — a miss
    here is only ever cosmetic, enforcement stays server-side.

    Deliberately NOT a regex built from `r`: `r` is untrusted-shaped free text from the
    gate policy response, so it is compared with plain string ops (`==`, `startswith`)
    and only the fixed, pre-compiled suffix pattern above is ever matched against.
    """
    m = str(model_id or "").strip().lower()
    if m.startswith("aigw:"):
        m = m[len("aigw:") :]
    if not m:
        return False
    for r in blocked:
        r = str(r or "").strip().lower()
        if not r:
            continue  # an empty blocked entry must never match everything
        if m == r:
            return True
        if m.startswith(r) and _VARIANT_SUFFIX_RE.match(m[len(r) :]):
            return True
    return False


class AIGatewayProvider(ProviderClient):
    """Routes each model to the sub-client whose wire the gateway expects for it."""

    def __init__(
        self,
        *,
        base_url: str = "",
        access_token: str = "",
        token_provider: Optional[Callable[[], str]] = None,
        thinking_budget: Optional[int] = None,
        clients: Optional[dict[str, ProviderClient]] = None,
    ):
        # Sub-clients are built lazily per wire (they are cheap wrappers whose own SDK
        # clients stay lazy too), so a missing setting surfaces on the first real call with
        # this provider's own message rather than OpenAI's. Tests inject `clients`.
        self._base_url = normalise_base(base_url)
        self._access_token = (access_token or "").strip()
        # Asked once per request for the current OAuth bearer, so a silent refresh takes
        # effect immediately. Returns "" when nobody has signed in, which is why the
        # pasted session below stays a live fallback rather than being replaced.
        self._token_provider = token_provider
        self._thinking_budget = thinking_budget
        self._clients: dict[str, ProviderClient] = dict(clients or {})
        # Injected sub-clients belong to the caller (tests): never evict them on rotation.
        self._injected = set(self._clients)
        self._built_with: Optional[str] = None

    def _credential(self) -> tuple[str, str]:
        """`(kind, value)` for this moment — `bearer` for an OAuth session, `session` for
        a pasted JWT, `("", "")` when neither is set up.

        OAuth wins when present because it is the one that renews itself; a pasted session
        left over from the old flow keeps working until it lapses.
        """
        if self._token_provider is not None:
            try:
                token = (self._token_provider() or "").strip()
            except Exception:  # noqa: BLE001 - a broken sign-in must not mask the paste
                logger.debug("aigw: token provider failed", exc_info=True)
                token = ""
            if token:
                return ("bearer", token)
        if self._access_token:
            return ("session", self._access_token)
        return ("", "")

    def _build(self, wire: str, kind: str, credential: str) -> ProviderClient:
        if not self._base_url:
            raise RuntimeError(
                "Cloudflare AI Gateway is missing its gateway address — add it in "
                "Settings ▸ Models."
            )
        if not credential:
            raise RuntimeError(
                "Cloudflare AI Gateway is not signed in — open Settings ▸ Models and "
                "press Sign in."
            )
        headers = bearer_headers(credential) if kind == "bearer" else access_headers(
            credential
        )
        base = wire_url(self._base_url, wire)
        if wire == "messages":
            from .anthropic_provider import AnthropicProvider, DEFAULT_THINKING_BUDGET

            budget = (
                DEFAULT_THINKING_BUDGET
                if self._thinking_budget is None
                else self._thinking_budget
            )
            # `auth_token` makes the SDK claim `Authorization: Bearer` for its own
            # placeholder — the very slot an OAuth session needs. Handing it `api_key`
            # instead moves the placeholder to `x-api-key` (equally ignored under Unified
            # Billing) and leaves `Authorization` to Access, so nothing depends on which
            # of the two headers the SDK happens to merge last.
            upstream = (
                {"api_key": _UNUSED_UPSTREAM_KEY}
                if kind == "bearer"
                else {"auth_token": _UNUSED_UPSTREAM_KEY}
            )
            return AnthropicProvider(
                base_url=base,
                **upstream,
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
        return self._client_for_wire(wire_for(model))

    def _client_for_wire(self, wire: str) -> ProviderClient:
        # Keyed on the wire rather than the model so the dynamic-routing retry can ask for
        # the `chat` sub-client directly: `dynamic/<route>` is not a model id anything
        # should be running `wire_for` on, it is an address on `/compat`.
        #
        # Resolved once per call and threaded into `_build`: asking twice would double
        # every silent-refresh check on the request path.
        kind, credential = self._credential()
        if self._token_provider is not None:
            # The credential is baked into each sub-client's default headers at build
            # time, so a silent refresh has to invalidate them or every later call would
            # keep presenting the expired bearer. Rebuilding is cheap — these are lazy
            # wrappers — and only happens on the ~15-minute refresh boundary.
            stamp = f"{kind}:{credential}"
            if stamp != self._built_with:
                self._clients = {
                    w: c for w, c in self._clients.items() if w in self._injected
                }
                self._built_with = stamp
        client = self._clients.get(wire)
        if client is None:
            client = self._build(wire, kind, credential)
            self._clients[wire] = client
        return client

    # -- dynamic routing --------------------------------------------------------
    def _retry_route(
        self, model: str, exc: Exception, messages: list[dict[str, Any]]
    ) -> Optional[_Route]:
        """The route to re-send this failed call on, or None to let the error stand.

        Two gates, both of which mean "a second request would fail too, so don't pay for
        it":

        * Only "the shared pool is busy right now" earns a re-send (`is_gateway_busy`
          covers both spellings — the 429 `Wholesale Rate limited` body and the older 402
          `wholesale rate limit exceeded`). A bad id, a restricted model, an
          out-of-credits account would all fail identically on the stand-in.
        * The turn has to fit the stand-in's context window (`fits_the_stand_in`) — the
          two 1M Claude tiers fail over to a 400k model.
        """
        if not dynamic_routing_enabled() or not is_gateway_busy(exc):
            return None
        route = _ROUTES.get(_bare_gateway_id(model))
        if route is None:
            return None
        if not fits_the_stand_in(route, messages):
            logger.warning(
                "aigw: %s is rate-limited, but this turn (~%d tokens) does not fit the "
                "stand-in %s (window %s) — letting the 429 stand rather than re-sending",
                model,
                estimate_tokens(messages),
                route.fallback,
                context_window(route.fallback),
            )
            return None
        return route

    @staticmethod
    def _retry_settings(
        model: str, route: _Route, settings: dict[str, Any]
    ) -> dict[str, Any]:
        """Settings for the re-send, which always goes out on `/compat`.

        `openai_provider._pin_reasoning_effort` pins effort to `none` for `gpt-5.6*` ids
        because Chat Completions refuses function tools at any other effort — and it
        matches on the model string, which is now `dynamic/ow-…` and misses. So pin it
        here instead.

        Pinned when EITHER end of the route is an OpenAI tier, because the whole point of
        a route is that the client does not know which end answers. Half the table is
        Anthropic-primary with an OpenAI stand-in (`claude-opus-5` → `gpt-5.6-terra`); if
        this only looked at the primary, those re-sends would reach Chat Completions
        unpinned and lean on `openai_provider`'s `_param_fix_retry` to self-heal — correct
        in the end, but at the cost of a third round-trip on a turn that is already two
        requests deep.

        Sending it the other way (an Anthropic end receiving `reasoning_effort`) is the
        risk this accepts in exchange: `/compat` is a translation layer and only forwards
        what the vendor schema knows. That assumption was already load-bearing for the
        OpenAI-primary half of the table and is unchanged here — confirm it in the
        gateway's Logs the first time a real 429 exercises a route.

        `max_tokens` → `max_completion_tokens`, UNCONDITIONALLY (every route, not just the
        OpenAI-primary half). `openai_provider.complete`/`stream` default
        `kwargs.setdefault("max_tokens", DEFAULT_MAX_TOKENS)`, and gpt-5.6 on Chat
        Completions rejects that field outright — `400 unsupported_parameter: max_tokens
        is not supported with this model. Use 'max_completion_tokens' instead.` — for
        BOTH routes whose primary is an OpenAI tier (`ow-openai-gpt-5-6-sol`,
        `ow-openai-gpt-5-6-terra`). Cloudflare's fallback edge only fires on error/timeout
        — it cannot see "429 vs 400" — so that 400 just falls through to the route's
        Anthropic stand-in, which answers 200. The caller never learns their primary was
        never actually retried; only the response's `cf-aig-step`/model headers would show
        it, and nothing here reads those. Verified live 2026-09-16: an anthropic/* gateway
        id given `max_completion_tokens` alone (no `max_tokens`) still returns 200 with a
        real `usage.completion_tokens`, i.e. `/compat` accepts the renamed field for every
        author it fronts — so renaming for Anthropic-primary routes too is safe, not just
        tolerated, and keeps one code path instead of branching on which end is OpenAI.
        """
        out = dict(settings)
        if wire_for(model) == "responses" or wire_for(route.fallback) == "responses":
            out.setdefault("reasoning_effort", "none")
        if "max_tokens" in out:
            out["max_completion_tokens"] = out.pop("max_tokens")
        else:
            from .openai_provider import DEFAULT_MAX_TOKENS

            out.setdefault("max_completion_tokens", DEFAULT_MAX_TOKENS)
        return out

    @staticmethod
    def _mark_route(exc: Exception, route: _Route) -> None:
        """Tag the error with the route that was tried, for `errors.friendly_model_error`.

        Best-effort: an exception type that refuses attributes just stays untagged and the
        message falls back to its routeless wording.
        """
        try:
            exc.aigw_route = route.name  # type: ignore[attr-defined]
            exc.aigw_fallback = route.fallback  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 - cosmetic; never mask the real failure
            logger.debug("aigw: could not tag %r with its route", type(exc).__name__)

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
        try:
            return self._client_for(model).complete(
                model=upstream_model(model, wire),
                messages=messages,
                tools=tools,
                **settings,
            )
        except Exception as exc:
            route = self._retry_route(model, exc, messages)
            if route is None:
                raise
            logger.warning(
                "aigw: %s is rate-limited, retrying on route %s (stand-in %s)",
                model,
                route.name,
                route.fallback,
            )
            try:
                return self._client_for_wire("chat").complete(
                    model=f"dynamic/{route.name}",
                    messages=messages,
                    tools=tools,
                    **self._retry_settings(model, route, settings),
                )
            except Exception:  # noqa: BLE001 - the ORIGINAL error is the true diagnosis
                # Re-raise the 429, not whatever the route answered: a missing route or a
                # busy stand-in both mean "the tier is unavailable right now", and only
                # the original body carries the marker `errors.py` reads.
                self._mark_route(exc, route)
                raise exc

    def stream(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: Optional[list[dict[str, Any]]] = None,
        **settings: Any,
    ):
        """Generator, deliberately — this used to hand the sub-client's iterator straight
        back, which meant the SDK call (and its exception) happened at `stream()` call
        time. Retrying needs to catch that exception, so the whole thing moved inside a
        generator body and now raises on the first `next()` instead.

        The one consumer that matters, `engine._astream`'s producer thread, calls and
        iterates inside the same `try`, so the move is invisible there; `router.stream`
        only passes the iterator along.

        A re-send is only honest before the first chunk has been handed out: once the
        caller has seen text, replaying the turn on another model would duplicate it.

        **Known limitation, accepted.** If the *re-send* dies after emitting some of its
        own chunks, the caller keeps the partial text and still gets the original 429 —
        so the message says "the same-tier stand-in was busy too" even when the route's
        real failure was something else (a network blip, the stand-in's own limiter). The
        alternative is a second diagnosis that contradicts the text already on screen; the
        gateway's Logs are where a mid-stream route failure is actually diagnosed.

        This wrapper does its own stream closing nowhere on purpose: GeneratorExit (thrown
        in when a caller stops iterating, e.g. engine._astream breaking on Stop) is a
        BaseException, so `except Exception` below never sees it — it propagates straight
        through this frame and into whichever sub-client `.stream()` generator is
        currently suspended on `yield event`. Unwinding this frame drops that generator's
        only reference, which finalizes (closes) it immediately, and it is that inner
        generator's own try/finally — present on every provider that holds a real SDK
        stream — that actually closes the underlying connection.
        """
        wire = wire_for(model)
        started = False
        retry: Optional[_Route] = None
        first_error: Exception = RuntimeError("unreachable")
        try:
            for event in self._client_for(model).stream(
                model=upstream_model(model, wire),
                messages=messages,
                tools=tools,
                **settings,
            ):
                started = True
                yield event
        except Exception as exc:
            route = None if started else self._retry_route(model, exc, messages)
            if route is None:
                raise
            logger.warning(
                "aigw: %s is rate-limited mid-stream (nothing emitted yet), retrying on "
                "route %s (stand-in %s)",
                model,
                route.name,
                route.fallback,
            )
            retry = route
            first_error = exc
        if retry is None:
            return
        try:
            for event in self._client_for_wire("chat").stream(
                model=f"dynamic/{retry.name}",
                messages=messages,
                tools=tools,
                **self._retry_settings(model, retry, settings),
            ):
                yield event
        except Exception:  # noqa: BLE001 - same contract as `complete`
            # Including when the route had already emitted chunks of its own — see the
            # "known limitation" note above.
            self._mark_route(first_error, retry)
            raise first_error

    def capabilities(self, model: str) -> ModelCapabilities:
        # The router strips the `aigw:` prefix before delegating, but the matrix is keyed on
        # the full routed id — put it back so curated entries answer from the matrix.
        return capabilities_for(model if ":" in model else f"aigw:{model}")
