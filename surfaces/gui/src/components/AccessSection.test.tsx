import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { AccessSection } from "./AccessSection";

// UI chrome asserts on the English copy (setupTests.ts boots the real en catalog under
// jsdom's en-US locale). Mirrors LibraryView's load-failure vs empty-state test convention.
const EMPTY_CONNS = { connected: [], recommended: [], attention: 0 };

vi.mock("../api", () => ({
  CLOUD_CHANGED: "coworker:cloud-changed",
  getCloudStatus: vi.fn(async () => ({ signed_in: false, account: "", user_id: "" })),
  getConnectors: vi.fn(async () => []),
  getRecentChannels: vi.fn(async () => []),
  getSessionConnections: vi.fn(async () => EMPTY_CONNS),
  getSubscriptions: vi.fn(async () => []),
  setSessionConnection: vi.fn(async () => ({ ok: true })),
  subscribeChannel: vi.fn(async () => ({ ok: true })),
  unsubscribeChannel: vi.fn(async () => ({ ok: true })),
  getRoots: vi.fn(async () => []),
  addRoot: vi.fn(async () => ({ ok: true, roots: [] })),
  removeRoot: vi.fn(async () => ({ ok: true, roots: [] })),
}));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function renderOpen() {
  render(<AccessSection sessionId="sess-1" />);
  fireEvent.click(screen.getByTestId("access-toggle"));
}

describe("AccessSection — load failure vs genuine empty", () => {
  it("renders the genuine empty copy when connections resolve with an empty list", async () => {
    renderOpen();
    expect(await screen.findByText("No connectors enabled for this session.")).toBeTruthy();
    expect(screen.queryByText("Could not load connector status.")).toBeNull();
    expect(screen.queryByTestId("connectors-retry")).toBeNull();
  });

  it("shows a retryable failure (not the empty copy) when the fetch rejects", async () => {
    const { getSessionConnections } = await import("../api");
    vi.mocked(getSessionConnections).mockRejectedValueOnce(new Error("network error"));

    renderOpen();

    expect(await screen.findByText("Could not load connector status.")).toBeTruthy();
    expect(screen.queryByText("No connectors enabled for this session.")).toBeNull();
    expect(screen.getByTestId("connectors-retry")).toBeTruthy();
  });

  it("recovers real data after retrying a failed load", async () => {
    const { getSessionConnections } = await import("../api");
    vi.mocked(getSessionConnections).mockRejectedValueOnce(new Error("network error"));
    vi.mocked(getSessionConnections).mockResolvedValueOnce({
      connected: [{ connector: "github", enabled: true, detail: "acme-org" }],
      recommended: [],
      attention: 0,
    });

    renderOpen();
    expect(await screen.findByText("Could not load connector status.")).toBeTruthy();

    fireEvent.click(screen.getByTestId("connectors-retry"));

    // "Github" also appears in the header summary once a source is live, so assert on the
    // connector row's detail text instead, which is unique to the Sources list.
    expect(await screen.findByText(/acme-org/)).toBeTruthy();
    expect(screen.queryByTestId("connectors-retry")).toBeNull();
    expect(screen.queryByText("Could not load connector status.")).toBeNull();
  });
});
