// Settings ▸ Models keeps asking for the providers while the open provider's live model
// catalog is still being fetched, and stops once it lands. The server kicks that first
// pull on the providers request itself and answers `pending` before it completes — so
// without this poll the first visit after an upgrade showed the built-in list with no
// status row and no way to fetch (what a colleague on v0.4.7 saw, owner-hit 2026-09-09).
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { ModelsTab } from "./ManageTabs";
import type { ProviderCatalog, ProviderInfo } from "../api";

vi.mock("../tauri", () => ({ openExternal: vi.fn() }));
vi.mock("../api", () => ({
  getSettings: vi.fn(async () => ({
    model: "gemini:gemini-3.5-flash",
    models: ["gemini:gemini-3.5-flash"],
    model_labels: {},
    source: "stored",
  })),
  getProviders: vi.fn(async () => []),
  getRelayStatus: vi.fn(async () => ({
    signed_in: true,
    email: "a@example.test",
    name: "A",
    dept: "",
    role: "",
    expires_at: "",
    relay: "https://relay.test",
    has_api_key: true,
    stale_relay: false,
  })),
  refreshProviderModels: vi.fn(async () => ({ ok: true })),
  getSubscriptions: vi.fn(async () => []),
  addModel: vi.fn(async (id: string) => ({ ok: true, models: [id], model: id })),
  removeModel: vi.fn(async () => ({ ok: true, models: [], model: "" })),
  setDefaultModel: vi.fn(async () => ({ ok: true })),
}));

import { getProviders } from "../api";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

const PENDING: ProviderCatalog = { supported: true, live: false, fetched_at: null, error: null, count: 0, pending: true };
const LIVE: ProviderCatalog = { supported: true, live: true, fetched_at: "2026-09-09T04:00:00Z", error: null, count: 2, pending: false };

function gemini(catalog: ProviderCatalog, suggested: string[]): ProviderInfo {
  return {
    name: "gemini",
    title: "Gemini (Google)",
    needs_key: true,
    configured: true,
    values: {},
    suggested_models: suggested,
    recommended_model: "gemini-3.5-flash",
    fields: [{ key: "api_key", label: "Gemini API key", secret: true, required: true, help: "", placeholder: "" }],
    catalog,
  };
}

describe("ModelsTab — catalog pending poll", () => {
  it(
    "polls the providers while the first pull is in flight and settles once the list lands",
    async () => {
      vi.mocked(getProviders)
        .mockResolvedValueOnce([gemini(PENDING, ["gemini-3.5-flash"])])
        .mockResolvedValue([gemini(LIVE, ["gemini-3.7-flash", "gemini-3.5-flash"])]);

      render(<ModelsTab />);
      fireEvent.click(await screen.findByTestId("set-provider-gemini"));

      // The first answer: fetching, with a Refresh button and the built-in list meanwhile.
      expect(await screen.findByText("Fetching the model list from the provider…")).toBeTruthy();
      expect(screen.getByText("Refresh")).toBeTruthy();
      expect(getProviders).toHaveBeenCalledTimes(1);

      // ~2s later the poll asks again and the live list replaces the placeholder line.
      expect(await screen.findByText(/Model list from the provider's API/, {}, { timeout: 5000 })).toBeTruthy();
      expect(screen.queryByText("Fetching the model list from the provider…")).toBeNull();
      expect(screen.getByText("gemini-3.7-flash")).toBeTruthy();
      expect(getProviders).toHaveBeenCalledTimes(2);
    },
    10000,
  );

  it("does not poll once the catalog is live", async () => {
    vi.mocked(getProviders).mockResolvedValue([gemini(LIVE, ["gemini-3.5-flash"])]);
    render(<ModelsTab />);
    fireEvent.click(await screen.findByTestId("set-provider-gemini"));
    expect(await screen.findByText(/Model list from the provider's API/)).toBeTruthy();
    await new Promise((r) => setTimeout(r, 2300));
    expect(getProviders).toHaveBeenCalledTimes(1);
  }, 10000);
});
