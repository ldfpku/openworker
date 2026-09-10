// PersonaPeek — the read-only glance at a coworker: identity, capabilities, and the
// instructions it runs on (owner ask 2026-09-10: after picking a coworker there was no
// way to read what it actually is).
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { PersonaPeek } from "./PersonaPeek";

vi.mock("../api", () => ({
  getPersonaDetail: vi.fn(async (id: string) =>
    id === "missing"
      ? { ok: false, error: "unknown persona: missing" }
      : {
          id,
          name: "生产计划与排产",
          icon: "",
          tagline: "为交期负责",
          description: "排产、压瓶颈、盯齐套、复盘延期。",
          media: [],
          builtin: true,
          group: "operations",
          enabled: true,
          surfaced: true,
          default: false,
          tools: ["files", "search"],
          recommended_models: [],
          default_permission_mode: "interactive",
          requires_folder: false,
          recommends: [],
          default_connections: [],
          system_prompt: "# 你是生产计划员\n\n为交期负责。",
          source: "/state/personas-installed/production-planning/manifest.md",
        },
  ),
}));

afterEach(cleanup);

describe("PersonaPeek", () => {
  it("shows the coworker's identity, capabilities and instructions, rendered or raw", async () => {
    const onClose = vi.fn();
    const onManage = vi.fn();
    render(<PersonaPeek personaId="production-planning" onClose={onClose} onManage={onManage} />);
    expect((await screen.findByTestId("persona-peek-name")).textContent).toContain("生产计划与排产");
    expect(screen.getByTestId("persona-peek-about").textContent).toContain("排产、压瓶颈");
    expect(screen.getByText(/files · search/)).toBeTruthy();
    // Rendered markdown by default: the heading is an <h1>, not "# …" text.
    const prompt = screen.getByTestId("persona-peek-prompt");
    expect(prompt.querySelector("h1")?.textContent).toBe("你是生产计划员");
    fireEvent.click(screen.getByTestId("persona-peek-prompt-toggle"));
    expect(prompt.querySelector("pre")?.textContent).toContain("# 你是生产计划员");
    // Manage hands the id to the caller; Close closes.
    fireEvent.click(screen.getByTestId("persona-peek-manage"));
    expect(onManage).toHaveBeenCalledWith("production-planning");
    fireEvent.click(screen.getByTestId("persona-peek-close"));
    expect(onClose).toHaveBeenCalled();
  });

  it("reports a coworker that can't be loaded instead of an empty panel", async () => {
    render(<PersonaPeek personaId="missing" onClose={() => {}} />);
    expect(await screen.findByText("Could not load this coworker.")).toBeTruthy();
  });

  it("Escape closes it", async () => {
    const onClose = vi.fn();
    render(<PersonaPeek personaId="production-planning" onClose={onClose} />);
    await screen.findByTestId("persona-peek-name");
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalled();
  });
});
