import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { PersonaView } from "./PersonaView";
import en from "../locales/en.json";

// A hermetic fetch stub routing by URL substring + method. Records calls so tests can assert POSTs.
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

const DETAIL = {
  id: "ops",
  name: "Ops Coworker",
  icon: "🛠️",
  tagline: "Operate and investigate",
  description: "A careful, methodical operations engineer.",
  media: [],
  builtin: true,
  group: "general",
  enabled: true,
  surfaced: true,
  default: false,
  tools: ["files", "search", "shell"],
  recommended_models: ["claude-opus-4-8", "gpt-5.5"],
  default_permission_mode: "interactive",
  workspace: "deliverable",
  recommends: [
    { kind: "connector", ref: "github", reason: "confirm deploys", tier: "core", connected: true },
    { kind: "connector", ref: "datadog", reason: "pull alerts", tier: "core", connected: false },
    { kind: "mcp", ref: "filesystem", reason: "read runbooks", tier: "optional", connected: false },
  ],
  default_connections: [
    { connector: "slack", enabled: true, connected: true },
    { connector: "datadog", enabled: false, connected: false },
  ],
};

const CONNECTORS = {
  connectors: [
    { name: "github", title: "GitHub", logo: "github", brand_color: "#1f2328" },
    { name: "slack", title: "Slack", logo: "slack", brand_color: "#611f69" },
    { name: "datadog", title: "Datadog", logo: "datadog", brand_color: "#632ca6" },
  ],
};

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("PersonaView", () => {
  it("renders the persona detail (identity, tools, recommends + connect state) from the endpoint", async () => {
    stubFetch([
      { match: "/v1/personas/ops", method: "GET", json: DETAIL },
      { match: "/v1/connectors", method: "GET", json: CONNECTORS },
    ]);
    render(<PersonaView personaId="ops" />);

    expect(await screen.findByText("Ops Coworker")).toBeTruthy();
    expect(screen.getByText("Operate and investigate")).toBeTruthy();
    expect(screen.getByText("A careful, methodical operations engineer.")).toBeTruthy();
    // tool calls sit behind a collapsed Advanced disclosure (UX-035)
    expect(screen.queryByText(/shell/)).toBeNull();
    fireEvent.click(screen.getByTestId("tool-calls-disclosure"));
    expect(screen.getByText(/files · search · shell/)).toBeTruthy();
    // a connected row shows the Ready chip; unconnected ones offer Connect/Add
    expect(screen.getAllByText(/Ready/).length).toBeGreaterThan(0);
    expect(screen.getByText("Connect")).toBeTruthy(); // datadog (core, not connected)
    expect(screen.getByText("Add")).toBeTruthy(); // filesystem (mcp, not connected)
    // defaults footer
    expect(screen.getByText("claude-opus-4-8")).toBeTruthy();
  });

  it("toggling a default connection POSTs /connections and applies the returned defaults", async () => {
    const calls = stubFetch([
      { match: "/v1/personas/ops", method: "GET", json: DETAIL },
      { match: "/v1/connectors", method: "GET", json: CONNECTORS },
      {
        match: "/v1/personas/ops/connections",
        method: "POST",
        json: {
          ok: true,
          default_connections: [
            { connector: "slack", enabled: false, connected: true },
            { connector: "datadog", enabled: false, connected: false },
          ],
        },
      },
    ]);
    render(<PersonaView personaId="ops" />);
    await screen.findByText("Ops Coworker");

    // Switches in DOM order: [0] persona Enable, then the default-connection toggles. Slack is the
    // checked+enabled default; datadog is disabled (not connected). Target the last checked+enabled
    // switch — the Slack default — and flip it off.
    const switches = screen.getAllByRole("switch");
    const candidates = switches.filter(
      (s) => s.getAttribute("aria-checked") === "true" && !(s as HTMLButtonElement).disabled,
    );
    fireEvent.click(candidates[candidates.length - 1]);

    await waitFor(() => {
      const post = calls.find(
        (c) => c.method === "POST" && c.url.includes("/v1/personas/ops/connections"),
      );
      expect(post).toBeTruthy();
      expect(post!.body).toMatchObject({ connector: "slack", enabled: false });
    });
  });

  it("toggling Enable POSTs /enable", async () => {
    const calls = stubFetch([
      { match: "/v1/personas/ops", method: "GET", json: DETAIL },
      { match: "/v1/connectors", method: "GET", json: CONNECTORS },
      { match: "/v1/personas/ops/enable", method: "POST", json: { ok: true } },
    ]);
    render(<PersonaView personaId="ops" />);
    await screen.findByText("Ops Coworker");

    // The enable switch is the first one in DOM order (identity header).
    const enableToggle = screen.getAllByRole("switch")[0];
    fireEvent.click(enableToggle);

    await waitFor(() => {
      const post = calls.find((c) => c.method === "POST" && c.url.includes("/v1/personas/ops/enable"));
      expect(post).toBeTruthy();
      expect(post!.body).toMatchObject({ enabled: false });
    });
  });
});

// The default is a POINTER whose zero value is the baseline (registry contract). The page has
// to show where it currently points AND offer the way back — the old single button did
// neither: it turned into a disabled "Default for new sessions" label with no reverse
// (audit 2026-09-13).
describe("PersonaView default pointer", () => {
  const routes = (detail: any, extra: { match: string; method?: string; json: any }[] = []) => [
    ...extra,
    { match: `/v1/personas/${detail.id}`, method: "GET", json: detail },
    { match: "/v1/connectors", method: "GET", json: CONNECTORS },
  ];

  it("offers Clear default on a non-baseline default and POSTs {default:false}", async () => {
    const calls = stubFetch(
      routes({ ...DETAIL, default: true }, [
        { match: "/v1/personas/ops", method: "POST", json: { ok: true } },
      ]),
    );
    render(<PersonaView personaId="ops" />);
    await screen.findByText("Ops Coworker");

    expect(screen.getByTestId("persona-default-status").textContent).toBe(
      "Default for new sessions",
    );
    expect(screen.queryByTestId("persona-make-default")).toBeNull();
    const clear = screen.getByTestId("persona-clear-default") as HTMLButtonElement;
    expect(clear.disabled).toBe(false);
    // The tip names the baseline the way the picker does, from first paint — a second
    // request for its backend name only made the tip say two different things depending on
    // timing, and settle on the less localized one (audit 2026-09-13).
    expect(clear.title).toBe(
      "New sessions, inbound DMs and the disabled-coworker fallback go back to OpenWorker (general).",
    );

    fireEvent.click(clear);
    await waitFor(() => {
      const post = calls.find(
        (c) => c.method === "POST" && c.url.endsWith("/v1/personas/ops"),
      );
      expect(post).toBeTruthy();
      expect(post!.body).toEqual({ default: false });
    });
  });

  it("make default stays one click, even for a disabled coworker", async () => {
    const calls = stubFetch(
      routes({ ...DETAIL, enabled: false, default: false }, [
        { match: "/v1/personas/ops", method: "POST", json: { ok: true } },
      ]),
    );
    render(<PersonaView personaId="ops" />);
    await screen.findByText("Ops Coworker");

    const make = screen.getByTestId("persona-make-default") as HTMLButtonElement;
    expect(make.disabled).toBe(false); // set_default enables as it goes
    fireEvent.click(make);

    await waitFor(() => {
      const post = calls.find(
        (c) => c.method === "POST" && c.url.endsWith("/v1/personas/ops"),
      );
      expect(post!.body).toEqual({ default: true });
    });
  });

  it("keeps the enable switch live on a default that somehow arrived disabled", async () => {
    stubFetch(routes({ ...DETAIL, enabled: false, default: true }));
    render(<PersonaView personaId="ops" />);
    await screen.findByText("Ops Coworker");

    const enable = screen.getAllByRole("switch")[0] as HTMLButtonElement;
    expect(enable.getAttribute("aria-checked")).toBe("false");
    expect(enable.disabled).toBe(false); // otherwise it is unrecoverable
  });

  it("locks the enable switch on an enabled default (clear the default first)", async () => {
    stubFetch(routes({ ...DETAIL, enabled: true, default: true }));
    render(<PersonaView personaId="ops" />);
    await screen.findByText("Ops Coworker");

    expect((screen.getAllByRole("switch")[0] as HTMLButtonElement).disabled).toBe(true);
  });

  it("gives the baseline a status tag, no enable switch and no Clear default", async () => {
    const baseline = {
      ...DETAIL,
      id: "cowork",
      name: "OpenWorker",
      enabled: true,
      default: true,
      recommends: [],
      default_connections: [],
    };
    stubFetch(routes(baseline));
    render(<PersonaView personaId="cowork" />);
    await screen.findByTestId("persona-baseline-tag");

    expect(screen.queryAllByRole("switch")).toHaveLength(0);
    expect(screen.getByTestId("persona-baseline-tag").textContent).toBe("Always on");
    // Nothing to clear to: the baseline IS the pointer's zero value.
    expect(screen.queryByTestId("persona-clear-default")).toBeNull();
    expect(screen.getByTestId("persona-default-status")).toBeTruthy();
    // …but "Show in picker" stays interactive — that is the documented way to hide it.
    expect((screen.getByTestId("persona-surfaced") as HTMLInputElement).disabled).toBe(false);
  });

  it("puts the lock explanation somewhere it can actually be hovered", async () => {
    // Chromium (WebView2 — the shipping platform) dispatches no hover to a DISABLED form
    // control, so a `title` on the checkbox or on the Toggle's <button> is never seen. It
    // rides on the enclosing label / wrapper instead (audit 2026-09-13).
    stubFetch(routes({ ...DETAIL, enabled: true, default: true }));
    render(<PersonaView personaId="ops" />);
    await screen.findByText("Ops Coworker");

    const box = screen.getByTestId("persona-surfaced") as HTMLInputElement;
    expect(box.disabled).toBe(true);
    expect(box.title).toBe(""); // not on the dead element…
    expect((box.closest("label") as HTMLElement).title).toBe(en.persona.default_locked_tip);

    const enable = screen.getAllByRole("switch")[0] as HTMLButtonElement;
    expect(enable.disabled).toBe(true);
    expect(enable.title).toBe("");
    expect((enable.parentElement as HTMLElement).title).toBe(en.persona.default_locked_tip);
  });

  it("says a refusal out loud, and not in the colour of a success line", async () => {
    stubFetch(
      routes({ ...DETAIL, default: false }, [
        {
          match: "/v1/personas/ops",
          method: "POST",
          json: { ok: false, code: "default_locked", error: "english prose" },
        },
      ]),
    );
    render(<PersonaView personaId="ops" />);
    await screen.findByText("Ops Coworker");

    fireEvent.click(screen.getByTestId("persona-surfaced"));

    const msg = await screen.findByTestId("persona-msg");
    expect(msg.textContent).toBe(en.personas.refused_default_locked); // localized, not prose
    expect(msg.className).toContain("text-warnInk"); // …and not the export success grey
  });
});
