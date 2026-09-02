// TrustedWorkspacesCard isn't exported on its own (only SettingsView is), and it mounts on
// the default "appearance" tab alongside a handful of other getSettings()-backed cards — so
// this renders the whole SettingsView with a full ../api mock, same as the real page would.
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { SettingsView } from "./SettingsView";

vi.mock("../api", () => ({
  getSettings: vi.fn(async () => ({
    scratch_base: "~/OpenWorker",
    sessions_peek: 5,
    context_bar: false,
  })),
  // Default: a genuine empty list, same shape getTrustedWorkspaces() resolves with when the
  // backend has nothing to report (not a fetch failure).
  getTrustedWorkspaces: vi.fn(async () => [] as unknown[]),
  setAutoApprove: vi.fn(async () => ({ ok: true })),
  setAutoApproveShadow: vi.fn(async () => ({ ok: true })),
  setCompactionSettings: vi.fn(async () => ({ ok: true })),
  setContextBar: vi.fn(async () => ({ ok: true })),
  setOnboarded: vi.fn(async () => ({ ok: true, onboarded: false })),
  setPdfSettings: vi.fn(async () => ({ ok: true })),
  setScratchBase: vi.fn(async () => ({ ok: true })),
  setSessionsPeek: vi.fn(async () => ({ ok: true })),
  setWorkspaceTrusted: vi.fn(async () => ({ ok: true })),
}));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("SettingsView — trusted workspaces load failure vs genuine empty state", () => {
  it("renders the empty-state copy when the fetch resolves with no workspaces", async () => {
    render(<SettingsView />);
    expect(await screen.findByText("No workspaces are trusted.")).toBeTruthy();
  });

  it("shows the failure copy (not the empty-state copy) when the fetch rejects", async () => {
    const { getTrustedWorkspaces } = await import("../api");
    vi.mocked(getTrustedWorkspaces).mockRejectedValueOnce(new Error("network down"));

    render(<SettingsView />);

    expect(await screen.findByText("Could not load trusted workspaces.")).toBeTruthy();
    expect(screen.queryByText("No workspaces are trusted.")).toBeNull();
  });

  it("recovers the real list on Retry once the API succeeds again", async () => {
    const { getTrustedWorkspaces } = await import("../api");
    vi.mocked(getTrustedWorkspaces).mockRejectedValueOnce(new Error("network down"));
    vi.mocked(getTrustedWorkspaces).mockResolvedValueOnce([
      { workspace: "/Users/dev/project", exists: true, requested_commands: ["npm test"], trusted: true, required: false },
    ]);

    render(<SettingsView />);
    expect(await screen.findByText("Could not load trusted workspaces.")).toBeTruthy();

    fireEvent.click(screen.getByTestId("trusted-workspaces-retry"));

    expect(await screen.findByText("/Users/dev/project")).toBeTruthy();
    expect(screen.queryByText("Could not load trusted workspaces.")).toBeNull();
    expect(screen.queryByTestId("trusted-workspaces-retry")).toBeNull();
  });
});
