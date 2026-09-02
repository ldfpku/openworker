import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { ListeningSessionsBlock } from "./ManageTabs";
import type { Connector } from "../api";

// Scoped to ListeningSessionsBlock (Integrations ▸ Messaging routing's per-connector
// "sessions listening" list) — the minimal renderable unit around getSubscriptions.
// UI chrome asserts on the English copy (setupTests.ts boots the real en catalog);
// mirrors LibraryView / AccessSection's load-failure vs genuine-empty test convention.
vi.mock("../api", () => ({
  getSubscriptions: vi.fn(async () => []),
  unsubscribeChannel: vi.fn(async () => ({ ok: true })),
}));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

const CONNECTOR: Connector = {
  name: "slack",
  title: "Slack",
  icon: "slack",
  blurb: "",
  auth: "oauth",
  two_way: true,
  channels: true,
  available: true,
  fields: [],
  instructions: [],
  connected: true,
  account: null,
  enabled: true,
  brand_color: "#4a154b",
  logo: "slack",
  allowed_users: [],
  tools: [],
  managed: false,
  managed_profile: false,
};

const SUB = {
  session_id: "sess-1",
  session_title: "Weekly report",
  agent: "cowork",
  channel: "general",
  channel_name: "general",
  routing_target: null,
  collision: false,
};

describe("ListeningSessionsBlock — load failure vs genuine empty", () => {
  it("renders the genuine empty copy (with its count) when subscriptions resolve empty", async () => {
    render(<ListeningSessionsBlock c={CONNECTOR} />);
    const block = await screen.findByTestId("listening-slack");
    expect(block.textContent).toContain(
      "None yet — open a session's Sources ▸ Channels to subscribe it to a channel.",
    );
    expect(block.textContent).toContain("· 0");
    expect(screen.queryByText("Could not load subscriptions.")).toBeNull();
    expect(screen.queryByTestId("subscriptions-retry")).toBeNull();
  });

  it("shows a retryable failure (not the empty copy, no zero count) when the fetch rejects", async () => {
    const { getSubscriptions } = await import("../api");
    vi.mocked(getSubscriptions).mockRejectedValueOnce(new Error("network error"));

    render(<ListeningSessionsBlock c={CONNECTOR} />);

    expect(await screen.findByText("Could not load subscriptions.")).toBeTruthy();
    const block = screen.getByTestId("listening-slack");
    expect(block.textContent).not.toContain(
      "None yet — open a session's Sources ▸ Channels to subscribe it to a channel.",
    );
    expect(block.textContent).not.toContain("· 0");
    expect(screen.getByTestId("subscriptions-retry")).toBeTruthy();
  });

  it("recovers real rows after retrying a failed load", async () => {
    const { getSubscriptions } = await import("../api");
    vi.mocked(getSubscriptions).mockRejectedValueOnce(new Error("network error"));
    vi.mocked(getSubscriptions).mockResolvedValueOnce([SUB]);

    render(<ListeningSessionsBlock c={CONNECTOR} />);
    expect(await screen.findByText("Could not load subscriptions.")).toBeTruthy();

    fireEvent.click(screen.getByTestId("subscriptions-retry"));

    expect(await screen.findByText("Weekly report")).toBeTruthy();
    expect(screen.queryByTestId("subscriptions-retry")).toBeNull();
    expect(screen.queryByText("Could not load subscriptions.")).toBeNull();
  });
});
