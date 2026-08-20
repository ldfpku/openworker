// UX-015 (§33): tool calls render as English one-liners. The model does NOT emit a purpose
// per call — the stream is name+args+result — so the sentence is synthesized here from
// per-tool templates. `run_shell` is the exception: its optional `description` argument is
// model-written intent and is preferred when present. Fallback: "Used <tool> — <short args>".

import { shortArgs } from "./components/ApprovalCard";
import i18n from "./i18n";

// A one-line sentence in three segments so the UI can emphasize the object:
// "Read " + <b>runbook.md</b> + " from the shared folder".
export interface HumanLine {
  pre: string;
  obj?: string;
  post?: string;
}

// i18n.t() returns undefined before init() (bare unit tests call these helpers without
// initLocale(); the app always inits in main.tsx). Mirror react-i18next's graceful
// fallback: return the English key itself, with {{placeholders}} interpolated.
const t = (key: string, opts?: Record<string, unknown>): string =>
  i18n.isInitialized
    ? i18n.t(key, opts)
    : key.replace(/\{\{(\w+)\}\}/g, (_, v: string) => String(opts?.[v] ?? ""));

const trunc = (s: string, n: number) => (s.length > n ? s.slice(0, n - 1) + "…" : s);
const baseName = (p: string) => p.replace(/\/+$/, "").split("/").pop() || p;

// send_message targets are "platform:chat" or "platform:chat:thread" — show the platform
// by name and the last human-ish segment of the chat id.
function messageTarget(target: string): { platform: string; tail: string } {
  const [platform, ...rest] = String(target).split(":");
  const chat = rest[0] || "";
  const tail = chat.includes("/") ? chat.split("/").pop() || chat : chat;
  const names: Record<string, string> = { slack: "Slack", telegram: "Telegram" };
  return { platform: names[platform] || platform, tail };
}

export function humanizeTool(name: string, args: any): HumanLine {
  const a = args && typeof args === "object" ? args : {};
  switch (name) {
    case "run_shell": {
      const cmd = trunc(String(a.command ?? ""), 60);
      const desc = typeof a.description === "string" && a.description.trim() ? a.description.trim() : "";
      const pre = a.run_in_background ? t("Started in the background: ") : t("Ran ");
      return {
        pre,
        obj: cmd,
        ...(desc ? { post: t(" — {{desc}}", { desc: `${desc.charAt(0).toLowerCase()}${desc.slice(1)}` }) } : {}),
      };
    }
    case "shell_task_output":
      return { pre: t("Checked on a background command") };
    case "shell_task_kill":
      return { pre: t("Stopped a background command") };
    case "read_file":
      return { pre: t("Read "), obj: baseName(String(a.path ?? t("a file"))) };
    case "write_file":
      return { pre: t("Wrote "), obj: baseName(String(a.path ?? t("a file"))) };
    case "replace_in_file":
    case "apply_patch":
    case "apply_unified_diff":
      return { pre: t("Edited "), obj: a.path ? baseName(String(a.path)) : t("files") };
    case "grep":
      return { pre: t("Searched the code for "), obj: `“${trunc(String(a.pattern ?? ""), 40)}”` };
    case "git_log":
      return { pre: t("Looked through recent git history") };
    case "todo_write": {
      // `todos` is current; `items` renders histories from before the rename (the old
      // key breaks Together's GLM-5.2 chat template — see coworker/tools/todo.py).
      const items = Array.isArray(a.todos) ? a.todos : Array.isArray(a.items) ? a.items : [];
      if (items.length === 1) {
        const it = items[0] || {};
        const status = String(it.status || "").replace(/_/g, " ");
        return {
          pre: t("Updated the plan — "),
          obj: `“${trunc(String(it.content ?? ""), 70)}”`,
          ...(status ? { post: t(" → {{status}}", { status: t(status) }) } : {}),
        };
      }
      return { pre: t("Updated the plan — {{count}} items", { count: items.length }) };
    }
    case "send_message": {
      const { platform, tail } = messageTarget(String(a.target ?? ""));
      if (!tail) return { pre: t("Sent a message") };
      return { pre: t("Sent a {{platform}} message to ", { platform }), obj: tail };
    }
    case "web_search":
      return { pre: t("Searched the web — "), obj: `“${trunc(String(a.query ?? ""), 60)}”` };
    case "web_fetch": {
      let host = String(a.url ?? "");
      try {
        host = new URL(host).host || host;
      } catch {
        /* keep raw */
      }
      return { pre: t("Read a web page — "), obj: trunc(host, 50) };
    }
    case "explore":
      return { pre: t("Sent a sub-agent to explore — "), obj: `“${trunc(String(a.task ?? a.prompt ?? ""), 60)}”` };
    case "load_skill":
      // SKILLS-SPEC §4.1 #4 — the trust line: the transcript always shows the moment a
      // skill's instructions were picked up, model-invoked or forced via /skill.
      return { pre: t("Used skill: "), obj: String(a.name ?? "") };
    case "ask_user":
      return { pre: t("Asked you a question") };
    case "propose_plan":
      return { pre: t("Proposed a plan") };
    case "request_directory":
      return { pre: t("Asked for folder access — "), obj: String(a.path ?? "") };
    default: {
      const rest = trunc(shortArgs(a), 80);
      return { pre: t("Used {{name}}", { name }), ...(rest ? { post: t(" — {{rest}}", { rest }) } : {}) };
    }
  }
}

// The approval card's headline (§35): the ask, phrased as the action being decided.
// run_shell leads with the model's own description ("Run a command — fetch stock data").
export function humanizeApprovalTitle(name: string, args: any): HumanLine {
  const a = args && typeof args === "object" ? args : {};
  switch (name) {
    case "write_file":
      return { pre: t("Write "), obj: baseName(String(a.path ?? t("a file"))) };
    case "replace_in_file":
    case "apply_patch":
    case "apply_unified_diff":
      return { pre: t("Edit "), obj: a.path ? baseName(String(a.path)) : t("files") };
    case "run_shell": {
      const desc = typeof a.description === "string" && a.description.trim() ? a.description.trim() : "";
      return {
        pre: t("Run a command"),
        ...(desc ? { post: t(" — {{desc}}", { desc: `${desc.charAt(0).toLowerCase()}${desc.slice(1)}` }) } : {}),
      };
    }
    case "send_message": {
      const { tail } = messageTarget(String(a.target ?? ""));
      return tail ? { pre: t("Send a message to "), obj: tail } : { pre: t("Send a message") };
    }
    case "send_file": {
      const { tail } = messageTarget(String(a.target ?? ""));
      return tail ? { pre: t("Send a file to "), obj: tail } : { pre: t("Send a file") };
    }
    case "create_scheduled_task":
      return a.title
        ? { pre: t("Create the automation "), obj: `“${trunc(String(a.title), 60)}”` }
        : { pre: t("Create an automation") };
    case "save_skill":
      // SKILLS-SPEC §5.2/§7: "Add", never "install"; destination is "your skills".
      return a.name
        ? { pre: t("Add skill "), obj: String(a.name), post: t(" to your skills") }
        : { pre: t("Add a skill to your skills") };
    default:
      return { pre: t("Use {{name}}", { name }) };
  }
}

// Approvals with no executed tool call (typically declined): the ask, phrased as intent.
export function humanizeAsk(name: string, args: any): HumanLine {
  const a = args && typeof args === "object" ? args : {};
  switch (name) {
    case "run_shell":
      return { pre: t("Wanted to run "), obj: trunc(String(a.command ?? ""), 60) };
    case "write_file":
      return { pre: t("Wanted to write "), obj: baseName(String(a.path ?? t("a file"))) };
    case "replace_in_file":
    case "apply_patch":
    case "apply_unified_diff":
      return { pre: t("Wanted to edit "), obj: a.path ? baseName(String(a.path)) : t("files") };
    case "send_message": {
      const { platform, tail } = messageTarget(String(a.target ?? ""));
      if (!tail) return { pre: t("Wanted to send a message") };
      return { pre: t("Wanted to message "), obj: tail, post: t(" on {{platform}}", { platform }) };
    }
    default:
      return { pre: t("Wanted to use {{name}}", { name }) };
  }
}
