import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { SettingsView } from "./SettingsView";

const getSettings = vi.fn();

vi.mock("../api", () => ({
  getSettings: (...args: unknown[]) => getSettings(...args),
  getTrustedWorkspaces: vi.fn(async () => [] as unknown[]),
  setAutoApprove: vi.fn(async () => ({ ok: true })),
  setAutoApproveShadow: vi.fn(async () => ({ ok: true })),
  setCompactionSettings: vi.fn(async () => ({ ok: true })),
  setGuidanceSettings: vi.fn(async () => ({ ok: true })),
  setContextBar: vi.fn(async () => ({ ok: true })),
  setOnboarded: vi.fn(async () => ({ ok: true, onboarded: false })),
  setPdfSettings: vi.fn(async () => ({ ok: true })),
  setScratchBase: vi.fn(async () => ({ ok: true })),
  setSessionsPeek: vi.fn(async () => ({ ok: true })),
  setWorkspaceTrusted: vi.fn(async () => ({ ok: true })),
}));

const settings = (extra: Record<string, unknown> = {}) => ({
  scratch_base: "~/OpenWorker",
  sessions_peek: 5,
  context_bar: false,
  models: [],
  guidance_model: "",
  ...extra,
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("SettingsView — pre-flight automatic-check default", () => {
  it("is unchecked when the backend has no saved preference", async () => {
    getSettings.mockResolvedValue(settings());
    render(<SettingsView initialTab="context" />);
    const checkbox = (await screen.findByTestId("guidance-enabled")) as HTMLInputElement;
    expect(checkbox.checked).toBe(false);
  });

  it("preserves an explicitly enabled preference", async () => {
    getSettings.mockResolvedValue(settings({ guidance_enabled: true }));
    render(<SettingsView initialTab="context" />);
    const checkbox = (await screen.findByTestId("guidance-enabled")) as HTMLInputElement;
    expect(checkbox.checked).toBe(true);
  });

  it("fails closed when settings cannot be loaded", async () => {
    getSettings.mockRejectedValue(new Error("offline"));
    render(<SettingsView initialTab="context" />);
    const checkbox = (await screen.findByTestId("guidance-enabled")) as HTMLInputElement;
    expect(checkbox.checked).toBe(false);
  });
});
