"""Live model-catalog parsing — turns a provider's raw model-list response into
`CatalogModel` rows the GUI can render, with zero network and zero dependency on
`registry.py` (kept a one-way import: registry → catalog, never the reverse).

Every `parse_*` function is defensive by construction: a malformed payload (wrong shape,
missing fields, unexpected types) degrades to an empty list rather than raising — the
catalog is a best-effort convenience layer on top of the curated `matrix.py`, never a
hard dependency the app can crash on.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional

#: Providers whose model-list API we know how to call and parse. Everyone else (bedrock,
#: vertex, aigw, ollama, ark, ark-agent-plan-cn, and the oauth providers) either has no
#: such API, or one this module doesn't (yet) speak.
CATALOG_PROVIDERS = frozenset(
    {
        "openai",
        "anthropic",
        "gemini",
        "custom",
        "nvidia",
        "together",
        "fireworks",
        "openrouter",
        "zai",
        "deepseek",
        "kimi",
        "minimax",
        "qwen",
        "xai",
        "mistral",
        "meta",
    }
)


def supports_catalog(name: str) -> bool:
    return name in CATALOG_PROVIDERS


@dataclass(frozen=True)
class CatalogModel:
    id: str
    label: str
    context_window: Optional[int] = None

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "label": self.label, "context_window": self.context_window}


# -- chat-model filtering ---------------------------------------------------------

# Substrings (lowercased) that mark a listed model as something this app can't drive as
# a chat/tool-calling model: embeddings, TTS/audio, transcription, image/video
# generation, moderation, rerankers, and the specialized agents. Deliberately broad
# (substring, not exact-match) — vendors spell these many ways (`text-embedding-3`,
# `whisper-1`, `dall-e-3`, `gemini-live-2.5`, …).
_NON_CHAT_SUBSTRINGS = (
    "embed",
    "tts",
    "whisper",
    "transcri",
    "dall-e",
    "image",
    "imagen",
    "veo",
    "lyria",
    "audio",
    "realtime",
    "live",
    "moderation",
    "rerank",
    "aqa",
    "robotics",
    "computer-use",
    "deep-research",
)


def is_chat_model_id(model_id: str) -> bool:
    low = (model_id or "").lower()
    return not any(s in low for s in _NON_CHAT_SUBSTRINGS)


# -- label prettification ---------------------------------------------------------

# Token0 abbreviations that stay all-caps instead of Title-case ("GPT", not "Gpt").
_ABBREV_TOKENS = {"gpt", "glm", "llm", "vl", "moe", "fp8", "gguf"}

# A token that is purely digits and dots ("5.6", "4") reads as a version number and gets
# glued back onto token0 with a dash ("GPT-5.6"), not treated as a separate word.
_VERSION_RE = re.compile(r"^[0-9]+(?:\.[0-9]+)*$")

#: Per-provider label suffix ("GLM-5.2 · Z AI"). Providers absent here fall back to
#: `provider_title` (the descriptor's own title, or a custom endpoint's display name),
#: trimmed of any parenthetical ("xAI (Grok)" → "xAI").
LABEL_SUFFIX: dict[str, str] = {
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "gemini": "Google",
    "zai": "Z AI",
    "kimi": "Moonshot",
    "qwen": "Alibaba",
    "nvidia": "via NVIDIA",
    "together": "via Together",
    "fireworks": "via Fireworks",
    "openrouter": "via OpenRouter",
}


def _label_suffix(provider: str, provider_title: str = "") -> str:
    suffix = LABEL_SUFFIX.get(provider)
    if suffix:
        return suffix
    return (provider_title or "").split(" (", 1)[0].strip()


def pretty_model_label(model_id: str, provider: str, provider_title: str = "") -> str:
    """Derive a human label from a raw model id when the vendor's API didn't give us one
    (no `displayName`/`name` field) — e.g. `gpt-5.6-sol` → `GPT-5.6 Sol · OpenAI`,
    `moonshotai/kimi-k3` → `Kimi K3 · via NVIDIA`, `glm-5.2` → `GLM-5.2 · Z AI`."""
    tail = (model_id or "").rsplit("/", 1)[-1]
    tokens = [t for t in tail.split("-") if t]
    suffix = _label_suffix(provider, provider_title)
    if not tokens:
        return suffix or tail
    head_token = tokens[0]
    head = (
        head_token.upper()
        if head_token.lower() in _ABBREV_TOKENS
        else head_token.capitalize()
    )
    rest = tokens[1:]
    if rest and _VERSION_RE.match(rest[0]):
        head = f"{head}-{rest[0]}"
        rest = rest[1:]
    words = [head, *[t.capitalize() for t in rest]]
    body = " ".join(words)
    return f"{body} · {suffix}" if suffix else body


# -- per-vendor response parsing ---------------------------------------------------


def parse_gemini(payload: Any) -> list[CatalogModel]:
    """`{"models": [{"name": "models/gemini-3.7-flash", "displayName": "...",
    "inputTokenLimit": 1048576, "supportedGenerationMethods": ["generateContent", ...]},
    ...]}` — only chat-capable, `generateContent`-supporting rows survive."""
    out: list[CatalogModel] = []
    seen: set[str] = set()
    if not isinstance(payload, dict):
        return out
    entries = payload.get("models")
    if not isinstance(entries, list):
        return out
    for entry in entries:
        try:
            if not isinstance(entry, dict):
                continue
            methods = entry.get("supportedGenerationMethods")
            if not isinstance(methods, list) or "generateContent" not in methods:
                continue
            raw_id = str(entry.get("name") or "").strip()
            if not raw_id:
                continue
            model_id = (
                raw_id[len("models/") :] if raw_id.startswith("models/") else raw_id
            )
            if not model_id or model_id in seen or not is_chat_model_id(model_id):
                continue
            display_name = str(entry.get("displayName") or "").strip()
            label = (
                f"{display_name} · Google"
                if display_name
                else pretty_model_label(model_id, "gemini")
            )
            context_window = entry.get("inputTokenLimit")
            context_window = context_window if isinstance(context_window, int) else None
            out.append(CatalogModel(model_id, label, context_window))
            seen.add(model_id)
        except Exception:
            continue
    return out


def parse_anthropic(payload: Any) -> list[CatalogModel]:
    """`{"data": [{"id": "claude-...", "display_name": "Claude ..."}, ...]}`."""
    out: list[CatalogModel] = []
    seen: set[str] = set()
    if not isinstance(payload, dict):
        return out
    entries = payload.get("data")
    if not isinstance(entries, list):
        return out
    for entry in entries:
        try:
            if not isinstance(entry, dict):
                continue
            model_id = str(entry.get("id") or "").strip()
            if not model_id or model_id in seen:
                continue
            display_name = str(entry.get("display_name") or "").strip()
            label = (
                f"{display_name} · Anthropic"
                if display_name
                else pretty_model_label(model_id, "anthropic")
            )
            out.append(CatalogModel(model_id, label, None))
            seen.add(model_id)
        except Exception:
            continue
    return out


def parse_openai_compat(
    payload: Any, provider: str, provider_title: str = ""
) -> list[CatalogModel]:
    """`{"data": [{"id": "..."}]}` (OpenRouter adds `name`/`context_length`) or a bare
    `[{"id": "..."}]` list (some vLLM servers). Embedding/TTS/image/etc. rows are dropped."""
    out: list[CatalogModel] = []
    seen: set[str] = set()
    if isinstance(payload, dict):
        entries = payload.get("data")
    elif isinstance(payload, list):
        entries = payload
    else:
        entries = None
    if not isinstance(entries, list):
        return out
    for entry in entries:
        try:
            if not isinstance(entry, dict):
                continue
            model_id = str(entry.get("id") or "").strip()
            if not model_id or model_id in seen or not is_chat_model_id(model_id):
                continue
            name = entry.get("name")
            label = (
                name.strip()
                if isinstance(name, str) and name.strip()
                else pretty_model_label(model_id, provider, provider_title)
            )
            context_window = entry.get("context_length")
            context_window = context_window if isinstance(context_window, int) else None
            out.append(CatalogModel(model_id, label, context_window))
            seen.add(model_id)
        except Exception:
            continue
    return out


def parse_catalog(name: str, payload: Any, provider_title: str = "") -> list[CatalogModel]:
    """Dispatch to the right parser for `name`. Never raises."""
    try:
        if name == "gemini":
            return parse_gemini(payload)
        if name == "anthropic":
            return parse_anthropic(payload)
        return parse_openai_compat(payload, name, provider_title)
    except Exception:
        return []
