// Provider logo registry (UX-DECISIONS §39): official brand marks for the onboarding
// provider gallery. Most are vendored from the MIT-licensed lobe-icons set; BytePlus is
// its official website mark, used with permission; Cloudflare is the simple-icons path
// (CC0), the same source connectors/registry.tsx already draws its marks from. All stay bundled like connector assets
// (no CDN at runtime). Keys are /v1/providers names; unknown names get no mark (the gallery
// falls back to a neutral monogram). PROVIDER_ORDER is the gallery order — recognition
// first, long tail behind the scroll fold.

import anthropic from "./logos/anthropic.svg";
import openai from "./logos/openai.svg";
import gemini from "./logos/gemini.svg";
import byteplus from "./logos/byteplus.svg";
import volcengine from "./logos/volcengine.svg";
import ollama from "./logos/ollama.svg";
import bedrock from "./logos/bedrock.svg";
import vertex from "./logos/vertex.svg";
import openrouter from "./logos/openrouter.svg";
import fireworks from "./logos/fireworks.svg";
import together from "./logos/together.svg";
import zai from "./logos/zai.svg";
import kimi from "./logos/kimi.svg";
import deepseek from "./logos/deepseek.svg";
import mistral from "./logos/mistral.svg";
import qwen from "./logos/qwen.svg";
import minimax from "./logos/minimax.svg";
import xai from "./logos/xai.svg";
import meta from "./logos/meta.svg";
import cloudflare from "./logos/cloudflare.svg";
import nvidia from "./logos/nvidia.svg";

export const PROVIDER_LOGOS: Record<string, string> = {
  anthropic,
  openai,
  // The subscription provider wears the same vendor mark — it's the same models,
  // different billing (owner call 2026-08-21: no bare-letter monogram).
  "openai-codex": openai,
  gemini,
  aigw: cloudflare,
  nvidia,
  ark: byteplus,
  "ark-agent-plan-cn": volcengine,
  meta,
  ollama,
  bedrock,
  vertex,
  openrouter,
  fireworks,
  together,
  zai,
  kimi,
  deepseek,
  mistral,
  qwen,
  minimax,
  xai,
};

export const PROVIDER_ORDER = [
  "anthropic",
  "openai",
  "gemini",
  // Ahead of the direct vendors it fronts: for users behind the Great Firewall this is
  // the route that actually reaches OpenAI/Claude/Grok, and it needs one token, not six.
  "aigw",
  // Also a company route (the NVIDIA NIM relay, admin-issued keys), so it sits with
  // aigw ahead of the self-serve vendors.
  "nvidia",
  "ark",
  "ark-agent-plan-cn",
  "meta",
  "ollama",
  "bedrock",
  "vertex",
  "openrouter",
  "fireworks",
  "together",
  "zai",
  "kimi",
  "deepseek",
  "mistral",
  "qwen",
  "minimax",
  "xai",
];

// The two routes that cost nobody anything per token: the company's NVIDIA NIM relay
// (admin-issued keys, no model bill) and a model running on the user's own machine. The
// model picker and the Models checklist tag these with a quiet "Free" badge so the cheap
// choice is visible at the moment of choosing, not just in the manual.
const FREE_PROVIDERS = ["nvidia", "ollama"];

export function isFreeModel(id: string): boolean {
  return FREE_PROVIDERS.some((p) => id.startsWith(`${p}:`));
}

export function providerRank(name: string): number {
  const i = PROVIDER_ORDER.indexOf(name);
  return i === -1 ? PROVIDER_ORDER.length : i;
}
