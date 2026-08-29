"""The curated model matrix — the only models we actively suggest, label, and vouch for.

Keyed by the FULL routed id, exactly as the ProviderRouter receives it — including reseller
"ugly names" like ``together:zai-org/GLM-5.2`` (bare ids route to the OpenAI default). Each
entry carries the UI display label and the model's capabilities, making this the single
source of truth the capability probe and the GUI's pickers read from.

Deliberately SMALL (owner call, 2026-07-04): current-generation, agent-capable (tool-calling)
models only. It is not user-editable — users can still add any custom model string, which
falls back to the conservative heuristics in ``capabilities.py`` at their own risk of
degraded results. Ids verified against vendor/reseller catalogs on 2026-07-04; refresh the
reseller rows when catalogs rotate (they rename on every model generation).

Context windows (``context_window``, tokens) feed the GUI's context-fill meter. Entries
where the vendor spec wasn't re-checked stay ``None`` — the meter simply hides rather than
showing a made-up denominator. Values entered 2026-07-28 from vendor docs; verify alongside
the id refresh.

Resellers: Together + Fireworks + OpenRouter. TODO: add Groq entries here AND its
descriptor in ``registry.py`` once the current provider surface is tested — deliberately
deferred to bound how much needs verifying at once.

``aigw:`` rows reach OpenAI, Anthropic and Google through the shared account's Cloudflare
AI Gateway instead of one key per vendor (``aigateway_provider.py``), billed against that
account's Unified Billing credits. Their ids are Cloudflare's own ``author/model`` strings,
kept verbatim rather than translated from the vendor spelling — the author segment is what
selects the request wire. The gateway carries far more than these three labs; the narrow
scope is an owner call, see the section comment.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .base import ModelCapabilities

_AGENTIC = ModelCapabilities(
    tools=True, vision=False, parallel_tool_calls=True, streaming=True
)
# The native three (OpenAI, Anthropic, Gemini) all take PDFs directly; every
# OpenAI-compatible vendor and reseller in the matrix does not (their chat APIs have
# no inline file part — checked 2026-07-17), so those fall back via pdf_support.py.
_AGENTIC_VISION = ModelCapabilities(
    tools=True, vision=True, pdf=True, parallel_tool_calls=True, streaming=True
)
# Sees images but has no verified inline-PDF part: the compat vendors that ship a vision
# model, and everything routed through Cloudflare AI Gateway (image input confirmed on the
# wire 2026-08-23; a PDF part was never probed there, so it is not claimed). PDFs still
# work — pdf_support.py rasterizes pages and sends them as images.
_AGENTIC_IMAGE = ModelCapabilities(
    tools=True, vision=True, parallel_tool_calls=True, streaming=True
)


@dataclass(frozen=True)
class ModelEntry:
    label: str  # UI display name, e.g. "GLM-5.2 · via Together"
    caps: ModelCapabilities = _AGENTIC
    # Max context length in tokens (prompt side), for the GUI's context-fill meter.
    # None = not verified against the vendor spec yet; the meter hides.
    context_window: Optional[int] = None


MATRIX: dict[str, ModelEntry] = {
    # -- first-party ------------------------------------------------------------
    # GPT-5.6 (2026-07-09): number = generation, Sol/Terra/Luna = capability tiers.
    # Bare "gpt-5.6" aliases to Sol server-side; we list the explicit tier ids only.
    # Rolling out — accounts without access get a friendly error (providers/errors.py).
    "gpt-5.6-sol": ModelEntry("GPT-5.6 Sol · OpenAI", _AGENTIC_VISION, 400_000),
    "gpt-5.6-terra": ModelEntry("GPT-5.6 Terra · OpenAI", _AGENTIC_VISION, 400_000),
    "gpt-5.6-luna": ModelEntry("GPT-5.6 Luna · OpenAI", _AGENTIC_VISION, 400_000),
    "gpt-5.5": ModelEntry("GPT-5.5 · OpenAI", _AGENTIC_VISION, 400_000),
    # Fable 5 (2026-06-09) is GA; its Mythos 5 sibling is approved-orgs-only, so it
    # stays out of a picker meant for the public.
    "anthropic:claude-fable-5": ModelEntry(
        "Claude Fable 5 · Anthropic", _AGENTIC_VISION, 1_000_000
    ),
    "anthropic:claude-opus-4-8": ModelEntry(
        "Claude Opus 4.8 · Anthropic", _AGENTIC_VISION, 200_000
    ),
    "anthropic:claude-sonnet-4-6": ModelEntry(
        "Claude Sonnet 4.6 · Anthropic", _AGENTIC_VISION, 200_000
    ),
    "anthropic:claude-haiku-4-5": ModelEntry(
        "Claude Haiku 4.5 · Anthropic", _AGENTIC_VISION, 200_000
    ),
    # Gemini (thought signatures required in tool loops — carried via the `_gemini`
    # message sidecar, see gemini_provider.py). Reconciled against
    # https://ai.google.dev/gemini-api/docs/models on 2026-08-22: every 2.5-and-newer
    # general text+vision chat model, newest first. Deliberately excluded, because none of
    # them is a chat model this app can drive — TTS (`*-tts`), image generation
    # (`*-image`, the Nano Banana line), live/native-audio, Veo, Lyria, embeddings,
    # robotics-ER, and the specialized agents (computer-use, deep-research, antigravity).
    # Also excluded: everything the page marks shut down (2.0 Flash, 2.0 Flash-Lite,
    # gemini-3-pro-preview, gemini-3.1-flash-lite-preview).
    # Every one of these reports the same limits on its model card: 1,048,576 input /
    # 65,536 output tokens, function calling Supported.
    "gemini:gemini-3.7-flash": ModelEntry(
        "Gemini 3.7 Flash · Google", _AGENTIC_VISION, 1_048_576
    ),
    "gemini:gemini-3.6-flash": ModelEntry(
        "Gemini 3.6 Flash · Google", _AGENTIC_VISION, 1_048_576
    ),
    "gemini:gemini-3.5-flash": ModelEntry(
        "Gemini 3.5 Flash · Google", _AGENTIC_VISION, 1_048_576
    ),
    "gemini:gemini-3.5-flash-lite": ModelEntry(
        "Gemini 3.5 Flash-Lite · Google", _AGENTIC_VISION, 1_048_576
    ),
    "gemini:gemini-3.1-flash-lite": ModelEntry(
        "Gemini 3.1 Flash-Lite · Google", _AGENTIC_VISION, 1_048_576
    ),
    # The only Pro in the 3.x line is still preview-tagged, so it stays despite the rule of
    # thumb that previews don't belong in a curated list. gemini-3-flash-preview is here
    # only because the vendor page still lists it as available — it is a preview of an older
    # generation than the stable Flash models above it, and previews do get shut down
    # (gemini-3-pro-preview already has been), so it is the first row to drop on a refresh.
    "gemini:gemini-3.1-pro-preview": ModelEntry(
        "Gemini 3.1 Pro · Google", _AGENTIC_VISION, 1_048_576
    ),
    "gemini:gemini-3-flash-preview": ModelEntry(
        "Gemini 3 Flash · Google", _AGENTIC_VISION, 1_048_576
    ),
    "gemini:gemini-2.5-pro": ModelEntry(
        "Gemini 2.5 Pro · Google", _AGENTIC_VISION, 1_048_576
    ),
    "gemini:gemini-2.5-flash": ModelEntry(
        "Gemini 2.5 Flash · Google", _AGENTIC_VISION, 1_048_576
    ),
    "gemini:gemini-2.5-flash-lite": ModelEntry(
        "Gemini 2.5 Flash-Lite · Google", _AGENTIC_VISION, 1_048_576
    ),
    # Ark Responses API providers (verified 2026-08-14). BytePlus pay-as-you-go and
    # Volcengine Agent Plan intentionally use separate provider prefixes because their
    # endpoints, credentials, regions, and model catalogs are not interchangeable.
    "ark:dola-seed-evolving-latest-version": ModelEntry(
        "Dola Seed Evolving · BytePlus Ark", context_window=256_000
    ),
    "ark:dola-seed-2-1-turbo-260628": ModelEntry(
        "Dola Seed 2.1 Turbo · BytePlus Ark", context_window=256_000
    ),
    "ark-agent-plan-cn:doubao-seed-evolving": ModelEntry(
        "Doubao Seed Evolving · Volcengine Agent Plan", context_window=256_000
    ),
    "ark-agent-plan-cn:doubao-seed-2.1-turbo": ModelEntry(
        "Doubao Seed 2.1 Turbo · Volcengine Agent Plan", context_window=256_000
    ),
    # -- direct OpenAI-compatible vendors ----------------------------------------
    # Muse Spark (Meta Model API, public preview 2026-07-09): multimodal + tools via
    # their OpenAI-compat surface. Vision yes; PDFs unverified over compat — falls
    # back via pdf_support.py like the other compat vendors.
    "meta:muse-spark-1.1": ModelEntry("Muse Spark 1.1 · Meta", _AGENTIC_IMAGE),
    "zai:glm-5.2": ModelEntry("GLM-5.2 · Z AI", _AGENTIC, 128_000),
    "deepseek:deepseek-v4-flash": ModelEntry(
        "DeepSeek V4 Flash · DeepSeek", _AGENTIC, 128_000
    ),
    "deepseek:deepseek-v4-pro": ModelEntry(
        "DeepSeek V4 Pro · DeepSeek", _AGENTIC, 128_000
    ),
    "kimi:kimi-k2.6": ModelEntry("Kimi K2.6 · Moonshot", _AGENTIC, 256_000),
    "minimax:MiniMax-M2.5": ModelEntry("MiniMax M2.5 · MiniMax"),
    "qwen:qwen3-max": ModelEntry("Qwen3 Max · Alibaba", _AGENTIC, 256_000),
    "xai:grok-4.3": ModelEntry("Grok 4.3 · xAI", _AGENTIC, 256_000),
    "mistral:mistral-large-latest": ModelEntry(
        "Mistral Large · Mistral", _AGENTIC, 128_000
    ),
    # Kimi K3 through the company's NVIDIA NIM relay (nvidia.smjtools.com, per-person
    # `nvapi-` keys from the administrator). Image input works through the relay (its
    # README demonstrates a chat/completions image_url round trip); the context window
    # NIM serves was not verified, so the meter hides rather than borrowing Together's
    # 1M figure for the same model.
    "nvidia:moonshotai/kimi-k3": ModelEntry("Kimi K3 · via NVIDIA", _AGENTIC_IMAGE),
    # -- resellers (their model namespaces, verbatim) -----------------------------
    "together:thinkingmachines/Inkling": ModelEntry("Inkling · via Together"),
    "together:zai-org/GLM-5.2": ModelEntry("GLM-5.2 · via Together", _AGENTIC, 128_000),
    # Kimi K3 on Together (landed late July 2026): 1M window, native vision; PDFs
    # unverified over the compat surface (falls back via pdf_support.py, like Muse Spark).
    "together:moonshotai/Kimi-K3": ModelEntry(
        "Kimi K3 · via Together", _AGENTIC_IMAGE, 1_000_000
    ),
    "together:moonshotai/Kimi-K2.7-Code": ModelEntry(
        "Kimi K2.7 Code · via Together", _AGENTIC, 256_000
    ),
    "together:moonshotai/Kimi-K2.6": ModelEntry(
        "Kimi K2.6 · via Together", _AGENTIC, 256_000
    ),
    "together:deepseek-ai/DeepSeek-V4-Pro": ModelEntry(
        "DeepSeek V4 Pro · via Together", _AGENTIC, 128_000
    ),
    "together:meta-llama/Llama-4-Maverick-17B-128E-Instruct-FP8": ModelEntry(
        "Llama 4 Maverick · via Together", _AGENTIC, 1_000_000
    ),
    "fireworks:accounts/fireworks/models/glm-5p2": ModelEntry(
        "GLM-5.2 · via Fireworks", _AGENTIC, 128_000
    ),
    "fireworks:accounts/fireworks/models/kimi-k2p6": ModelEntry(
        "Kimi K2.6 · via Fireworks", _AGENTIC, 256_000
    ),
    "fireworks:accounts/fireworks/models/deepseek-v4-pro": ModelEntry(
        "DeepSeek V4 Pro · via Fireworks", _AGENTIC, 128_000
    ),
    "fireworks:accounts/fireworks/models/llama4-maverick-instruct-basic": ModelEntry(
        "Llama 4 Maverick · via Fireworks", _AGENTIC, 1_000_000
    ),
    # OpenRouter slugs are lowercase `<lab>/<model>` (checked against their catalog
    # 2026-07-25); same labs as above, one key for all of them.
    "openrouter:z-ai/glm-5.2": ModelEntry("GLM-5.2 · via OpenRouter", _AGENTIC, 128_000),
    "openrouter:moonshotai/kimi-k2.6": ModelEntry(
        "Kimi K2.6 · via OpenRouter", _AGENTIC, 256_000
    ),
    "openrouter:deepseek/deepseek-v4-pro": ModelEntry(
        "DeepSeek V4 Pro · via OpenRouter", _AGENTIC, 128_000
    ),
    "openrouter:meta-llama/llama-4-maverick": ModelEntry(
        "Llama 4 Maverick · via OpenRouter", _AGENTIC, 1_000_000
    ),
    # -- cloud accounts (models running in the user's own AWS/GCP) ----------------
    # Bedrock ids carry a family segment (claude/ → native Anthropic path, other/ →
    # Converse) plus AWS's own `-v<n>:<m>` version suffix. Some regions require the
    # `us.`/`eu.` cross-region inference-profile prefix — custom add-model accepts those.
    "bedrock:claude/anthropic.claude-sonnet-4-6-v1:0": ModelEntry(
        "Claude Sonnet 4.6 · AWS Bedrock", _AGENTIC_VISION, 200_000
    ),
    "bedrock:claude/anthropic.claude-haiku-4-5-v1:0": ModelEntry(
        "Claude Haiku 4.5 · AWS Bedrock", _AGENTIC_VISION, 200_000
    ),
    "bedrock:other/amazon.nova-2-pro-v1:0": ModelEntry(
        "Nova 2 Pro · AWS Bedrock", _AGENTIC, 300_000
    ),
    "bedrock:other/meta.llama4-maverick-17b-instruct-v1:0": ModelEntry(
        "Llama 4 Maverick · AWS Bedrock", _AGENTIC, 1_000_000
    ),
    "bedrock:other/mistral.mistral-large-3-v1:0": ModelEntry(
        "Mistral Large 3 · AWS Bedrock", _AGENTIC, 128_000
    ),
    # Live-verified on Converse 2026-07-26 (complete/stream/tool round trip); asked for
    # two tool calls it emits them one at a time, so parallel stays off.
    "bedrock:other/nvidia.nemotron-super-3-120b": ModelEntry(
        "Nemotron Super 3 120B · AWS Bedrock",
        ModelCapabilities(
            tools=True, vision=False, parallel_tool_calls=False, streaming=True
        ),
    ),
    # Vertex ids carry a family segment too (gemini/ and claude/ → native paths,
    # openweight/ → the MaaS OpenAI-compat endpoint, keeping the publisher segment).
    "vertex:gemini/gemini-3.1-pro-preview": ModelEntry(
        "Gemini 3.1 Pro · Vertex AI", _AGENTIC_VISION, 1_048_576
    ),
    "vertex:gemini/gemini-3.6-flash": ModelEntry(
        "Gemini 3.6 Flash · Vertex AI", _AGENTIC_VISION, 1_048_576
    ),
    "vertex:claude/claude-sonnet-4-6": ModelEntry(
        "Claude Sonnet 4.6 · Vertex AI", _AGENTIC_VISION, 200_000
    ),
    "vertex:claude/claude-haiku-4-5": ModelEntry(
        "Claude Haiku 4.5 · Vertex AI", _AGENTIC_VISION, 200_000
    ),
    "vertex:openweight/meta/llama-4-maverick-17b-128e-instruct-maas": ModelEntry(
        "Llama 4 Maverick · Vertex AI", _AGENTIC, 1_000_000
    ),
    "vertex:openweight/qwen/qwen3-coder-480b-a35b-instruct-maas": ModelEntry(
        "Qwen3 Coder · Vertex AI", _AGENTIC, 256_000
    ),
    # -- Cloudflare AI Gateway ----------------------------------------------------
    # Reached through the account's AI Gateway and billed against its prepaid Unified
    # Billing credits — no per-vendor key to hand out, and the gateway's own User
    # Insights page attributes spend per person. Ids are Cloudflare's `author/model`
    # strings verbatim (note the dots where Anthropic itself writes dashes); the author
    # segment picks the request wire, see `aigateway_provider.wire_for`.
    #
    # Scope is deliberately narrow: the three labs whose models people here actually ask
    # for, and only their text and vision models. The gateway carries a dozen more
    # authors plus Workers AI, and image/TTS/realtime models on top of that; carrying all
    # of it turned the picker into a catalog nobody could navigate. Anything dropped is
    # one matrix row away from coming back.
    #
    # Every row below was called live on 2026-08-23 and answered 200 — with a tool
    # definition attached, and for the Google rows an inline image part as well;
    # gemini-3.5-flash's logged response body carries a real `tool_calls` entry.
    #
    # The GPT-5.6 tiers only answer on the Responses wire. On chat/completions OpenAI
    # itself refuses: "Function tools with reasoning_effort are not supported for
    # gpt-5.6-sol in /v1/chat/completions." That is why `wire_for` exists.
    "aigw:openai/gpt-5.6-sol": ModelEntry(
        "GPT-5.6 Sol · via Cloudflare", _AGENTIC_IMAGE, 400_000
    ),
    "aigw:openai/gpt-5.6-terra": ModelEntry(
        "GPT-5.6 Terra · via Cloudflare", _AGENTIC_IMAGE, 400_000
    ),
    "aigw:openai/gpt-5.6-luna": ModelEntry(
        "GPT-5.6 Luna · via Cloudflare", _AGENTIC_IMAGE, 400_000
    ),
    # Opus 5 and Sonnet 5 exist only on the gateway — the direct `anthropic:` rows above
    # are still on the 4.x line. No vendor page was read for their context windows, so
    # they stay None and the GUI's fill meter hides rather than inventing a denominator.
    "aigw:anthropic/claude-opus-5": ModelEntry(
        "Claude Opus 5 · via Cloudflare", _AGENTIC_IMAGE
    ),
    "aigw:anthropic/claude-sonnet-5": ModelEntry(
        "Claude Sonnet 5 · via Cloudflare", _AGENTIC_IMAGE
    ),
    "aigw:anthropic/claude-fable-5": ModelEntry(
        "Claude Fable 5 · via Cloudflare", _AGENTIC_IMAGE, 1_000_000
    ),
    # Dashes, not the dots Cloudflare's REST API uses: on the gateway's own domain the
    # model id is forwarded to Anthropic untouched. Anthropic says so itself — "model:
    # claude-sonnet-4.6 was not found. Did you mean claude-sonnet-4-6?".
    "aigw:anthropic/claude-haiku-4-5": ModelEntry(
        "Claude Haiku 4.5 · via Cloudflare", _AGENTIC_IMAGE, 200_000
    ),
    # Gemini 3.x and up only (owner call), and note the `google-ai-studio/` author — on
    # this host `google/` answers `2008 Invalid provider`. The prefix is not decoration:
    # `/compat` needs it to pick a provider, so unlike the two wires above it is sent
    # upstream intact (`aigateway_provider.upstream_model`).
    #
    # THIS IS A SHORTER LIST THAN THE `gemini:` ROWS ABOVE, deliberately. Cloudflare's
    # Unified Billing covers only part of the line on this path, and the gateway's own log
    # says which: a `wholesale: false` entry means it declined to bill the request and
    # proxied it bare, at which point Google answers "Missing or invalid Authorization
    # header" — an error about credentials that is really about coverage. Confirmed
    # uncovered here, twice each with caching off: 3-flash, 3.1-pro, 3.5-flash,
    # 3.5-flash-lite, 3.7-flash. Re-probe before assuming that is still true.
    #
    # Two of the four keep the `-preview` suffix Google's own API still carries. That is
    # the vendor's spelling and this path forwards it verbatim; dropping it 404s.
    #
    # Both routes to Gemini are kept on purpose: the direct one is cheaper for whoever
    # has a personal Google discount and carries the full line, the gateway one is what a
    # colleague on the shared account gets. The label says which is which.
    "aigw:google-ai-studio/gemini-3.6-flash": ModelEntry(
        "Gemini 3.6 Flash · via Cloudflare", _AGENTIC_IMAGE, 1_048_576
    ),
    "aigw:google-ai-studio/gemini-3.1-pro-preview": ModelEntry(
        "Gemini 3.1 Pro · via Cloudflare", _AGENTIC_IMAGE, 1_048_576
    ),
    "aigw:google-ai-studio/gemini-3.1-flash-lite": ModelEntry(
        "Gemini 3.1 Flash-Lite · via Cloudflare", _AGENTIC_IMAGE, 1_048_576
    ),
    "aigw:google-ai-studio/gemini-3-flash-preview": ModelEntry(
        "Gemini 3 Flash · via Cloudflare", _AGENTIC_IMAGE, 1_048_576
    ),
    # THREE WAYS TO MISREAD A PROBE, all three paid for once already. Before you delete
    # a row because it "does not work", rule these out — and read the response body, not
    # the status code. The gateway's own log keeps the body under `response_head`
    # (GET /accounts/{id}/ai-gateway/gateways/{gw}/logs/{log_id}).
    #
    #   HTTP 402 means two different things, and only the body says which:
    #       "This model is not available via unified billing."   → really unavailable
    #       "Wholesale rate limit exceeded for this gateway."    → just busy
    #     The wholesale pool is shared per model and the top tiers saturate fast, so
    #     probing in a burst makes perfectly good models look dead. Go one at a time.
    #
    #   2002 "Failed to parse model output" is usually an empty completion, not a broken
    #     model: the Gemini rows think before answering and the thinking spends
    #     `max_tokens`. Give a probe 800 tokens before concluding anything.
    #
    #   "User Input Error" on a vision probe is usually the image. A 1x1 PNG is rejected
    #     outright; a real one goes through.
}


def entry_for(model: str) -> ModelEntry | None:
    return MATRIX.get(model)


def model_labels() -> dict[str, str]:
    """Full-id → display-label map, shipped to the GUI so every picker shows human names."""
    return {mid: e.label for mid, e in MATRIX.items()}


def model_context_windows() -> dict[str, int]:
    """Full-id → context-window map (verified entries only), for the GUI's fill meter."""
    return {
        mid: e.context_window for mid, e in MATRIX.items() if e.context_window
    }


def models_for_provider(provider: str) -> list[str]:
    """BARE model ids (prefix stripped) the matrix curates for a provider — feeds the
    Settings pane's suggestions and the composer picker so both stay in lockstep with the
    matrix. OpenAI entries are stored without a prefix (bare ids route to the OpenAI
    default), so its list is every un-prefixed id."""
    if provider == "openai":
        return [mid for mid in MATRIX if ":" not in mid]
    prefix = provider + ":"
    return [mid[len(prefix) :] for mid in MATRIX if mid.startswith(prefix)]


# Targets are all existing MATRIX rows (verified above) — keep this table in sync with the
# matrix: if a target id's row is ever renamed or dropped, update the row here to match.
_UTILITY_MODELS: tuple[tuple[str, str], ...] = (
    ("aigw:anthropic/", "aigw:anthropic/claude-haiku-4-5"),
    ("aigw:openai/", "aigw:openai/gpt-5.6-luna"),
    ("aigw:google-ai-studio/", "aigw:google-ai-studio/gemini-3.1-flash-lite"),
    ("anthropic:", "anthropic:claude-haiku-4-5"),
    ("gemini:gemini-", "gemini:gemini-3.5-flash-lite"),
    ("bedrock:claude/", "bedrock:claude/anthropic.claude-haiku-4-5-v1:0"),
    ("vertex:claude/", "vertex:claude/claude-haiku-4-5"),
    ("vertex:gemini/", "vertex:gemini/gemini-3.6-flash"),
)


def utility_model_for(model: str) -> str:
    """Cheap same-provider sibling for auxiliary calls (auto-titles): the ProviderRouter
    routes per call by the model string's prefix (router.py's `_provider_name`/`_client_for`),
    so handing it the sibling id serves the sibling through the session's own provider
    instance directly — no separate client or credentials needed. Longest-matching-prefix
    over `_UTILITY_MODELS`; a bare id starting `gpt-` (no provider prefix) routes to the
    OpenAI default's cheap tier. Unknown namespaces — custom endpoints, resellers, anything
    not in the table — fall back to the session's own model rather than guessing a sibling
    id that may not exist on that endpoint."""
    best_prefix, best_target = "", ""
    for prefix, target in _UTILITY_MODELS:
        if len(prefix) > len(best_prefix) and model.startswith(prefix):
            best_prefix, best_target = prefix, target
    if best_target:
        return best_target
    if model.startswith("gpt-"):
        return "gpt-5.6-luna"
    return model
