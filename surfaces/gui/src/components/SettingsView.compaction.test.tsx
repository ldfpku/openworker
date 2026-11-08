import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { SettingsView } from "./SettingsView";

const getSettings = vi.fn();
const setCompactionSettings = vi.fn(async () => ({ ok: true }));

vi.mock("../api", () => ({
  getSettings: (...args: unknown[]) => getSettings(...args),
  // The Settings nav reads the upgradable-skill count for its badge.
  getSkillUpdates: vi.fn(async () => ({ ok: true, available_count: 0 })),
  getTrustedWorkspaces: vi.fn(async () => [] as unknown[]),
  setAutoApprove: vi.fn(async () => ({ ok: true })),
  setAutoApproveShadow: vi.fn(async () => ({ ok: true })),
  setCompactionSettings: (...args: unknown[]) => setCompactionSettings(...(args as [])),
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

describe("SettingsView — compaction card is read-only", () => {
  it("shows the fixed ratio as text and has no editable threshold/cap inputs", async () => {
    getSettings.mockResolvedValue(settings({ compaction_threshold_pct: 0.8 }));
    render(<SettingsView initialTab="context" />);

    // The read-only ratio line renders with the backend-reported percentage.
    const line = await screen.findByTestId("compaction-threshold-readonly");
    expect(line.textContent).toContain("80");

    // The old editable inputs are gone entirely.
    expect(screen.queryByTestId("compaction-threshold")).toBeNull();
    expect(screen.queryByTestId("compaction-cap")).toBeNull();

    // Nothing in the card writes a compaction setting on mount.
    expect(setCompactionSettings).not.toHaveBeenCalled();
  });

  it("falls back to the 80% default when settings cannot be loaded", async () => {
    getSettings.mockRejectedValue(new Error("offline"));
    render(<SettingsView initialTab="context" />);
    const line = await screen.findByTestId("compaction-threshold-readonly");
    expect(line.textContent).toContain("80");
  });
});
