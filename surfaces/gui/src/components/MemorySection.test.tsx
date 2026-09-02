import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemorySection } from "./MemorySection";

// UI chrome asserts on the English copy (setupTests.ts boots the real en catalog under
// jsdom's en-US locale). Mirrors LibraryView's load-failure vs empty-state test convention.
const SETTINGS = { enabled: true, user_rules: "" };
const ENTRY = {
  id: 1,
  scope: "user",
  content: "Prefers dark mode.",
  summary: "dark mode",
  created_at: "2026-08-01T00:00:00Z",
};

vi.mock("../api", () => ({
  getMemorySettings: vi.fn(async () => SETTINGS),
  setMemorySettings: vi.fn(async () => SETTINGS),
  getMemory: vi.fn(async () => []),
  updateMemory: vi.fn(async () => ({ ok: true })),
  deleteMemory: vi.fn(async () => ({ ok: true })),
  deleteAllMemory: vi.fn(async () => ({ ok: true, deleted: 0 })),
  MEMORY_CHANGED: "coworker:memory-changed",
}));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("MemorySection — load failure vs genuine empty", () => {
  it("renders the genuine empty copy when the list resolves empty", async () => {
    render(<MemorySection />);
    expect(await screen.findByTestId("memory-empty")).toBeTruthy();
    expect(screen.queryByText("Could not load memory.")).toBeNull();
    expect(screen.queryByTestId("memory-retry")).toBeNull();
  });

  it("shows a retryable failure (not the empty copy) when the fetch rejects", async () => {
    const { getMemory } = await import("../api");
    vi.mocked(getMemory).mockRejectedValueOnce(new Error("network error"));

    render(<MemorySection />);

    expect(await screen.findByText("Could not load memory.")).toBeTruthy();
    expect(screen.queryByTestId("memory-empty")).toBeNull();
    expect(screen.getByTestId("memory-retry")).toBeTruthy();
  });

  it("recovers real data after retrying a failed load", async () => {
    const { getMemory } = await import("../api");
    vi.mocked(getMemory).mockRejectedValueOnce(new Error("network error"));
    vi.mocked(getMemory).mockResolvedValueOnce([ENTRY]);

    render(<MemorySection />);
    expect(await screen.findByText("Could not load memory.")).toBeTruthy();

    fireEvent.click(screen.getByTestId("memory-retry"));

    expect(await screen.findByText("Prefers dark mode.")).toBeTruthy();
    expect(screen.queryByTestId("memory-retry")).toBeNull();
    expect(screen.queryByText("Could not load memory.")).toBeNull();
  });
});
