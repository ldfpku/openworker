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
    const box = screen
      .getByTitle("ollama:mistral:latest")
      .closest("label")!
      .querySelector("input") as HTMLInputElement;
    fireEvent.click(box);
    expect(addModel).toHaveBeenCalledWith("ollama:mistral:latest");
  });

  it("sorts rows by id, newest first, and badges ids the live catalog doesn't carry; add stays reachable", () => {
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
    expect(names).toEqual([
      "gemini:gemini-3.8-flash",
      "gemini:gemini-3.7-flash",
      "gemini:gemini-3.5-flash",
    ]);
    expect(screen.getByTestId("mlist-off-catalog-gemini:gemini-3.8-flash")).toBeTruthy();
    expect(screen.queryByTestId("mlist-off-catalog-gemini:gemini-3.5-flash")).toBeNull();
    // Live catalog: the free-type row is folded behind a link, not gone.
    expect(screen.queryByPlaceholderText("Add another model…")).toBeNull();
    fireEvent.click(screen.getByTestId("mlist-add-manually"));
    addTyped("gemini-4-preview");
    expect(addModel).toHaveBeenCalledWith("gemini:gemini-4-preview");
  });

  it("does not pin the default to the top — strict id order (owner call 2026-09-23)", () => {
    render(
      <ModelChecklist
        provider="aigw"
        knownProviders={[...KNOWN, "aigw"]}
        suggested={["anthropic/claude-sonnet-5", "openai/gpt-6-luna", "openai/gpt-5.6-terra"]}
        curated={["aigw:anthropic/claude-sonnet-5"]}
        defaultModel="aigw:anthropic/claude-sonnet-5"
        onChanged={() => {}}
      />,
    );
    const names = screen.getAllByTitle(/^aigw:/).map((el) => el.getAttribute("title"));
    expect(names).toEqual([
      "aigw:openai/gpt-6-luna",
      "aigw:openai/gpt-5.6-terra",
      "aigw:anthropic/claude-sonnet-5",
    ]);
  });

  // Owner call 2026-09-23: the company gateway's models come only from its per-person
  // list — no free-type row, live or not, and no "add manually" escape hatch either.
  it.each([
    ["live", { supported: true, live: true, fetched_at: "2026-09-23T05:00:00Z", error: null, count: 2 }],
    ["failed", { supported: true, live: false, fetched_at: null, error: "timeout", count: 0 }],
  ] as const)("never offers hand-typed ids for the gateway (%s catalog)", (_label, catalog) => {
    render(
      <ModelChecklist
        provider="aigw"
        knownProviders={[...KNOWN, "aigw"]}
        suggested={["anthropic/claude-opus-5", "workers-ai/@cf/zai-org/glm-5.3"]}
        curated={["aigw:anthropic/claude-opus-5"]}
        defaultModel="aigw:anthropic/claude-opus-5"
        catalog={catalog as ProviderCatalog}
        onRefresh={async () => {}}
        onChanged={() => {}}
      />,
    );
    expect(screen.queryByPlaceholderText("Add another model…")).toBeNull();
    expect(screen.queryByTestId("mlist-add-manually")).toBeNull();
    // Ticking and defaulting still work on what the gateway listed.
    expect(screen.getByTitle("aigw:workers-ai/@cf/zai-org/glm-5.3")).toBeTruthy();
    // …and the status row (Refresh / Retry) is the way to re-pull the list.
    expect(screen.getByTestId("mlist-catalog-status")).toBeTruthy();
  });

  // The gateway's server list is the ONLY list (the guard is an allowlist): with no
  // successful pull there are no models at all, so the status row must not claim a
  // built-in list is being shown — and it carries the guard's own sentence verbatim.
  it("says no models are available, not 'showing the built-in list', when the gateway has no list", () => {
    const guard = "你的账号暂未开通任何模型，请联系管理员开通。[gateway-guard]";
    render(
      <ModelChecklist
        provider="aigw"
        knownProviders={[...KNOWN, "aigw"]}
        suggested={[]}
        curated={["gpt-5.5"]}
        defaultModel="gpt-5.5"
        catalog={{ supported: true, live: false, fetched_at: null, error: guard, count: 0 }}
        onRefresh={async () => {}}
        onChanged={() => {}}
      />,
    );
    const status = screen.getByTestId("mlist-catalog-status").textContent || "";
    expect(status).toContain(guard);
    expect(status).toContain("no models are available until it arrives");
    expect(status).not.toContain("built-in list");
    expect(screen.queryAllByTitle(/^aigw:/)).toHaveLength(0);
    expect(screen.getByText("Retry")).toBeTruthy();
  });

  it("says the old default left the list when told so, and only then", () => {
    const catalog: ProviderCatalog = { supported: true, live: true, fetched_at: "2026-10-13T05:00:00Z", error: null, count: 1 };
    const list = (defaultGone: boolean) => (
      <ModelChecklist
        provider="aigw"
        knownProviders={[...KNOWN, "aigw"]}
        suggested={["anthropic/claude-sonnet-5"]}
        curated={["aigw:anthropic/claude-sonnet-5"]}
        defaultModel="aigw:anthropic/claude-fable-5"
        catalog={catalog}
        defaultGone={defaultGone}
        onRefresh={async () => {}}
        onChanged={() => {}}
      />
    );
    const { rerender } = render(list(true));
    expect(screen.getByTestId("mlist-default-gone").textContent).toBe(
      "Your previous default model is no longer on your available list — please choose another.",
    );
    // The dead id is not a row; what is left can be made the default.
    expect(screen.queryByTitle("aigw:anthropic/claude-fable-5")).toBeNull();
    expect(screen.getByText("Make default")).toBeTruthy();
    rerender(list(false));
    expect(screen.queryByTestId("mlist-default-gone")).toBeNull();
  });
});

// Owner ask 2026-10-14: a price hint next to the models (cost, and roughly capability), and
// a "Restricted" tag on models the administrator opened to 总经理 / 管理员 only. Both come
// from the company gateway's guard through /v1/settings; a row with no entry — every other
// provider's, and a gateway model the guard did not price — must look exactly as before.
describe("ModelChecklist — gateway price hint and Restricted tag", () => {
  const SOL = "aigw:openai/gpt-6.1-sol";
  const FLASH = "aigw:google-ai-studio/gemini-3.7-flash";
  const HAIKU = "aigw:anthropic/claude-haiku-4-5";
  const LUNA = "aigw:openai/gpt-6-luna";
  const gateway = (extra: Partial<Parameters<typeof ModelChecklist>[0]> = {}) => (
    <ModelChecklist
      provider="aigw"
      knownProviders={[...KNOWN, "aigw"]}
      suggested={[
        "openai/gpt-6.1-sol",
        "google-ai-studio/gemini-3.7-flash",
        "anthropic/claude-haiku-4-5",
        "openai/gpt-6-luna",
      ]}
      curated={[SOL]}
      defaultModel={SOL}
      labels={{ [SOL]: "GPT-6.1 Sol · via Cloudflare" }}
      prices={{ [SOL]: { in: 3, out: 15 }, [FLASH]: { in: 0.15, out: 0.6 }, [HAIKU]: { in: 1 } }}
      tiers={{ [SOL]: "limited" }}
      onChanged={() => {}}
      {...extra}
    />
  );
  const row = (id: string) => screen.getByTitle(id).closest(".mlist-row") as HTMLElement;

  it("shows input / output price per million tokens on the row, with the spelled-out tooltip", () => {
    render(gateway());
    const price = screen.getByTestId(`mlist-price-${SOL}`);
    expect(price.textContent).toBe("$3 / $15 per 1M tokens");
    expect(price.getAttribute("title")).toBe("Input $3 · output $15 (USD per 1M tokens)");
    // Inside the row's flexible name cell: whatever follows that cell does not move.
    expect(price.closest(".mlist-main")).toBe(row(SOL).querySelector(".mlist-main"));
    expect(screen.getByTestId(`mlist-price-${FLASH}`).textContent).toBe("$0.15 / $0.6 per 1M tokens");
    // Only one side priced: that side, named.
    expect(screen.getByTestId(`mlist-price-${HAIKU}`).textContent).toBe("Input $1 per 1M tokens");
  });

  it("tags a limited model 'Restricted' next to its name, and only that one", () => {
    render(gateway());
    const tag = screen.getByTestId(`mlist-restricted-${SOL}`);
    expect(tag.textContent).toBe("Restricted");
    expect(tag.getAttribute("title")).toBe("Open to the General Manager and administrators only");
    // Right after the name group, ahead of the price.
    expect(tag.parentElement?.previousElementSibling?.querySelector(".mlist-name")?.textContent).toBe(
      "GPT-6.1 Sol · via Cloudflare",
    );
    expect(tag.nextElementSibling).toBe(screen.getByTestId(`mlist-price-${SOL}`));
    expect(screen.queryAllByTestId(/^mlist-restricted-/)).toHaveLength(1);
  });

  it("adds nothing to a model without data", () => {
    render(gateway());
    expect(screen.queryByTestId(`mlist-price-${LUNA}`)).toBeNull();
    expect(screen.queryByTestId(`mlist-restricted-${LUNA}`)).toBeNull();
    // The row is the bare one it always was: checkbox + name, then the make-default button.
    const main = row(LUNA).querySelector(".mlist-main")!;
    expect(Array.from(main.children).map((el) => el.tagName)).toEqual(["INPUT", "SPAN"]);
    expect(row(LUNA).textContent).toBe("openai/gpt-6-lunaMake default");
  });

  it("adds nothing at all when the server sends no maps (older backend, other providers)", () => {
    render(gateway({ prices: undefined, tiers: undefined }));
    expect(screen.queryAllByTestId(/^mlist-(price|restricted)-/)).toHaveLength(0);
    cleanup();
    render(
      <ModelChecklist
        provider="openai"
        knownProviders={KNOWN}
        suggested={["gpt-5.5"]}
        curated={["gpt-5.5"]}
        defaultModel="gpt-5.5"
        // A map that only knows gateway ids says nothing about this provider's rows.
        prices={{ [SOL]: { in: 3, out: 15 } }}
        tiers={{ [SOL]: "limited" }}
        onChanged={() => {}}
      />,
    );
    expect(screen.queryAllByTestId(/^mlist-(price|restricted)-/)).toHaveLength(0);
  });

  it("ignores malformed prices and unknown tiers instead of showing them", () => {
    render(
      gateway({
        prices: {
          [SOL]: { in: -3, out: Number.NaN },
          [FLASH]: { in: "0.15", out: 0.6 } as never,
          [HAIKU]: null,
        },
        tiers: { [SOL]: "all", [FLASH]: "vip" },
      }),
    );
    expect(screen.queryByTestId(`mlist-price-${SOL}`)).toBeNull();
    expect(screen.getByTestId(`mlist-price-${FLASH}`).textContent).toBe("Output $0.6 per 1M tokens");
    expect(screen.queryByTestId(`mlist-price-${HAIKU}`)).toBeNull();
    expect(screen.queryAllByTestId(/^mlist-restricted-/)).toHaveLength(0);
  });

  it("says it in Chinese with the agreed wording", async () => {
    const i18n = (await import("i18next")).default;
    await i18n.changeLanguage("zh");
    try {
      render(gateway());
      const price = screen.getByTestId(`mlist-price-${SOL}`);
      expect(price.textContent).toBe("$3 / $15 每百万 token");
      expect(price.getAttribute("title")).toBe("输入 $3 · 输出 $15（美元 / 百万 token）");
      const tag = screen.getByTestId(`mlist-restricted-${SOL}`);
      expect(tag.textContent).toBe("限制使用");
      expect(tag.getAttribute("title")).toBe("仅对总经理、管理员开放");
    } finally {
      await i18n.changeLanguage("en");
    }
  });
});
