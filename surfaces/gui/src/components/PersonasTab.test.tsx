// Settings → Coworkers list: status is a tag, controls are controls (audit 2026-09-13).
// The default row must keep the configure gear (its detail page is the only route to
// "clear default" / "in picker" / export / delete), the baseline row must state that it is
// always on instead of offering a switch the server would refuse, and a refused write must
// say so instead of silently reloading.
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { PersonasTab } from "./PersonasTab";
import en from "../locales/en.json";
import zh from "../locales/zh.json";

type Call = { url: string; method: string; body: any };

function stubFetch(routes: { match: string; method?: string; json: any }[]) {
  const calls: Call[] = [];
  const fn = vi.fn(async (url: string, init?: RequestInit) => {
    const method = (init?.method || "GET").toUpperCase();
    calls.push({ url, method, body: init?.body ? JSON.parse(String(init.body)) : undefined });
    for (const r of routes) {
      if (url.includes(r.match) && (!r.method || r.method === method)) {
        return { ok: true, json: async () => r.json } as Response;
      }
    }
    return { ok: true, json: async () => ({}) } as Response;
  });
  vi.stubGlobal("fetch", fn);
  return calls;
}

const base = {
  icon: "cowork",
  requires_folder: false,
  builtin: true,
  tools: [],
  surfaced: true,
  ships: true,
  group: "general",
};

// The baseline is deliberately NOT the default here: the two states are independent and each
// row has to render its own tag.
const PERSONAS = [
  { ...base, id: "cowork", name: "OpenWorker", tagline: "The generalist", enabled: true, default: false },
  { ...base, id: "ops", name: "Ops Coworker", tagline: "Operate", enabled: true, default: true },
  { ...base, id: "code", name: "Code", tagline: "Repos", enabled: false, default: false },
];

const INDEX = { personas: PERSONAS, internal: false };

function rowOf(name: string): HTMLElement {
  // Each row is `<div class="px-[18px] py-4">` wrapping the name + its controls.
  const label = screen.getByText(name);
  return label.closest("div.px-\\[18px\\]") as HTMLElement;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("PersonasTab rows", () => {
  it("gives the default row its tag AND its configure gear, but no enable switch", async () => {
    stubFetch([
      { match: "/v1/sessions", method: "GET", json: { sessions: [] } },
      { match: "/v1/personas", method: "GET", json: INDEX },
    ]);
    render(<PersonasTab onOpenPersona={() => {}} />);
    await screen.findByText("Ops Coworker");

    const row = rowOf("Ops Coworker");
    expect(within(row).getByTestId("persona-default-tag").textContent).toBe("Default");
    expect(within(row).getByTestId("persona-configure-ops")).toBeTruthy();
    expect(within(row).queryByRole("switch")).toBeNull();
  });

  it("opens the detail page from the default row's gear", async () => {
    stubFetch([
      { match: "/v1/sessions", method: "GET", json: { sessions: [] } },
      { match: "/v1/personas", method: "GET", json: INDEX },
    ]);
    const opened: string[] = [];
    render(<PersonasTab onOpenPersona={(id) => opened.push(id)} />);
    await screen.findByText("Ops Coworker");

    fireEvent.click(screen.getByTestId("persona-configure-ops"));
    expect(opened).toEqual(["ops"]);
  });

  it("states that the baseline is always on instead of offering a switch, and keeps its gear", async () => {
    stubFetch([
      { match: "/v1/sessions", method: "GET", json: { sessions: [] } },
      { match: "/v1/personas", method: "GET", json: INDEX },
    ]);
    render(<PersonasTab onOpenPersona={() => {}} />);
    await screen.findByText("OpenWorker");

    const row = rowOf("OpenWorker");
    expect(within(row).getByTestId("persona-baseline-tag").textContent).toBe("Always on");
    expect(within(row).queryByRole("switch")).toBeNull();
    expect(within(row).queryByTestId("persona-default-tag")).toBeNull();
    expect(within(row).getByTestId("persona-configure-cowork")).toBeTruthy();
  });

  it("still gives an ordinary coworker its enable switch", async () => {
    stubFetch([
      { match: "/v1/sessions", method: "GET", json: { sessions: [] } },
      { match: "/v1/personas", method: "GET", json: INDEX },
    ]);
    render(<PersonasTab onOpenPersona={() => {}} />);
    await screen.findByText("Code");

    const toggle = within(rowOf("Code")).getByRole("switch");
    expect(toggle.getAttribute("aria-checked")).toBe("false");
  });

  it("surfaces the server's reason when a write is refused", async () => {
    const calls = stubFetch([
      {
        match: "/v1/personas/code",
        method: "POST",
        json: { ok: false, error: "nope, not allowed" },
      },
      { match: "/v1/sessions", method: "GET", json: { sessions: [] } },
      { match: "/v1/personas", method: "GET", json: INDEX },
    ]);
    render(<PersonasTab onOpenPersona={() => {}} />);
    await screen.findByText("Code");

    fireEvent.click(within(rowOf("Code")).getByRole("switch"));

    await waitFor(() => {
      expect(screen.getByTestId("persona-error-code").textContent).toBe("nope, not allowed");
    });
    expect(calls.some((c) => c.method === "POST" && c.url.includes("/v1/personas/code"))).toBe(true);
  });

  it("translates a refusal that carries a code instead of printing the server's English", async () => {
    stubFetch([
      {
        match: "/v1/personas/code",
        method: "POST",
        json: {
          ok: false,
          code: "default_locked",
          error: "this coworker is the default for new sessions — clear the default first",
        },
      },
      { match: "/v1/sessions", method: "GET", json: { sessions: [] } },
      { match: "/v1/personas", method: "GET", json: INDEX },
    ]);
    render(<PersonasTab onOpenPersona={() => {}} />);
    await screen.findByText("Code");

    fireEvent.click(within(rowOf("Code")).getByRole("switch"));

    await waitFor(() => {
      // The catalog string, NOT the server's prose — this app's primary UI is Chinese.
      expect(screen.getByTestId("persona-error-code").textContent).toBe(
        en.personas.refused_default_locked,
      );
    });
  });

  it("shows both status tags out of the box, where the baseline IS the default", async () => {
    // DEFAULT_PERSONA_ID is the baseline, so this is every fresh install. The two tags say
    // different things: "Default" is a pointer that can move, "Always on" is the floor it
    // falls back to — and only the second names the one control that hides it.
    const fresh = PERSONAS.map((p) =>
      p.id === "cowork" ? { ...p, default: true } : { ...p, default: false },
    );
    stubFetch([
      { match: "/v1/sessions", method: "GET", json: { sessions: [] } },
      { match: "/v1/personas", method: "GET", json: { personas: fresh, internal: false } },
    ]);
    render(<PersonasTab onOpenPersona={() => {}} />);
    await screen.findByText("OpenWorker");

    const row = rowOf("OpenWorker");
    expect(within(row).getByTestId("persona-default-tag").textContent).toBe("Default");
    expect(within(row).getByTestId("persona-baseline-tag").textContent).toBe("Always on");
    expect(within(row).queryByRole("switch")).toBeNull();
    expect(within(row).getByTestId("persona-configure-cowork")).toBeTruthy();
  });
});

// i18n.test.ts already enforces whole-catalog parity; this is the local reminder that the
// lifecycle vocabulary added in this pass has to exist in BOTH catalogs (zh is the owner's
// primary UI language), placeholders included.
describe("persona lifecycle locale keys", () => {
  const NEW_KEYS = [
    "persona.clear_default",
    "persona.clear_default_tip",
    "persona.baseline_tip",
    "personas.baseline_tag",
    "personas.update_failed",
    "persona.default_locked_tip",
    "persona.enable_first_tip",
    "personas.refused_baseline_locked",
    "personas.refused_default_locked",
    "personas.refused_unknown_persona",
  ];

  const at = (tree: Record<string, any>, path: string) =>
    path.split(".").reduce<any>((node, key) => node?.[key], tree);

  it("defines every new key in English and Chinese", () => {
    for (const path of NEW_KEYS) {
      expect(at(en, path), `en: ${path}`).toBeTypeOf("string");
      expect(at(zh, path), `zh: ${path}`).toBeTypeOf("string");
    }
  });

  it("names the baseline in both clear-default tips", () => {
    expect(at(en, "persona.clear_default_tip")).toContain("{{name}}");
    expect(at(zh, "persona.clear_default_tip")).toContain("{{name}}");
  });
});
