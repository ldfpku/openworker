// Add-model family dropdown for the cloud-account providers: the family choice folds
// into the model id (`bedrock:claude/…`, `vertex:openweight/…`); plain providers keep
// the bare add-model row.
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { ModelChecklist } from "./ModelChecklist";
import type { ProviderCatalog } from "../api";

vi.mock("../api", () => ({
  addModel: vi.fn(async (id: string) => ({ ok: true, models: [id], model: id })),
  removeModel: vi.fn(async () => ({ ok: true, models: [], model: "" })),
  setDefaultModel: vi.fn(async () => ({ ok: true })),
  getSettings: vi.fn(async () => ({ models: [], model: "" })),
}));

import { addModel } from "../api";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

const KNOWN = ["openai", "anthropic", "bedrock", "vertex", "openrouter"];

function renderList(provider: string) {
  return render(
    <ModelChecklist
      provider={provider}
      knownProviders={KNOWN}
      suggested={[]}
      curated={[]}
      defaultModel=""
      onChanged={() => {}}
    />,
  );
}

function addTyped(id: string) {
  fireEvent.change(screen.getByPlaceholderText("Add another model…"), {
    target: { value: id },
  });
  fireEvent.click(screen.getByText("Add"));
}

describe("ModelChecklist add-model family dropdown", () => {
  it("folds the selected vertex family into the id", async () => {
    renderList("vertex");
    fireEvent.change(screen.getByTestId("mlist-family"), {
      target: { value: "openweight" },
    });
    addTyped("meta/llama-4-maverick-17b-128e-instruct-maas");
    expect(addModel).toHaveBeenCalledWith(
      "vertex:openweight/meta/llama-4-maverick-17b-128e-instruct-maas",
    );
  });

  it("defaults bedrock to the Claude family and keeps a typed family verbatim", async () => {
    renderList("bedrock");
    addTyped("anthropic.claude-sonnet-4-6-v1:0");
    expect(addModel).toHaveBeenCalledWith(
      "bedrock:claude/anthropic.claude-sonnet-4-6-v1:0",
    );
    addTyped("other/amazon.nova-2-pro-v1:0");
    expect(addModel).toHaveBeenLastCalledWith("bedrock:other/amazon.nova-2-pro-v1:0");
  });

  it("shows no family dropdown for plain providers", async () => {
    renderList("openrouter");
    expect(screen.queryByTestId("mlist-family")).toBeNull();
    addTyped("z-ai/glm-5.2");
    expect(addModel).toHaveBeenCalledWith("openrouter:z-ai/glm-5.2");
  });
});

describe("ModelChecklist live catalog status", () => {
  it("hides the add-model row and shows a refresh button + status line when live", () => {
    const catalog: ProviderCatalog = { supported: true, live: true, fetched_at: "2026-09-03T05:00:00Z", error: null, count: 1 };
    render(
      <ModelChecklist
        provider="openai"
        knownProviders={KNOWN}
        suggested={["gpt-5.5"]}
        curated={[]}
        defaultModel=""
        catalog={catalog}
        onRefresh={async () => {}}
        onChanged={() => {}}
      />,
    );
    expect(screen.queryByPlaceholderText("Add another model…")).toBeNull();
    expect(screen.getByText("Refresh")).toBeTruthy();
    expect(screen.getByText(/Model list from the provider's API/)).toBeTruthy();
  });

  it("keeps the add-model row and shows the error text when the fetch failed and isn't live", () => {
    const catalog: ProviderCatalog = { supported: true, live: false, fetched_at: null, error: "timeout", count: 0 };
    render(
      <ModelChecklist
        provider="openai"
        knownProviders={KNOWN}
        suggested={["gpt-5.5"]}
        curated={[]}
        defaultModel=""
        catalog={catalog}
        onRefresh={async () => {}}
        onChanged={() => {}}
      />,
    );
    expect(screen.getByPlaceholderText("Add another model…")).toBeTruthy();
    expect(screen.getByText(/Couldn't fetch the model list \(timeout\)/)).toBeTruthy();
  });

  it("filters the rows by id/label once there are more than 12 and the catalog is live", () => {
    const suggested = Array.from({ length: 13 }, (_, i) => `model-${i}`);
    const catalog: ProviderCatalog = { supported: true, live: true, fetched_at: "2026-09-03T05:00:00Z", error: null, count: 13 };
    render(
      <ModelChecklist
        provider="openai"
        knownProviders={KNOWN}
        suggested={suggested}
        curated={[]}
        defaultModel=""
        catalog={catalog}
        onRefresh={async () => {}}
        onChanged={() => {}}
      />,
    );
    expect(screen.getAllByRole("checkbox")).toHaveLength(13);
    fireEvent.change(screen.getByPlaceholderText("Filter models…"), {
      target: { value: "model-1" },
    });
    // model-1, model-10..model-12 match the "model-1" substring.
    expect(screen.getAllByRole("checkbox")).toHaveLength(4);
  });
});
