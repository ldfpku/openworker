"""Model-provider registry — descriptors + a factory, mirroring the connector
(`connectors/descriptors.py`) and web-search (`web/providers.py`) patterns.

A `ProviderDescriptor` declares a provider's UI config `fields` (rendered dynamically by the
GUI, same `to_dict()` shape connectors use) and a `build(profile, secrets)` factory that returns
a `ProviderClient`. The `ProviderRouter` selects a descriptor by the `provider:` prefix of a
model string and builds (and caches) its client from the matching SecretStore profile.

Today: `openai` (the default — native models via the Responses API; an optional custom
endpoint covering Azure OpenAI's `/openai/v1` and any OpenAI-compliant gateway keeps the
Chat Completions path), `anthropic` (native Messages API via
`AnthropicProvider`), `gemini` (native Google GenAI API via `GeminiProvider`), `bedrock`
(models in the user's own AWS account — Claude natively, everything else via Converse),
`vertex` (the user's own GCP project — Gemini and Claude natively, open-weight via the
MaaS endpoint), `aigw` (Cloudflare AI Gateway — many vendors on one work-account sign-in,
address baked in, `aigateway_provider.py`), `ollama` (local, OpenAI-compatible `/v1`), and
`custom` (one user-named OpenAI-compatible endpoint — the escape hatch for anything not
listed above; single instance, see its descriptor's comment for why).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from .aigateway_provider import (
    AIGatewayProvider,
    access_headers,
    bearer_headers,
    normalise_base,
    resolve_settings,
    wire_url,
)
from .anthropic_provider import AnthropicProvider
from .base import ProviderClient
from .bedrock_provider import BedrockProvider
from .gemini_provider import GeminiProvider, RELAY_TOKEN_PREFIX, resolve_base_url
from .openai_provider import OpenAIProvider
from .openai_responses import OpenAIResponsesProvider
from .vertex_provider import VertexProvider

logger = logging.getLogger(__name__)

DEFAULT_OLLAMA_URL = "http://localhost:11434"
RETIRED_PROVIDERS = frozenset({"nvidia"})


def retired_provider_error(name: str) -> str:
    return f"Provider '{name}' is no longer available. Select a model from AI Gateway or another provider."


@dataclass(frozen=True)
class ProviderField:
    """One config input for a provider, rendered by the GUI (mirrors connectors' `Field`)."""

    key: str
    label: str
    secret: bool = False
    required: bool = True
    help: str = ""
    placeholder: str = ""
    # Pre-filled (still editable) form value — e.g. an OpenAI-compatible vendor's official
    # endpoint, so the user only has to paste a key. Distinct from `placeholder` (grey hint).
    default: str = ""
    # Non-empty → the field renders as a segmented choice control instead of a text input;
    # each option is {"value", "label"} plus optional UI extras: "tag" (a tiny badge like
    # "Easiest"), "desc" (one-liner atop the method's panel), and "command" (a copyable
    # terminal command shown in the panel, e.g. the gcloud ADC login). The chosen value is
    # stored like any other field value.
    choices: tuple = ()
    # {"other_field_key": "value"} → the field only renders while that other field holds
    # that value. Drives auth-method switching (Bedrock) without a per-provider form.
    show_when: Optional[dict] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "secret": self.secret,
            "required": self.required,
            "help": self.help,
            "placeholder": self.placeholder,
            "default": self.default,
            "choices": [dict(c) for c in self.choices],
            "show_when": self.show_when,
        }


@dataclass(frozen=True)
class ProviderDescriptor:
    """A model provider: its UI fields + a factory that builds its `ProviderClient`."""

    name: str
    title: str
    needs_key: bool
    fields: list[ProviderField]
    build: Callable[[dict[str, Any], Any], ProviderClient] = field(repr=False)
    recommended_model: Optional[str] = (
        None  # pre-filled in the UI; auto-added on configure
    )
    env_key: Optional[str] = (
        None  # env var that can supply the API key (e.g. ANTHROPIC_API_KEY)
    )
    # One-line note under the provider title (e.g. "Connects through X's OpenAI-compatible API").
    blurb: str = ""
    # "oauth" → no key form at all: the provider is configured by a browser sign-in
    # (tokens in its `provider:<name>` profile) and the GUI renders connect/sign-out
    # instead of fields. None → the usual key/field form.
    auth: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "title": self.title,
            "needs_key": self.needs_key,
            "fields": [f.to_dict() for f in self.fields],
            "recommended_model": self.recommended_model,
            "blurb": self.blurb,
            "auth": self.auth,
        }


def _normalize_ollama_url(url: Optional[str]) -> str:
    """Accept `http://host:11434` or `.../v1` and return an OpenAI-compatible base URL.

    Ollama serves its OpenAI-compatible API under `/v1`; the native API lives at the root, so we
    always target `<root>/v1`.
    """
    base = (url or DEFAULT_OLLAMA_URL).strip().rstrip("/")
    if not base:
        base = DEFAULT_OLLAMA_URL
    if not base.endswith("/v1"):
        base = base + "/v1"
    return base


def _build_openai(profile: dict[str, Any], secrets: Any) -> ProviderClient:
    # Key resolution stays in resolve_api_key (explicit → env → SecretStore), so we just
    # hand over the SecretStore. Stock OpenAI (no custom endpoint) speaks the Responses
    # API — the only wire with reasoning + tools on GPT-5.6+. A custom endpoint (Azure
    # OpenAI /openai/v1, vLLM, any OpenAI-compliant gateway) keeps Chat Completions,
    # which is what compat servers implement.
    base_url = ((profile or {}).get("base_url") or "").strip() or None
    if base_url:
        return OpenAIProvider(secrets=secrets, base_url=base_url)
    return OpenAIResponsesProvider(secrets=secrets)


def _build_codex(profile: dict[str, Any], secrets: Any) -> ProviderClient:
    # Credentials come from the OAuth token set in the provider's own profile,
    # resolved (and refreshed) at call time by the token store — never a key.
    from .codex_provider import CodexProvider

    return CodexProvider(secrets=secrets)


def _build_anthropic(profile: dict[str, Any], secrets: Any) -> ProviderClient:
    # Key resolution stays in AnthropicProvider/resolve_api_key (explicit → env → SecretStore),
    # deferred to first call so the provider can be built before a key exists.
    # thinking_budget: hidden profile override — absent/invalid → the default (ON),
    # explicit 0 → off (see DEFAULT_THINKING_BUDGET).
    from .anthropic_provider import DEFAULT_THINKING_BUDGET

    api_key = ((profile or {}).get("api_key") or "").strip() or None
    try:
        thinking_budget = int(str((profile or {}).get("thinking_budget") or "").strip())
    except ValueError:
        thinking_budget = DEFAULT_THINKING_BUDGET
    return AnthropicProvider(
        api_key=api_key, secrets=secrets, thinking_budget=thinking_budget
    )


def _build_gemini(profile: dict[str, Any], secrets: Any) -> ProviderClient:
    # Same deferred-key contract as anthropic (GeminiProvider/resolve_api_key).
    # base_url: hidden profile override (same precedent as anthropic's thinking_budget) —
    # no ProviderField, since the UI only ever asks for the key.
    api_key = ((profile or {}).get("api_key") or "").strip() or None
    base_url = ((profile or {}).get("base_url") or "").strip() or None
    return GeminiProvider(api_key=api_key, secrets=secrets, base_url=base_url)


def _build_bedrock(profile: dict[str, Any], secrets: Any) -> ProviderClient:
    # Credentials resolve inside boto3/AnthropicBedrock at call time: explicit keys →
    # named profile → ambient chain (env / ~/.aws default / instance role).
    p = profile or {}

    def get(key: str) -> Optional[str]:
        return (p.get(key) or "").strip() or None

    return BedrockProvider(
        region=get("region"),
        auth_method=get("auth_method"),
        bedrock_api_key=get("bedrock_api_key"),
        profile_name=get("aws_profile"),
        access_key_id=get("aws_access_key_id"),
        secret_access_key=get("aws_secret_access_key"),
        session_token=get("aws_session_token"),
    )


def _build_vertex(profile: dict[str, Any], secrets: Any) -> ProviderClient:
    p = profile or {}

    def get(key: str) -> Optional[str]:
        return (p.get(key) or "").strip() or None

    return VertexProvider(
        project=get("project"),
        location=get("location"),
        auth_method=get("auth_method"),
        service_account_json=get("service_account_json"),
        api_key=get("vertex_api_key"),
    )


def _build_aigw(profile: dict[str, Any], secrets: Any) -> ProviderClient:
    # No SecretStore fallback and no shared key: an Access session is meaningless to every
    # other provider, and every other provider's key is meaningless here. Missing values
    # are tolerated at build time (same deferred contract as the rest) — the provider names
    # what is missing on the first real call.
    base_url, access_token = resolve_settings(profile or {})
    # thinking_budget: same hidden override as the direct Anthropic provider, applied to
    # the gateway's Claude rows. Absent/invalid → the Anthropic default.
    try:
        thinking_budget = int(str((profile or {}).get("thinking_budget") or "").strip())
    except ValueError:
        thinking_budget = None
    # The OAuth session is not a profile field: it lives in the SecretStore and rotates on
    # its own ~15-minute schedule, so the provider gets a reader rather than a value and
    # picks up a silent refresh on the very next request. `secrets` is absent in a few
    # headless assembly paths, where the pasted session (or the env var) is all there is.
    def read_session() -> str:
        from ..aigw_auth import access_token as current

        return current(secrets)

    return AIGatewayProvider(
        base_url=base_url,
        access_token=access_token,
        token_provider=read_session if secrets is not None else None,
        thinking_budget=thinking_budget,
        display_name=str((profile or {}).get("display_name") or ""),
    )


def _build_ollama(profile: dict[str, Any], secrets: Any) -> ProviderClient:
    # Ollama's OpenAI-compatible endpoint ignores the key but the SDK requires a non-empty
    # string, so we pass a placeholder. `base_url` comes from the stored profile (or the default).
    # Chat calls are rewritten onto the native API so we can set num_ctx — the /v1 handler
    # cannot, and its 4,096-token default drops the Cowork prompt (see ollama_context.py).
    from .ollama_context import ollama_http_client

    base_url = _normalize_ollama_url((profile or {}).get("base_url"))
    return OpenAIProvider(api_key="ollama", base_url=base_url, http_client=ollama_http_client())


def _openai_compat(vendor: str, default_base_url: str, env_key: Optional[str] = None):
    """Builder factory for vendors reached through their OpenAI-compatible API (Z AI, DeepSeek,
    Kimi, MiniMax, Qwen, xAI, Mistral). The key is resolved from the vendor's OWN profile (or its
    env var) — deliberately NOT from the OpenAI env/SecretStore fallback, so a configured OpenAI
    key is never silently sent to a different vendor's endpoint. Missing key ⇒ fail fast with a
    vendor-named error (these are only built on demand, when one of their models is selected).
    """

    def build(profile: dict[str, Any], secrets: Any) -> ProviderClient:
        base_url = ((profile or {}).get("base_url") or "").strip() or default_base_url
        api_key = ((profile or {}).get("api_key") or "").strip() or (
            os.environ.get(env_key, "").strip() if env_key else ""
        )
        if not api_key:
            raise RuntimeError(
                f"No {vendor} API key configured — add it in Settings ▸ Models."
            )
        return OpenAIProvider(api_key=api_key, base_url=base_url)

    return build


def _openai_responses_compat(
    vendor: str,
    default_base_url: str,
    env_key: Optional[str] = None,
    *,
    reasoning_summary: bool = True,
):
    """Builder factory for vendors that explicitly implement the OpenAI Responses API.

    Credentials stay isolated to the vendor's own profile/environment variable, matching the
    Chat Completions compat path above. In particular, an OpenAI key is never sent to Ark.
    """

    def build(profile: dict[str, Any], secrets: Any) -> ProviderClient:
        base_url = ((profile or {}).get("base_url") or "").strip() or default_base_url
        api_key = ((profile or {}).get("api_key") or "").strip() or (
            os.environ.get(env_key, "").strip() if env_key else ""
        )
        if not api_key:
            raise RuntimeError(
                f"No {vendor} API key configured — add it in Settings ▸ Models."
            )
        return OpenAIResponsesProvider(
            api_key=api_key,
            base_url=base_url,
            reasoning_summary=reasoning_summary,
        )

    return build


def _compat(
    name: str,
    title: str,
    *,
    base_url: str,
    recommended_model: str,
    env_key: str,
    endpoint_help: str = "",
) -> ProviderDescriptor:
    """Descriptor for an OpenAI-compatible vendor: key + a prefilled, editable endpoint."""
    vendor = title.split(" (")[0]
    return ProviderDescriptor(
        name=name,
        title=title,
        needs_key=True,
        fields=[
            ProviderField(
                "api_key",
                f"{vendor} API key",
                secret=True,
            ),
            ProviderField(
                "base_url",
                "Endpoint",
                required=False,
                default=base_url,
                placeholder=base_url,
                help=endpoint_help
                or f"Prefilled with {vendor}'s official endpoint; edit only for a regional or proxy variant.",
            ),
        ],
        build=_openai_compat(vendor, base_url, env_key),
        recommended_model=recommended_model,
        env_key=env_key,
        blurb=f"Uses {vendor}'s OpenAI-compatible API — the endpoint is prefilled, just add your key.",
    )


def _build_custom(profile: dict[str, Any], secrets: Any) -> ProviderClient:
    """Builder for the single user-defined "Custom endpoint" provider — unlike every
    `_compat` vendor above, there is no vendor default to fall back to: both fields are
    the whole credential, so a missing one fails fast with a pointer back to Settings
    instead of silently probing api.openai.com (OpenAIProvider's own bare-key default).
    """
    p = profile or {}
    base_url = (p.get("base_url") or "").strip()
    api_key = (p.get("api_key") or "").strip()
    if not base_url:
        raise RuntimeError(
            "No endpoint URL configured for the custom provider — add it in Settings ▸ Models."
        )
    if not api_key:
        raise RuntimeError(
            "No API key configured for the custom provider — add it in Settings ▸ Models."
        )
    return OpenAIProvider(api_key=api_key, base_url=base_url)


def _responses_compat(
    name: str,
    title: str,
    *,
    base_url: str,
    recommended_model: str,
    env_key: str,
    endpoint_help: str = "",
    reasoning_summary: bool = True,
) -> ProviderDescriptor:
    """Descriptor for a vendor exposing the OpenAI Responses API."""
    return ProviderDescriptor(
        name=name,
        title=title,
        needs_key=True,
        fields=[
            ProviderField(
                "api_key",
                f"{title} API key",
                secret=True,
            ),
            ProviderField(
                "base_url",
                "Endpoint",
                required=False,
                default=base_url,
                placeholder=base_url,
                help=endpoint_help
                or f"Prefilled with {title}'s official Responses endpoint.",
            ),
        ],
        build=_openai_responses_compat(
            title,
            base_url,
            env_key,
            reasoning_summary=reasoning_summary,
        ),
        recommended_model=recommended_model,
        env_key=env_key,
        blurb=f"Uses {title}'s OpenAI-compatible Responses API — the endpoint is prefilled, just add your key.",
    )


DESCRIPTORS: list[ProviderDescriptor] = [
    ProviderDescriptor(
        name="openai",
        title="OpenAI",
        needs_key=True,
        fields=[
            ProviderField(
                "api_key",
                "OpenAI API key",
                secret=True,
                placeholder="sk-…",
            ),
            ProviderField(
                "base_url",
                "Custom endpoint (optional)",
                secret=False,
                required=False,
                placeholder="https://…/openai/v1",
                help="For Azure OpenAI, vLLM, or any OpenAI-compliant server. Leave blank for api.openai.com.",
            ),
        ],
        build=_build_openai,
        recommended_model="gpt-5.6-sol",
        env_key="OPENAI_API_KEY",
    ),
    ProviderDescriptor(
        name="openai-codex",
        title="ChatGPT subscription",
        needs_key=False,
        fields=[],
        build=_build_codex,
        recommended_model="gpt-5.6-sol",
        blurb="Sign in with your ChatGPT plan and run OpenAI models through your "
        "subscription — no API key. Tokens stay on this machine.",
        auth="oauth",
    ),
    ProviderDescriptor(
        name="anthropic",
        title="Claude (Anthropic)",
        needs_key=True,
        fields=[
            ProviderField(
                "api_key",
                "Anthropic API key",
                secret=True,
                placeholder="sk-ant-…",
            ),
            # No thinking_budget field (owner call 2026-07-23): extended thinking is
            # on by default; the profile key stays a hidden override (0 = off).
        ],
        build=_build_anthropic,
        recommended_model="claude-fable-5",
        env_key="ANTHROPIC_API_KEY",
    ),
    ProviderDescriptor(
        name="gemini",
        title="Gemini (Google)",
        needs_key=True,
        fields=[
            ProviderField(
                "api_key",
                "Gemini API key",
                secret=True,
                placeholder="AIza…",
            ),
        ],
        build=_build_gemini,
        # Newest stable Flash on https://ai.google.dev/gemini-api/docs/models
        # ("our latest and most capable Flash model", checked 2026-08-22).
        recommended_model="gemini-3.7-flash",
        env_key="GEMINI_API_KEY",
    ),
    ProviderDescriptor(
        name="bedrock",
        title="AWS Bedrock",
        needs_key=True,
        fields=[
            ProviderField(
                "region",
                "AWS region",
                secret=False,
                placeholder="us-east-1",
                help="The region your Bedrock model access is enabled in.",
            ),
            # One auth method at a time (owner call 2026-07-26): AWS users are advanced —
            # a direct choice beats a pile of "(optional)" fields with hidden precedence.
            ProviderField(
                "auth_method",
                "Connect with",
                secret=False,
                required=False,  # the default stands in; builder tolerates absence
                default="api_key",
                choices=(
                    {
                        "value": "api_key",
                        "label": "Bedrock API key",
                        "tag": "Easiest",
                        "desc": "A single key generated on the Bedrock console — no AWS CLI or IAM setup needed.",
                    },
                    {
                        "value": "profile",
                        "label": "AWS profile",
                        "desc": "Uses a named profile from ~/.aws — works with `aws configure` and `aws sso login`.",
                    },
                    {
                        "value": "iam",
                        "label": "IAM keys",
                        "desc": "An IAM access key pair. For temporary STS credentials, include the session token.",
                    },
                ),
            ),
            ProviderField(
                "bedrock_api_key",
                "Bedrock API key",
                secret=True,
                required=False,
                placeholder="ABSK…",
                show_when={"auth_method": "api_key"},
            ),
            ProviderField(
                "aws_profile",
                "AWS profile",
                secret=False,
                required=False,
                placeholder="default",
                show_when={"auth_method": "profile"},
                help="Leave blank to use your default AWS credentials (env vars or ~/.aws).",
            ),
            ProviderField(
                "aws_access_key_id",
                "Access key ID",
                secret=False,
                required=False,
                placeholder="AKIA…",
                show_when={"auth_method": "iam"},
            ),
            ProviderField(
                "aws_secret_access_key",
                "Secret access key",
                secret=True,
                required=False,
                show_when={"auth_method": "iam"},
            ),
            ProviderField(
                "aws_session_token",
                "Session token (STS only, optional)",
                secret=True,
                required=False,
                show_when={"auth_method": "iam"},
            ),
        ],
        build=_build_bedrock,
        recommended_model="claude/anthropic.claude-sonnet-4-6-v1:0",
        blurb="Runs models inside your own AWS account. Claude uses Anthropic's native "
        "Bedrock path; every other model goes through the Converse API.",
    ),
    ProviderDescriptor(
        name="vertex",
        title="Vertex AI (Google Cloud)",
        needs_key=True,
        fields=[
            ProviderField(
                "project",
                "GCP project ID",
                secret=False,
                placeholder="my-project-123",
            ),
            ProviderField(
                "location",
                "Location",
                secret=False,
                # Prefilled, not just hinted: as a placeholder the grey "global" read as
                # an already-filled field, and Test then failed on "missing: Location"
                # (owner-hit 2026-10-14).
                default="global",
                placeholder="global",
                help="Use `global` for the newest Gemini and Claude models. Some models "
                "are regional — Model Garden lists each (Claude also: us-east5 / "
                "europe-west1; Qwen3 Coder: us-south1).",
            ),
            ProviderField(
                "auth_method",
                "Connect with",
                secret=False,
                required=False,  # the default stands in; builder tolerates absence
                default="adc",
                choices=(
                    {
                        "value": "adc",
                        "label": "Google Cloud login",
                        "tag": "Recommended",
                        "desc": "Uses your machine's Google Cloud identity (Application "
                        "Default Credentials). Nothing to paste — sign in once in a terminal:",
                        "command": "gcloud auth application-default login",
                    },
                    {
                        "value": "service_account",
                        "label": "Service account",
                        "desc": "A service-account key — the usual path on shared or headless machines.",
                    },
                    {
                        "value": "api_key",
                        "label": "API key",
                        "desc": "A long-lived key from the Google Cloud console's API Keys page. "
                        "Reaches Gemini models only — Claude and open-weight need Google "
                        "Cloud login or a service account.",
                    },
                ),
            ),
            ProviderField(
                "service_account_json",
                "Service-account JSON",
                secret=True,
                required=False,
                show_when={"auth_method": "service_account"},
                help="Paste the JSON key, or a path to the file.",
            ),
            ProviderField(
                "vertex_api_key",
                "Vertex API key",
                secret=True,
                required=False,
                placeholder="AQ.…",
                show_when={"auth_method": "api_key"},
            ),
        ],
        build=_build_vertex,
        recommended_model="gemini/gemini-3.6-flash",
        blurb="Runs models inside your own Google Cloud project. Gemini and Claude use "
        "their native APIs; open-weight models go through the Vertex MaaS endpoint.",
    ),
    ProviderDescriptor(
        name="aigw",
        title="Cloudflare AI Gateway",
        needs_key=True,
        # No credential fields (owner call 2026-08-27): the company gateway's address is
        # baked in and signing in IS the credential. The optional display name is only a
        # User Insights label; leaving it empty preserves the existing Access identity.
        # Legacy address/session profiles and CLOUDFLARE_AIGW_* env vars still work.
        fields=[
            ProviderField(
                "display_name",
                "Display name",
                required=False,
                placeholder="Your name",
                help="Shown as your name in Cloudflare AI Gateway User Insights.",
            )
        ],
        build=_build_aigw,
        # Not the flagship, unlike every other provider's recommendation. Fable 5 and
        # Opus 5 both work here, but this is one shared prepaid balance for the whole
        # company and Fable 5 costs roughly 7x Sonnet per token — a default everyone
        # inherits is the wrong place to spend that. Anyone who wants it just picks it.
        recommended_model="anthropic/claude-sonnet-5",
        blurb="Sign in with your work email — no API key of your own. GPT, Claude and "
        "Gemini, billed to the shared account.",
    ),
    # Ark has two intentionally separate provider identities. BytePlus pay-as-you-go and
    # Volcengine Agent Plan use different regions, endpoints, credentials, and model catalogs;
    # combining them would let one provider profile route a model to the wrong service.
    _responses_compat(
        "ark",
        "BytePlus Ark",
        base_url="https://ark.ap-southeast.bytepluses.com/api/v3",
        recommended_model="dola-seed-evolving-latest-version",
        env_key="ARK_API_KEY",
        endpoint_help="BytePlus Ark's Asia Pacific endpoint. This provider is separate from Volcengine Ark Agent Plan.",
        reasoning_summary=False,
    ),
    _responses_compat(
        "ark-agent-plan-cn",
        "Volcengine Ark Agent Plan",
        base_url="https://ark.cn-beijing.volces.com/api/plan/v3",
        recommended_model="doubao-seed-evolving",
        env_key="ARK_AGENT_PLAN_CN_API_KEY",
        endpoint_help="Volcengine Ark Agent Plan's China (Beijing) endpoint. It requires an Agent Plan API key.",
    ),
    # OpenAI-compatible vendors, listed as first-class providers so users don't need to know the
    # "point the OpenAI slot at a different endpoint" trick (owner call, 2026-07-04). Each keeps
    # its own key profile; the endpoint is prefilled and editable (regional variants in `help`).
    _compat(
        "zai",
        "Z AI (GLM)",
        base_url="https://api.z.ai/api/paas/v4",
        recommended_model="glm-5.2",
        env_key="ZAI_API_KEY",
        endpoint_help="Prefilled with Z AI's international endpoint. China mainland: https://open.bigmodel.cn/api/paas/v4",
    ),
    _compat(
        "deepseek",
        "DeepSeek",
        base_url="https://api.deepseek.com",
        recommended_model="deepseek-v4-flash",
        env_key="DEEPSEEK_API_KEY",
    ),
    _compat(
        "kimi",
        "Kimi (Moonshot AI)",
        base_url="https://api.moonshot.ai/v1",
        recommended_model="kimi-k2.6",
        env_key="MOONSHOT_API_KEY",
        endpoint_help="Prefilled with Moonshot's international endpoint. China mainland: https://api.moonshot.cn/v1",
    ),
    _compat(
        "minimax",
        "MiniMax",
        base_url="https://api.minimax.io/v1",
        recommended_model="MiniMax-M2.5",
        env_key="MINIMAX_API_KEY",
    ),
    _compat(
        "qwen",
        "Qwen (Alibaba)",
        base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        recommended_model="qwen3-max",
        env_key="DASHSCOPE_API_KEY",
        endpoint_help=(
            "Prefilled with the international endpoint. If your key was issued on the "
            "China mainland portal (qwencloud.com), switch to "
            "https://dashscope.aliyuncs.com/compatible-mode/v1 — keys only work against "
            "the endpoint in the region where they were created."
        ),
    ),
    _compat(
        "xai",
        "xAI (Grok)",
        base_url="https://api.x.ai/v1",
        recommended_model="grok-4.3",
        env_key="XAI_API_KEY",
    ),
    _compat(
        "mistral",
        "Mistral",
        base_url="https://api.mistral.ai/v1",
        recommended_model="mistral-large-latest",
        env_key="MISTRAL_API_KEY",
    ),
    _compat(
        "meta",
        "Meta (Muse Spark)",
        base_url="https://api.meta.ai/v1",
        recommended_model="muse-spark-1.1",
        env_key="META_API_KEY",
        endpoint_help="Prefilled with the Meta Model API endpoint (public preview, US-only as of 2026-07).",
    ),
    # Resellers: many labs' models behind one key, using THEIR model namespaces (the curated
    # ids + display labels live in providers/matrix.py). TODO: add Groq here (+ its matrix
    # rows) once the current provider surface is tested — deliberately deferred to bound
    # how much needs verifying at once (owner call, 2026-07-04).
    _compat(
        "together",
        "Together AI",
        base_url="https://api.together.xyz/v1",
        recommended_model="zai-org/GLM-5.2",
        env_key="TOGETHER_API_KEY",
    ),
    _compat(
        "fireworks",
        "Fireworks AI",
        base_url="https://api.fireworks.ai/inference/v1",
        recommended_model="accounts/fireworks/models/glm-5p2",
        env_key="FIREWORKS_API_KEY",
    ),
    _compat(
        "openrouter",
        "OpenRouter",
        base_url="https://openrouter.ai/api/v1",
        recommended_model="z-ai/glm-5.2",
        env_key="OPENROUTER_API_KEY",
    ),
    ProviderDescriptor(
        name="ollama",
        title="Ollama (local models)",
        needs_key=False,
        fields=[
            ProviderField(
                "base_url",
                "Ollama server URL",
                secret=False,
                required=False,
                placeholder=DEFAULT_OLLAMA_URL,
                help="Where `ollama serve` is listening. The OpenAI-compatible /v1 path is added automatically.",
            ),
        ],
        build=_build_ollama,
        # Reliable native tool-calling + strong coding quality (verified). Pull with
        # `ollama pull qwen3-coder:30b`.
        recommended_model="qwen3-coder:30b",
    ),
    # The escape hatch for every OpenAI-compatible server not named above: a self-hosted
    # vLLM/TGI box, an in-house gateway, a vendor we haven't curated a card for yet. Unlike
    # every `_compat`/nvidia descriptor there is no vendor to prefill — `display_name` is
    # the person's own label for whatever they're pointing at, and `manager.get_providers`
    # uses it to overwrite this row's title (so the gallery card and provider list read by
    # what they typed, not the generic "Custom endpoint"). Single instance only:
    # one `provider:custom` SecretStore profile, like every other provider —
    # multiple simultaneous custom endpoints would need a namespaced profile key and list UI
    # neither the GUI nor the router have today, so that stays out of scope until someone
    # actually needs a second one. No `env_key`: an env-var fallback would let the provider
    # "work" with a stale key from a previous endpoint the person typed over, silently
    # pointing traffic at whatever server used to live at that address.
    ProviderDescriptor(
        name="custom",
        title="Custom endpoint",
        needs_key=True,
        fields=[
            ProviderField(
                "display_name",
                "Endpoint name",
                required=True,
                help="Shown as this provider's name in the provider list.",
            ),
            ProviderField(
                "api_key",
                "API key",
                secret=True,
            ),
            ProviderField(
                "base_url",
                "Endpoint",
                required=True,
                placeholder="https://…/v1",
                help="OpenAI-compatible base URL, usually ending in /v1.",
            ),
        ],
        build=_build_custom,
        blurb="Any OpenAI-compatible endpoint — name it, then add the address (with /v1) and your API key.",
    ),
]

_BY_NAME = {d.name: d for d in DESCRIPTORS}


def provider_descriptors() -> list[ProviderDescriptor]:
    return list(DESCRIPTORS)


def provider_names() -> list[str]:
    return [d.name for d in DESCRIPTORS]


def get_descriptor(name: str) -> Optional[ProviderDescriptor]:
    return _BY_NAME.get(name)


def build_provider_client(
    name: str, profile: dict[str, Any], secrets: Any
) -> ProviderClient:
    """Build a `ProviderClient` for `name` from its stored profile. Unknown → OpenAI default."""
    if name in RETIRED_PROVIDERS:
        raise ValueError(retired_provider_error(name))
    descriptor = _BY_NAME.get(name) or _BY_NAME["openai"]
    return descriptor.build(profile or {}, secrets)


def descriptor_configured(d: ProviderDescriptor, profile: dict[str, Any]) -> bool:
    """Whether a provider is usable with the given stored profile. Single-key providers:
    a stored or env key. Multi-field cloud providers (no `api_key` field, e.g. Bedrock):
    every required field present — their actual credentials may be ambient (~/.aws, ADC).
    """
    if d.auth == "oauth":
        # A stored token set = signed in (the tokens live in the same profile).
        return bool((profile or {}).get("tokens"))
    if not d.needs_key:
        return True  # keyless (Ollama) — usable out of the box
    profile = profile or {}
    if d.name == "aigw":
        # Fieldless: the address is baked in and never counts. Configured means "holds a
        # credential" — a completed sign-in (aigw_auth keeps its OAuth state inside this
        # profile) or the legacy pasted/env Access session. Anything else would show a
        # fresh install as "✓ Connected" before anyone signed in.
        from ..aigw_auth import OAUTH_FIELD

        oauth = profile.get(OAUTH_FIELD)
        signed_in = isinstance(oauth, dict) and bool(
            oauth.get("access_token") or oauth.get("refresh_token")
        )
        return signed_in or bool(resolve_settings(profile)[1])
    if d.name == "custom":
        # Unlike the vendor `_compat` cards, there is no default endpoint standing in — a
        # key alone would build an OpenAIProvider `_build_custom` immediately raises on, so
        # "configured" here also needs the required base_url (and display_name) present.
        return bool(profile.get("api_key")) and all(
            profile.get(f.key) for f in d.fields if f.required
        )
    if any(f.key == "api_key" for f in d.fields):
        return bool(profile.get("api_key")) or bool(
            d.env_key and os.environ.get(d.env_key)
        )
    return all(profile.get(f.key) for f in d.fields if f.required)


def detect_provider(api_key: str) -> Optional[str]:
    """Best-effort provider guess from an API key's shape, for the onboarding auto-detect.
    Returns a known provider name or None. Mirrors the GUI's client-side detection so both agree.
    """
    key = (api_key or "").strip()
    if not key:
        return None
    if key.startswith("sk-ant-"):
        return "anthropic"
    if key.startswith("sk-or-"):
        return "openrouter"
    if key.startswith("AIza"):
        return "gemini"
    if key.startswith(("sk-", "sk_")):
        return "openai"
    return None


def _guard_message(resp: Any) -> str:
    """The company guard's own refusal text from a gateway response, or "".

    gateway-guard answers every refusal as `{"error": {"code", "message"}}` with a Chinese
    `message` that ends in `[gateway-guard]` and is written to be shown as-is (502
    `catalog_unavailable`, 503 `gate_unavailable`, 403 `model_restricted`, …). The tag is
    what tells it apart from a vendor error the gateway merely relayed, which has the same
    JSON shape and must keep going through the status-code reading instead.
    """
    try:
        err = (resp.json() or {}).get("error") or {}
    except Exception:  # noqa: BLE001 - non-JSON body (Access's HTML login page, plain text)
        return ""
    message = str(err.get("message") or "").strip() if isinstance(err, dict) else ""
    return message if "[gateway-guard]" in message else ""


def _aigw_probe_model(payload: Any) -> str:
    """Which model the Test completion should call, read from a `GET /gate/models` body.

    The guard names it itself (`probe`: an id guaranteed to be on this person's list).
    When that key is missing or null, the first id of `models` is by construction on the
    list too. Nothing usable → "" — the caller reports that; no id is ever invented here,
    because any hard-coded one is a model somebody's list does not contain.
    """
    if not isinstance(payload, dict):
        return ""
    probe = payload.get("probe")
    if isinstance(probe, str) and probe.strip():
        return probe.strip()
    models = payload.get("models")
    for entry in models if isinstance(models, list) else []:
        model_id = entry.get("id") if isinstance(entry, dict) else None
        if isinstance(model_id, str) and model_id.strip():
            return model_id.strip()
    return ""


_AIGW_STALE_SESSION = (
    "Your Access session isn't valid — sign in again to refresh it. "
    "(Sessions expire; this is the usual cause.)"
)
# The address is baked in, so this is never a typo on the user's side — it means the
# custom-domain mapping (or the guard / gateway behind it) is broken.
_AIGW_NOT_A_GATEWAY = (
    "The built-in gateway address didn't answer as a gateway — tell your administrator "
    "(the domain mapping may be broken)."
)


# -- transport failures (the Test button's "couldn't reach") ---------------------------
# (signature, kind, hint) — first match wins, so the specific readings come before the
# broad "timed out". Signatures are substrings of the lowercased `str(exc)` plus the
# exception's class name: every stack spells the same failure differently (httpx
# ConnectTimeout, ssl.SSLError, socket.gaierror, botocore EndpointConnectionError…) while
# the words underneath repeat. `handshake` is listed before `timed out` on purpose — the
# failure this company hits most, "The handshake operation timed out" (a TLS handshake
# that never completes, usually a proxy or an interrupted VPN), reads as a TLS problem,
# not as a generic timeout.
_TRANSPORT_SIGNATURES: tuple[tuple[str, str, str], ...] = (
    (
        "certificate_verify_failed",
        "certificate",
        "TLS certificate verification failed; the app's CA bundle may be missing or stale",
    ),
    (
        "certificate verify failed",
        "certificate",
        "TLS certificate verification failed; the app's CA bundle may be missing or stale",
    ),
    ("handshake", "tls", "the TLS handshake failed or timed out"),
    ("ssl:", "tls", "TLS handshake failed"),
    ("sslerror", "tls", "TLS handshake failed"),
    ("gaierror", "dns", "DNS could not resolve the endpoint"),
    ("nodename", "dns", "DNS could not resolve the endpoint"),
    ("name or service", "dns", "DNS could not resolve the endpoint"),
    ("getaddrinfo", "dns", "DNS could not resolve the endpoint"),
    ("name resolution", "dns", "DNS could not resolve the endpoint"),
    ("refused", "refused", "the endpoint refused the connection"),
    ("timed out", "timeout", "the connection timed out"),
    ("timeout", "timeout", "the connection timed out"),
)


def _classify_transport_error(exc: BaseException) -> tuple[Optional[str], Optional[str]]:
    """`(kind, hint)` for a verify probe's transport failure — `(None, None)` when the
    text matches no known signature. `kind` keys the gateway's fixed sentences below;
    `hint` is the English clause the other probes append."""
    haystack = f"{' '.join(str(exc).split())} {exc.__class__.__name__}".lower()
    for signature, kind, hint in _TRANSPORT_SIGNATURES:
        if signature in haystack:
            return kind, hint
    return None, None


def _describe_transport_error(exc: BaseException) -> str:
    """Turn a verify probe's transport failure into one actionable line.

    The bare class name ("ConnectError") cost a real user round-trips of diagnosis while
    the exception carried the answer all along — TLS verification, DNS, refusal and
    timeout each read differently (upstream #505). Class name plus message, plus a short
    hint when the signature maps to a known fix; a silent exception renders exactly the
    old class-name-only text.
    """
    msg = " ".join(str(exc).split()).rstrip(".")[:200]
    _kind, hint = _classify_transport_error(exc)
    name = exc.__class__.__name__
    if hint:
        if not msg:
            return f"{name} — {hint}"
        return f"{name}: {msg} — looks like {hint}"
    return name if not msg else f"{name}: {msg}"


# The gateway's "couldn't reach" is a FIXED sentence per failure kind, not the free-form
# line above: the GUI translates server strings by whole-string lookup
# (surfaces/gui/src/providers/ProviderSetup.tsx `localizeVerifyError` → `t(msg)`, keys in
# locales/zh-CN.json), so interpolating the exception would leave colleagues with English.
# Every sentence keeps the "Couldn't reach the gateway" prefix; the raw class and message
# go to the server log at warning level instead (`_verify_aigw`).
_AIGW_UNREACHABLE_DEFAULT = "Couldn't reach the gateway — check your network and try again."
_AIGW_UNREACHABLE: dict[str, str] = {
    "timeout": (
        "Couldn't reach the gateway — the connection timed out. Check your network or "
        "proxy and try again."
    ),
    "tls": (
        "Couldn't reach the gateway — the TLS handshake failed or timed out. Check your "
        "network, proxy or VPN and try again."
    ),
    "certificate": (
        "Couldn't reach the gateway — TLS certificate verification failed. The app's CA "
        "bundle may be missing or stale, or a proxy is intercepting HTTPS."
    ),
    "dns": (
        "Couldn't reach the gateway — DNS could not resolve its address. Check your "
        "network or DNS settings and try again."
    ),
    "refused": (
        "Couldn't reach the gateway — the connection was refused. Check your network or "
        "proxy and try again."
    ),
}


def _aigw_unreachable(exc: Optional[BaseException]) -> dict[str, Any]:
    """The Test's answer when a gateway request never completed: a fixed sentence picked
    by failure kind (translatable), the full cause in the log (greppable)."""
    kind, _hint = _classify_transport_error(exc) if exc is not None else (None, None)
    return {"ok": False, "error": _AIGW_UNREACHABLE.get(kind or "", _AIGW_UNREACHABLE_DEFAULT)}


def _verify_aigw(fields: dict[str, Any], timeout: float) -> dict[str, Any]:
    """Ask the guard which model to test with, then run one short generation on it.

    Two requests, in this order:

    1. `GET {base}/gate/models` — this person's model list. The guard is an allowlist, so
       there is no model the Test could safely assume: the response's `probe` (or, failing
       that, the first listed id) is the only id known to be callable by THIS person. A
       person with nothing ticked gets 502 `catalog_unavailable`, an unreadable gate config
       503 `gate_unavailable`; either way the guard's own Chinese sentence is the Test's
       failure, verbatim — it says what is wrong better than anything composed here.
    2. `POST {base}/compat/chat/completions` on that id. There is no read-only probe worth
       running instead: a real (sub-cent) completion exercises the whole path at once —
       Access, the custom domain, the `/compat` prefix rule, and Unified Billing. Same bet
       the Ark descriptor makes.

    `cf-aig-skip-cache` matters more than it looks: the gateway caches responses, so
    without it a second Test press can replay the first one and report success against a
    session that has since expired.
    """
    import httpx

    # Never empty: `resolve_settings` falls back to the built-in company gateway, which is
    # why there is no address to ask for here (or anywhere else in the pane).
    base_url, access_token = resolve_settings(fields or {})
    # Signed in beats pasted, exactly as the provider decides it at call time — otherwise
    # Test would keep exercising a stale typed session that real calls no longer use.
    # Injected by manager.verify_provider, which is the one holding the SecretStore.
    oauth_token = str((fields or {}).get("oauth_token") or "").strip()
    if not oauth_token and not access_token:
        return {"ok": False, "error": "Sign in to the gateway first."}
    # Fixed sentences on purpose (`_aigw_unreachable`): interpolating the exception would
    # defeat the GUI's word-for-word translation table. The KIND of failure still reaches
    # the person — a TLS handshake that times out (this network's recurring one, 2026-10)
    # points at the proxy/VPN, not at "check your network" — and the raw cause is logged
    # at warning so support can read it without a debug build.
    listing, err = _catalog_request(
        "aigw", key="", base_url=None, fields=fields, timeout=timeout, raw_exc=True
    )
    if listing is None:
        logger.warning(
            "aigw verify: model list unreachable: %s",
            _describe_transport_error(err) if isinstance(err, BaseException) else err,
        )
        return _aigw_unreachable(err if isinstance(err, BaseException) else None)
    if listing.status_code >= 300:
        if listing.status_code == 404 and not _guard_message(listing):
            return {"ok": False, "error": _AIGW_NOT_A_GATEWAY}
        return _map_probe_failure("aigw", _BY_NAME["aigw"], listing)
    try:
        payload = listing.json()
    except Exception:  # noqa: BLE001 - a 200 that is not JSON is not the guard answering
        payload = None
    if not isinstance(payload, dict):
        # Access can serve its login page with a 200; anything else that is not the
        # guard's JSON means the address is not reaching the guard at all.
        body = (getattr(listing, "text", "") or "").lower()
        if "cloudflare access" in body:
            return {"ok": False, "error": _AIGW_STALE_SESSION}
        return {"ok": False, "error": _AIGW_NOT_A_GATEWAY}
    probe_model = _aigw_probe_model(payload)
    if not probe_model:
        return {
            "ok": False,
            "error": "The gateway's list has no model to test with — ask your "
            "administrator to open one for you.",
        }
    display_name = str((fields or {}).get("display_name") or "")
    headers = (
        bearer_headers(oauth_token, display_name)
        if oauth_token
        else access_headers(access_token, display_name)
    )
    headers["cf-aig-skip-cache"] = "true"
    try:
        resp = httpx.post(
            wire_url(base_url, "chat") + "/chat/completions",
            headers=headers,
            json={
                "model": probe_model,
                "messages": [{"role": "user", "content": "Reply with OK."}],
                "max_tokens": 16,
            },
            timeout=timeout,
        )
    except Exception as exc:
        logger.warning("aigw verify: unreachable: %s", _describe_transport_error(exc))
        return _aigw_unreachable(exc)
    if resp.status_code < 300:
        return {"ok": True}
    # The guard sits in front of this call too (403 `model_restricted`, 503
    # `gate_unavailable`, 429 `quota_exceeded`, …) and its sentence is asked for first: a
    # guard 403 read by status alone would be reported as a stale Access session, which
    # the list request a few lines up has just disproved.
    refusal = _guard_message(resp)
    if refusal:
        return {"ok": False, "error": refusal}
    body = (resp.text or "").lower()
    # Access answers an unauthenticated request with its own HTML login page, not JSON —
    # so a 302/403 here is nearly always a stale session rather than anything upstream.
    if resp.status_code in (301, 302, 401, 403) or "cloudflare access" in body:
        return {"ok": False, "error": _AIGW_STALE_SESSION}
    if resp.status_code == 404 or "could not route" in body:
        return {"ok": False, "error": _AIGW_NOT_A_GATEWAY}
    if "invalid provider" in body:
        return {
            "ok": False,
            "error": "The gateway is reachable but rejected the model's provider "
            "prefix. This is an app bug, not a setting — please report it.",
        }
    if resp.status_code == 402 or "credit" in body:
        return {
            "ok": False,
            "error": "You're signed in, but the shared account is out of AI Gateway "
            "credits — ask your administrator to top up.",
        }
    if resp.status_code == 429:
        return {
            "ok": False,
            "error": "Rate limited right now — wait a moment and press Test again.",
        }
    return {"ok": False, "error": f"The gateway returned HTTP {resp.status_code}."}


def _verify_bedrock(fields: dict[str, Any], timeout: float) -> dict[str, Any]:
    """One cheap read-only Bedrock call (list models) with the same explicit → profile →
    ambient credential resolution the provider itself uses."""
    from .bedrock_provider import _session_kwargs

    def get(key: str) -> Optional[str]:
        return (fields.get(key) or "").strip() or None

    try:
        import boto3
        from botocore.config import Config
    except ImportError:
        return {
            "ok": False,
            "error": "boto3 is not installed — `pip install 'openworker[bedrock]'`.",
        }
    # Exactly one auth method is exercised — the one the form has selected. Per-method
    # required fields are checked here so the Test button says what's missing.
    method = get("auth_method") or "api_key"
    if method == "api_key" and not (
        get("bedrock_api_key") or os.environ.get("AWS_BEARER_TOKEN_BEDROCK")
    ):
        return {"ok": False, "error": "Enter a Bedrock API key to test."}
    if method == "iam" and not (
        get("aws_access_key_id") and get("aws_secret_access_key")
    ):
        return {"ok": False, "error": "Enter an access key ID and secret access key."}
    try:
        if method == "api_key":
            # The key rides the env var (boto3's only bearer channel); bearer then wins
            # over any ambient SigV4 credentials for Bedrock calls.
            if get("bedrock_api_key"):
                os.environ["AWS_BEARER_TOKEN_BEDROCK"] = get("bedrock_api_key")
            session_kwargs: dict[str, Any] = {}
        elif method == "profile":
            # Blank profile → the default credential chain (env vars / ~/.aws / role).
            session_kwargs = _session_kwargs(get("aws_profile"), None, None, None)
        else:  # iam
            session_kwargs = _session_kwargs(
                None,
                get("aws_access_key_id"),
                get("aws_secret_access_key"),
                get("aws_session_token"),
            )
        session = boto3.session.Session(**session_kwargs)
        client = session.client(
            "bedrock",
            region_name=get("region"),
            config=Config(connect_timeout=timeout, read_timeout=timeout),
        )
        client.list_foundation_models()
    except Exception as exc:
        kind = exc.__class__.__name__
        if kind == "NoCredentialsError":
            return {
                "ok": False,
                "error": "No AWS credentials found — enter keys or a profile, or run "
                "`aws configure` / `aws sso login` first.",
            }
        if kind == "ProfileNotFound":
            return {"ok": False, "error": f"{exc}"}
        # botocore raises MODELED subclasses of ClientError (class name
        # "AccessDeniedException", not "ClientError"), so detect by the response shape,
        # never the class name — a name check sent every modeled error to the generic
        # fallback and hid the specific message (owner report 2026-08-17).
        code = (getattr(exc, "response", None) or {}).get("Error", {}).get("Code", "")
        if code:
            if code in ("UnrecognizedClientException", "InvalidSignatureException"):
                return {"ok": False, "error": "AWS rejected the credentials."}
            if code in ("AccessDeniedException", "AccessDenied"):
                return {
                    "ok": False,
                    "error": (
                        "Credentials work but lack Bedrock access "
                        "(bedrock:ListFoundationModels) — check the key's policy, its "
                        "expiry (short-term keys last up to 12h), and that the region "
                        "matches where the key was created."
                    ),
                }
            if code == "ExpiredTokenException":
                return {"ok": False, "error": "The credentials have expired — generate a new key."}
            return {"ok": False, "error": f"AWS Bedrock returned {code}."}
        return {
            "ok": False,
            "error": f"Couldn't reach AWS Bedrock ({_describe_transport_error(exc)}).",
        }
    return {"ok": True}


# Verify probe: countTokens on a stable Gemini model — free (no generation), works with
# plain ADC (the model list/GET endpoints 403/404 under user credentials — checked live
# 2026-07-26), and exercises project + location + API enablement in one call.
_VERTEX_PROBE_MODEL = "gemini-2.5-flash"
_VERTEX_PROBE_BODY = {"contents": [{"role": "user", "parts": [{"text": "hi"}]}]}


def _verify_vertex(fields: dict[str, Any], timeout: float) -> dict[str, Any]:
    """One cheap call (countTokens) through the SELECTED auth method: ADC /
    service-account bearer, or the express API key header."""
    import httpx

    from .vertex_provider import load_credentials

    project = (fields.get("project") or "").strip()
    location = (fields.get("location") or "").strip()
    method = (fields.get("auth_method") or "").strip() or (
        "service_account" if (fields.get("service_account_json") or "").strip() else "adc"
    )
    if method == "api_key":
        key = (fields.get("vertex_api_key") or "").strip()
        if not key:
            return {"ok": False, "error": "Enter a Vertex API key to test."}
        try:
            # Express mode is global — no region host, no project in the path.
            resp = httpx.post(
                "https://aiplatform.googleapis.com/v1/publishers/google/models/"
                f"{_VERTEX_PROBE_MODEL}:countTokens",
                headers={"x-goog-api-key": key},
                json=_VERTEX_PROBE_BODY,
                timeout=timeout,
            )
        except Exception as exc:
            return {
                "ok": False,
                "error": f"Couldn't reach Vertex AI ({_describe_transport_error(exc)}).",
            }
        if resp.status_code < 300:
            return {"ok": True}
        if resp.status_code in (401, 403):
            return {"ok": False, "error": "Google rejected the API key."}
        return {"ok": False, "error": f"Vertex AI returned HTTP {resp.status_code}."}
    if method == "service_account" and not (fields.get("service_account_json") or "").strip():
        return {"ok": False, "error": "Paste a service-account JSON to test."}
    try:
        creds = None
        if method == "service_account":
            creds = load_credentials(fields.get("service_account_json"))
        if creds is None:
            import google.auth

            creds, _ = google.auth.default(
                scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )
        import functools

        from google.auth.transport.requests import Request

        # google-auth's transport waits 120 s by default; on a network that cannot reach
        # oauth2.googleapis.com the Test button would sit there for two minutes looking
        # dead. Bound the token refresh by the same timeout as the probe itself.
        creds.refresh(functools.partial(Request(), timeout=timeout))
    except Exception as exc:
        kind = exc.__class__.__name__
        if kind == "TransportError":
            return {
                "ok": False,
                "error": "Couldn't reach Google to refresh the credentials — check the network or proxy.",
            }
        if kind == "DefaultCredentialsError":
            return {
                "ok": False,
                "error": "No Google Cloud credentials found — paste a service-account "
                "JSON, or run `gcloud auth application-default login` first.",
            }
        if kind in ("RefreshError", "MalformedError", "JSONDecodeError", "ValueError"):
            return {"ok": False, "error": "Google rejected the credentials."}
        return {"ok": False, "error": f"Couldn't load Google credentials ({kind})."}
    from .vertex_provider import _regional_host

    try:
        resp = httpx.post(
            f"https://{_regional_host(location)}/v1/projects/{project}"
            f"/locations/{location}/publishers/google/models/"
            f"{_VERTEX_PROBE_MODEL}:countTokens",
            headers={"Authorization": f"Bearer {creds.token}"},
            json=_VERTEX_PROBE_BODY,
            timeout=timeout,
        )
    except Exception as exc:
        return {
            "ok": False,
            "error": f"Couldn't reach Vertex AI ({_describe_transport_error(exc)}).",
        }
    if resp.status_code < 300:
        return {"ok": True}
    if resp.status_code in (401, 403):
        return {
            "ok": False,
            "error": "Credentials work but lack Vertex AI access in this project.",
        }
    if resp.status_code == 404:
        return {"ok": False, "error": "Project or location not found on Vertex AI."}
    return {"ok": False, "error": f"Vertex AI returned HTTP {resp.status_code}."}


#: Google 401 reasons that mean "Google recognizes an AI Studio auth key (`AQ.…`) but will
#: not serve THIS one" — `x-goog-api-key` earns ACCESS_TOKEN_TYPE_UNSUPPORTED, `Bearer`
#: earns API_KEY_SERVICE_BLOCKED. A healthy auth key sails through the plain header form
#: and the relay untouched (verified live 2026-08-27), so these mean the key itself is
#: dead, mis-copied, or simply the wrong one. Docs float a "Restrict to Gemini API only"
#: console fix, but no such switch exists in the AI Studio UI (owner checked 2026-08-27) —
#: point at the key, not at settings nobody can find.
_UNUSABLE_KEY_REASONS = frozenset(
    {"ACCESS_TOKEN_TYPE_UNSUPPORTED", "API_KEY_SERVICE_BLOCKED"}
)

_UNUSABLE_KEY_HINT = (
    "Google 认得出这是 AI Studio 新版 auth key（AQ. 开头），但拒收了这一把——"
    "通常是 key 已失效、复制不完整，或粘的不是可用的那把。"
    "请到 https://aistudio.google.com/api-keys 重新完整复制一遍粘进来；"
    "还不行就让管理员新建一把再发你。"
)


def _google_error_detail(resp: Any) -> tuple[str, str]:
    """(`message`, first `details[].reason`) out of a Google-shaped `{"error": {...}}`
    body, else ("", "") — non-JSON bodies, test fakes without a .json."""
    try:
        parsed = resp.json()
    except (ValueError, AttributeError):
        return "", ""
    if not isinstance(parsed, dict):
        return "", ""
    error = parsed.get("error")
    if not isinstance(error, dict):
        return "", ""
    message = str(error.get("message") or "").strip()
    reason = ""
    details = error.get("details")
    if isinstance(details, list):
        for entry in details:
            if isinstance(entry, dict) and entry.get("reason"):
                reason = str(entry["reason"])
                break
    return message, reason


def relay_headers_from(fields: dict[str, Any]) -> dict[str, str]:
    """`Authorization: Bearer` for the company Gemini relay, out of an already-merged field
    map. Test runs before anything is saved, so the caller (manager.verify_provider) is the
    one holding the SecretStore; this module only reads what it was handed."""
    token = str(fields.get("relay_token") or "").strip()
    return {"Authorization": f"Bearer {token}"} if token.startswith(RELAY_TOKEN_PREFIX) else {}


def _catalog_request(
    name: str,
    *,
    key: str,
    base_url: Optional[str],
    fields: Optional[dict[str, Any]],
    timeout: float,
    raw_exc: bool = False,
) -> tuple[Any, Any]:
    """One GET against a provider's model-list endpoint — the shared wire logic behind
    both `verify_provider_key` (the Test button) and `list_provider_models` (the catalog
    fetch). Covers Anthropic, Gemini via the relay, Ollama, the gateway guard and
    OpenAI-compatible `/models`; Ark's POST Responses probe and the multi-field cloud
    providers stay inline in `verify_provider_key`. Returns `(response, None)` on a completed
    HTTP round trip (any status code) or `(None, error)` on a network failure — never
    raises. `error` is the user-facing sentence ("Couldn't reach <title> (<cause>)."), or
    the exception itself with `raw_exc=True` for a caller that words its own answer.
    """
    import httpx

    d = _BY_NAME.get(name) or _BY_NAME["openai"]
    try:
        if name == "anthropic":
            resp = httpx.get(
                "https://api.anthropic.com/v1/models",
                headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
                timeout=timeout,
            )
        elif name == "gemini":
            # Two credentials, because the company relay wants both: `key` is the person's
            # own Google key (what Test is actually validating) and the relay login says who
            # is asking. Testing while signed out earns a 401 from the relay, which is the
            # honest answer — that call would fail for real too.
            gemini_headers = {"x-goog-api-key": key}
            gemini_headers.update(relay_headers_from(fields or {}))
            resp = httpx.get(
                resolve_base_url(None) + "/v1beta/models",
                headers=gemini_headers,
                timeout=timeout,
            )
        elif name == "ollama":
            base = _normalize_ollama_url(base_url)
            resp = httpx.get(base.rstrip("/") + "/models", timeout=timeout)
        elif name == "aigw":
            # The company guard answers with THIS person's model list — exactly the
            # models their administrator ticked for them, the single source of truth for
            # what they may call — not the gateway's raw pricing catalog, which lists
            # long-retired models too. Same credential choice as `_verify_aigw`'s
            # completion: the signed-in OAuth session beats a pasted one.
            gw_base, access_token = resolve_settings(fields or {})
            oauth_token = str((fields or {}).get("oauth_token") or "").strip()
            if not oauth_token and not access_token:
                return None, "Sign in to the gateway first."
            resp = httpx.get(
                normalise_base(gw_base) + "/gate/models",
                headers=(
                    bearer_headers(oauth_token)
                    if oauth_token
                    else access_headers(access_token)
                ),
                timeout=timeout,
            )
        else:  # openai + any OpenAI-compatible endpoint (Azure, OpenRouter, vendors, vLLM…)
            default_base = next(
                (f.default for f in d.fields if f.key == "base_url" and f.default), ""
            )
            base = (
                (base_url or "").strip().rstrip("/")
                or default_base.rstrip("/")
                or "https://api.openai.com/v1"
            )
            resp = httpx.get(
                base + "/models",
                headers={"Authorization": f"Bearer {key}"},
                timeout=timeout,
            )
    except Exception as exc:  # DNS/connection/timeout — never let it bubble to a 500
        if raw_exc:
            return None, exc
        return None, f"Couldn't reach {d.title} ({_describe_transport_error(exc)})."
    return resp, None


def _map_probe_failure(name: str, d: ProviderDescriptor, resp: Any) -> dict[str, Any]:
    """Status-code and response-body → user-facing error text for a failed
    (`status_code >= 300`) model-list/probe response. Shared by `verify_provider_key` and
    `list_provider_models`."""
    if name == "gemini":
        # The relay's refusals arrive as a Google-shaped JSON envelope whose `message` was
        # written for exactly this moment (not signed in / login revoked / over quota) —
        # pass it through instead of flattening everything into "Invalid API key.". An
        # unconfigured AI Studio auth key additionally gets the console-side fix spelled out.
        detail, reason = _google_error_detail(resp)
        if reason in _UNUSABLE_KEY_REASONS:
            return {"ok": False, "error": _UNUSABLE_KEY_HINT}
        if detail:
            return {"ok": False, "error": detail}
    if name == "aigw":
        # The guard's own refusal first, verbatim: its Chinese `message` is written for
        # this pane — 502 `catalog_unavailable` (the administrator has ticked no model for
        # this person, or the catalog could not be read), 503 `gate_unavailable` (the gate
        # config is temporarily unreadable). Asked before the status code so a guard
        # refusal that happens to be a 403 is not misread as a stale session.
        refusal = _guard_message(resp)
        if refusal:
            return {"ok": False, "error": refusal}
        # Same reading as `_verify_aigw`: Access answers a stale session with a redirect or
        # its own login page.
        body = (getattr(resp, "text", "") or "").lower()
        if resp.status_code in (301, 302, 401, 403) or "cloudflare access" in body:
            return {"ok": False, "error": _AIGW_STALE_SESSION}
        try:
            err = (resp.json() or {}).get("error") or {}
            message = str(err.get("message") or "").strip() if isinstance(err, dict) else ""
        except Exception:  # noqa: BLE001 - non-JSON body, fall through to the status line
            message = ""
        if message:
            return {"ok": False, "error": message}
    if resp.status_code in (401, 403):
        if name == "ollama":
            return {"ok": False, "error": "Server rejected the request."}
        return {"ok": False, "error": "Invalid API key."}
    if resp.status_code == 404 and name == "ollama":
        return {
            "ok": False,
            "error": "Reached the server, but no OpenAI-compatible /v1 API there.",
        }
    return {"ok": False, "error": f"{d.title} returned HTTP {resp.status_code}."}


def verify_provider_key(
    name: str,
    *,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    fields: Optional[dict[str, Any]] = None,
    timeout: float = 10.0,
) -> dict[str, Any]:
    """Validate a provider's credentials with one cheap call — usually list models.

    Ark's Responses-compatible data plane does not document a `/models` probe, so its Test button
    sends a non-persisted one-token Responses request instead. Callers pass the key directly so a
    user can Test before saving. Never raises; returns {ok, error?}. Multi-field cloud providers
    (Bedrock, Vertex) take their whole form via `fields`; everyone else uses api_key/base_url.
    """
    if name in RETIRED_PROVIDERS:
        return {"ok": False, "error": retired_provider_error(name)}
    d = _BY_NAME.get(name) or _BY_NAME["openai"]
    key = (api_key or "").strip()
    if d.auth == "oauth":
        # OAuth providers verify from their stored tokens (needs the SecretStore),
        # which only the manager holds — see SessionManager.verify_provider.
        return {"ok": False, "error": f"{d.title} verifies via its sign-in, not a key."}
    if name == "bedrock":
        return _verify_bedrock(fields or {}, timeout)
    if name == "vertex":
        return _verify_vertex(fields or {}, timeout)
    if name == "aigw":
        return _verify_aigw(fields or {}, timeout)
    if name == "custom" and not (base_url or "").strip():
        # No vendor default to fall back to (unlike the `_compat` cards below) — without
        # this guard an empty URL would fall all the way through the generic branch to its
        # "https://api.openai.com/v1" fallback and Test a completely different service.
        return {"ok": False, "error": "Enter the endpoint URL first."}
    if name in ("ark", "ark-agent-plan-cn"):
        # Ark's Responses-compatible data plane has no read-only /models probe; a
        # non-persisted one-token completion exercises the credentials instead. POST, so
        # it stays inline rather than in the shared GET helper.
        import httpx

        default_base = next(
            (f.default for f in d.fields if f.key == "base_url" and f.default), ""
        )
        base = (base_url or "").strip().rstrip("/") or default_base.rstrip("/")
        try:
            resp = httpx.post(
                base + "/responses",
                headers={"Authorization": f"Bearer {key}"},
                json={
                    "model": d.recommended_model,
                    "input": "Reply with OK.",
                    "max_output_tokens": 1,
                    "store": False,
                },
                timeout=timeout,
            )
        except Exception as exc:
            return {
                "ok": False,
                "error": f"Couldn't reach {d.title} ({_describe_transport_error(exc)}).",
            }
    else:
        resp, err = _catalog_request(
            name, key=key, base_url=base_url, fields=fields, timeout=timeout
        )
        if err:
            return {"ok": False, "error": err}

    if resp.status_code < 300:
        return {"ok": True}
    return _map_probe_failure(name, d, resp)


def list_provider_models(
    name: str,
    *,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    fields: Optional[dict[str, Any]] = None,
    timeout: float = 10.0,
    provider_title: str = "",
) -> dict[str, Any]:
    """Fetch and parse a provider's live model catalog (Settings ▸ Models' background
    refresh, and `verify_provider`'s Test-button-doubles-as-a-catalog-pull path). Never
    raises; returns `{"ok": True, "models": [...]}` or `{"ok": False, "error": ...}`.

    An HTTP round trip that completed with a 2xx status but couldn't be turned into any
    models (non-JSON body, or a JSON body with nothing chat-shaped in it) also carries
    `"http_ok": True` — callers that only care whether the credentials themselves are good
    (not whether a catalog came back) can treat that as a pass.
    """
    from .catalog import parse_catalog, supports_catalog

    if name in RETIRED_PROVIDERS:
        return {"ok": False, "error": retired_provider_error(name), "unsupported": True}
    d = _BY_NAME.get(name) or _BY_NAME["openai"]
    if d.auth == "oauth" or not supports_catalog(name):
        return {
            "ok": False,
            "error": f"{d.title} has no model list API.",
            "unsupported": True,
        }
    key = (api_key or "").strip()
    if name == "custom" and not (base_url or "").strip():
        return {"ok": False, "error": "Enter the endpoint URL first."}
    resp, err = _catalog_request(
        name, key=key, base_url=base_url, fields=fields, timeout=timeout
    )
    if err:
        return {"ok": False, "error": err}
    if resp.status_code >= 300:
        return _map_probe_failure(name, d, resp)
    try:
        payload = resp.json()
    except (ValueError, AttributeError):
        return {
            "ok": False,
            "error": f"{d.title} returned a non-JSON model list.",
            "http_ok": True,
        }
    models = parse_catalog(name, payload, provider_title=provider_title or d.title)
    if not models:
        return {
            "ok": False,
            "error": f"{d.title} returned no models.",
            "http_ok": True,
        }
    return {"ok": True, "models": [m.to_dict() for m in models]}
