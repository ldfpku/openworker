import { createInstance } from "i18next";
import { describe, expect, it } from "vitest";
import en from "./locales/en.json";
import zh from "./locales/zh.json";

interface LocaleTree {
  [key: string]: string | LocaleTree;
}

const IMPORTANT_KEYS = [
  "settings.voice_installed",
  "settings.voice_not_installed",
  // Voice Input ships two model packs (streaming live text + the final pass that replaces it);
  // every string the pack cards and the composer's live row render is load-bearing copy.
  "settings.voice_pack_streaming",
  "settings.voice_pack_final",
  "settings.voice_pack_streaming_detail",
  "settings.voice_pack_final_detail",
  "settings.voice_pack_download_all",
  "settings.voice_pack_resume",
  "settings.voice_pack_progress",
  "settings.voice_pack_files_missing",
  "settings.voice_pack_verify",
  "settings.voice_pack_total_progress",
  "settings.voice_engine_title",
  "settings.voice_engine_detail",
  "settings.voice_legacy_present",
  "settings.voice_legacy_cleaned",
  "composer.voice.live_status",
  "composer.voice.realtime_degraded",
  "composer.err_dictation_engine",
  "personas.installed_other",
  "personas.disable_warning_other",
  "personas.tools_label",
  "personas.risk_label",
  "transcript.step.auto_allowed_tip",
  "manage.tool_asks_approval",
  "manage.id_title",
  "automations.empty_state",
  "composer.pdf_too_big",
  "composer.pdf_too_many_pages",
  "composer.pdf_unreadable",
  "composer.attach_skipped",
  "composer.folder_drop_unsupported",
  "composer.listening_sr",
  "composer.fallback_badge_tip",
  // Load-failure copy (fetch rejected ≠ genuinely empty) + the shared Retry label; each
  // section that can fail to load has its own key, and the listening header drops its
  // count while the subscription list is unknown.
  "common.retry",
  "audit.load_failed",
  "access.connectors_load_failed",
  "rail.artifacts_load_failed",
  "memory.load_failed",
  "skills.load_failed",
  "composer.skills_load_failed",
  "composer.enhance.failed",
  "composer.enhance.timed_out",
  "manage.subscriptions_load_failed",
  "manage.listening_title_uncounted",
  "settings.trust_load_failed",
  // Parked-prompt dress: the kind chip used to look up a bare English word (nowhere to
  // resolve for directory/plan/tool), and the two fixed server titles had no key at all.
  "inbox.kind.approval",
  "inbox.kind.question",
  "inbox.kind.notification",
  "inbox.kind.directory",
  "inbox.kind.plan",
  "inbox.kind.tool",
  "inbox.title_directory",
  "inbox.title_plan",
  // Says which surface answered a gate when it wasn't this app — by then the inline card is
  // already gone (it renders only while unresolved), so this line is the whole explanation.
  "transcript.resolved_via_weixin",
  "transcript.resolved_timed_out",
  "transcript.resolved_outcome_allow",
  "transcript.resolved_outcome_deny",
] as const;

const values: Record<string, Record<string, string | number>> = {
  // Sizes come from `ocw-stt`'s pack manifests at runtime, never from this file — these are
  // stand-ins shaped like what formatBytes produces for the streaming pack and for both packs.
  "settings.voice_installed": { size: "226 MiB" },
  "settings.voice_not_installed": { size: "226 MiB" },
  "settings.voice_pack_download_all": { size: "455 MiB" },
  "settings.voice_pack_progress": { done: "12 MiB", total: "226 MiB", index: 2, count: 3 },
  "settings.voice_pack_files_missing": { missing: 1, total: 3 },
  "settings.voice_pack_total_progress": { done: "120 MiB", total: "455 MiB" },
  "settings.voice_engine_detail": { engine: "sherpa-onnx 1.13.7" },
  "personas.installed_other": { count: 2 },
  "personas.disable_warning_other": { count: 2 },
  "personas.tools_label": { tools: "read_file" },
  "personas.risk_label": { risk: "read" },
  "transcript.step.auto_allowed_tip": { name: "read_file" },
  "manage.tool_asks_approval": { name: "send_message", kind: "write" },
  "manage.id_title": { id: "U123" },
  "composer.pdf_too_big": { name: "report.pdf", mb: "12.5", limit: 10 },
  "composer.pdf_too_many_pages": { name: "report.pdf", pages: 24, limit: 20 },
  "composer.pdf_unreadable": { name: "report.pdf", error: "invalid PDF" },
  "composer.attach_skipped": { names: "LICENSE, notes" },
  "composer.listening_sr": { time: "0:12" },
  "composer.fallback_badge_tip": { model: "GPT-5.6 Sol" },
  "manage.listening_title_uncounted": { title: "Slack" },
  "transcript.resolved_via_weixin": { outcome: "同意" },
};

function flatten(tree: LocaleTree, prefix = "", result: Record<string, string> = {}) {
  for (const [key, value] of Object.entries(tree)) {
    const path = prefix ? `${prefix}.${key}` : key;
    if (typeof value === "string") result[path] = value;
    else flatten(value, path, result);
  }
  return result;
}

function placeholders(value: string) {
  return [...value.matchAll(/{{\s*([\w.]+)(?:\s*,[^}]*)?\s*}}/g)]
    .map((match) => match[1])
    .sort();
}

const flatEn = flatten(en);
const flatZh = flatten(zh);

describe("locale contracts", () => {
  it("keeps English and Chinese key sets in parity", () => {
    // Chinese has a single plural category, so `*_one` variants exist only in English.
    const missingInZh = Object.keys(flatEn).filter((key) => !key.endsWith("_one") && !(key in flatZh));
    const missingInEn = Object.keys(flatZh).filter((key) => !(key in flatEn));
    expect(missingInZh, "keys missing from zh.json").toEqual([]);
    expect(missingInEn, "keys missing from en.json").toEqual([]);
  });

  it("keeps interpolation placeholders aligned between English and Chinese", () => {
    for (const key of Object.keys(flatEn)) {
      if (!(key in flatZh)) continue;
      expect(placeholders(flatZh[key]), key).toEqual(placeholders(flatEn[key]));
    }
  });

  it("defines every important runtime key in both locales", () => {
    for (const key of IMPORTANT_KEYS) {
      expect(flatEn[key], `missing English key: ${key}`).toBeTypeOf("string");
      expect(flatZh[key], `missing Chinese key: ${key}`).toBeTypeOf("string");
    }
  });

  it("fully interpolates important Chinese runtime strings", async () => {
    const instance = createInstance();
    await instance.init({
      resources: { zh: { translation: zh } },
      lng: "zh",
      fallbackLng: false,
      interpolation: { escapeValue: false },
    });

    for (const key of IMPORTANT_KEYS) {
      const rendered = instance.t(key, values[key] ?? {});
      expect(rendered, key).not.toMatch(/{{\s*[\w.]+(?:\s*,[^}]*)?\s*}}/);
    }
  });
});
