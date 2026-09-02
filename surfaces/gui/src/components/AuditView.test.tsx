import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { AuditView } from "./AuditView";

// UI chrome asserts on the English copy (setupTests.ts boots the real en catalog under
// jsdom's en-US locale), while event fields come straight from the mocked API data.
const EVENTS = [
  {
    id: 1,
    timestamp: "2026-08-27T00:00:00Z",
    session_id: "sess-1",
    agent: "cowork",
    workspace: "default",
    connector: "gmail",
    tool: "send_email",
    stage: "done",
    status: "ok",
    approval: "auto",
    args: { to: "a@example.com" },
    result_preview: "sent",
    reason: "",
    resource: "",
  },
];

vi.mock("../api", () => ({
  getAudit: vi.fn(async () => EVENTS),
}));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("AuditView — load failure vs empty state", () => {
  it("renders audit events on a successful fetch", async () => {
    render(<AuditView />);
    expect(await screen.findByText("send_email")).toBeTruthy();
    expect(screen.queryByText("No audit events yet.")).toBeNull();
    expect(screen.queryByText("Could not load audit events.")).toBeNull();
  });

  it("shows the genuine empty-state copy when the fetch resolves with no events", async () => {
    const { getAudit } = await import("../api");
    vi.mocked(getAudit).mockResolvedValueOnce([]);

    render(<AuditView />);
    expect(await screen.findByText("No audit events yet.")).toBeTruthy();
    expect(screen.queryByText("Could not load audit events.")).toBeNull();
  });

  it("shows a distinct failure state (not the empty-state copy) when the fetch rejects, and recovers via retry", async () => {
    const { getAudit } = await import("../api");
    vi.mocked(getAudit).mockRejectedValueOnce(new Error("network down"));

    render(<AuditView />);

    expect(await screen.findByText("Could not load audit events.")).toBeTruthy();
    expect(screen.queryByText("No audit events yet.")).toBeNull();

    // Next call (the retry) resolves with real data — default mock impl applies again
    // since the rejection above was a one-time override.
    fireEvent.click(screen.getByTestId("audit-retry"));

    expect(await screen.findByText("send_email")).toBeTruthy();
    expect(screen.queryByText("Could not load audit events.")).toBeNull();
    expect(screen.queryByTestId("audit-retry")).toBeNull();
  });
});
