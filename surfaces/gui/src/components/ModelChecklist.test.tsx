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
    expect(screen.getByText("Retry")).toBeTruthy();
  });

  it("keeps the live list but says the latest refresh failed when an error rides along", () => {
    // A failure after a successful pull: the cached list stays (and stays editable as the
    // provider's own), the row dates the last success and names the failure, and the
    // button reads Retry. Before 2026-09-09 the error was hidden and the date was the
    // failure's (owner's own nvidia/custom rows said "updated 3h ago" about a ConnectError).
    const catalog: ProviderCatalog = {
      supported: true,
      live: true,
      fetched_at: "2026-09-09T01:00:00Z",
      error: "Couldn't reach OpenAI (ConnectError).",
      failed_at: "2026-09-09T04:00:00Z",
      count: 1,
    };
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
    expect(screen.getByText(/Model list from the provider's API · updated .* · the latest refresh failed \(Couldn't reach OpenAI/)).toBeTruthy();
    expect(screen.getByText("Retry")).toBeTruthy();
    expect(screen.queryByPlaceholderText("Add another model…")).toBeNull();
    expect(screen.getAllByRole("checkbox")).toHaveLength(1);
  });

  it("shows a fetching line with a Refresh button while the first pull is still in flight", () => {
    // The very first Settings visit after an upgrade: the server kicked the pull on the
    // providers request and answered before it landed. This state used to render NOTHING
    // (no status line, no button) — what a colleague on v0.4.7 saw (owner-hit 2026-09-09).
    const onRefresh = vi.fn(async () => {});
    const catalog: ProviderCatalog = { supported: true, live: false, fetched_at: null, error: null, count: 0, pending: true };
    render(
      <ModelChecklist
        provider="gemini"
        knownProviders={KNOWN}
        suggested={["gemini-3.5-flash"]}
        curated={[]}
        defaultModel=""
        catalog={catalog}
        onRefresh={onRefresh}
        onChanged={() => {}}
      />,
    );
    expect(screen.getByText("Fetching the model list from the provider…")).toBeTruthy();
    expect(screen.getByPlaceholderText("Add another model…")).toBeTruthy(); // built-in list still editable meanwhile
    fireEvent.click(screen.getByText("Refresh"));
    expect(onRefresh).toHaveBeenCalledTimes(1);
  });

  it("treats an older server's answer without the pending flag the same way", () => {
    const catalog: ProviderCatalog = { supported: true, live: false, fetched_at: null, error: null, count: 0 };
    render(
      <ModelChecklist
        provider="gemini"
        knownProviders={KNOWN}
        suggested={["gemini-3.5-flash"]}
        curated={[]}
        defaultModel=""
        catalog={catalog}
        onRefresh={async () => {}}
        onChanged={() => {}}
      />,
    );
    expect(screen.getByText("Fetching the model list from the provider…")).toBeTruthy();
    expect(screen.getByText("Refresh")).toBeTruthy();
  });

  it("shows no status row for a provider without a model-list API", () => {
    const catalog: ProviderCatalog = { supported: false, live: false, fetched_at: null, error: null, count: 0 };
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
    expect(screen.queryByTestId("mlist-catalog-status")).toBeNull();
    expect(screen.getByText(/no model-list API/)).toBeTruthy();
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

// Audit 2026-09-10 fixes: suggestions are always the open provider's (an Ollama tag named
// like a cloud provider must not route to that provider), the default leads the list, a
// ticked/default id the live catalog no longer carries is badged, and the by-id add row
// stays reachable behind a link while the catalog is live.
describe("ModelChecklist — catalog hygiene", () => {
  const LIVE: ProviderCatalog = { supported: true, live: true, fetched_at: "2026-09-10T00:00:00Z", error: null, count: 2, pending: false };

  it("prefixes every suggestion with the open provider, even one named like another provider", () => {
    render(
      <ModelChecklist
        provider="ollama"
        knownProviders={[...KNOWN, "ollama", "mistral", "qwen"]}
        suggested={["mistral:latest", "qwen:7b"]}
        curated={[]}
        defaultModel=""
        onChanged={() => {}}
      />,
    );
    const boxes = screen.getAllByRole("checkbox");
    fireEvent.click(boxes[0]);
    expect(addModel).toHaveBeenCalledWith("ollama:mistral:latest");
  });

  it("lists the default first and badges ids the live catalog doesn't carry; add stays reachable", () => {
    render(
      <ModelChecklist
        provider="gemini"
        knownProviders={[...KNOWN, "gemini"]}
        suggested={["gemini-3.7-flash", "gemini-3.5-flash"]}
        curated={["gemini:gemini-3.5-flash", "gemini:gemini-3.8-flash"]}
        defaultModel="gemini:gemini-3.8-flash"
        catalog={LIVE}
        onChanged={() => {}}
      />,
    );
    const names = screen.getAllByTitle(/^gemini:/).map((el) => el.getAttribute("title"));
    expect(names[0]).toBe("gemini:gemini-3.8-flash");
    expect(screen.getByTestId("mlist-off-catalog-gemini:gemini-3.8-flash")).toBeTruthy();
    expect(screen.queryByTestId("mlist-off-catalog-gemini:gemini-3.5-flash")).toBeNull();
    // Live catalog: the free-type row is folded behind a link, not gone.
    expect(screen.queryByPlaceholderText("Add another model…")).toBeNull();
    fireEvent.click(screen.getByTestId("mlist-add-manually"));
    addTyped("gemini-4-preview");
    expect(addModel).toHaveBeenCalledWith("gemini:gemini-4-preview");
  });
});
