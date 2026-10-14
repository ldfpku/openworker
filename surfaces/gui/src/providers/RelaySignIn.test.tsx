// The Gemini (Google) pane takes two credentials: a sign-in to the company relay (who is
// calling) and the person's own Google key (what calls Google). The relay card therefore
// sits ABOVE the ordinary key field instead of replacing it. Its render site was dropped
// once by a merge — the card stayed defined but unmounted, with no way to sign in — and
// the whole provider was retired from 0.7.1 until 2026-10-14, so these pin the mount.
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { KEY_HELP, ProviderForm, type ProviderSetupState } from "./ProviderSetup";
import { RelaySignIn } from "./RelaySignIn";
import { PROVIDER_LOGOS, PROVIDER_ORDER } from "./logos";
import { detectProvider, type ProviderInfo, type RelayStatus } from "../api";

const getRelayStatus = vi.fn();

vi.mock("../api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api")>()),
  getRelayStatus: (...a: unknown[]) => getRelayStatus(...a),
}));
vi.mock("../tauri", () => ({ openExternal: vi.fn() }));
vi.mock("../brand/logo.webp", () => ({ default: "light.webp" }));
vi.mock("../brand/logo-dark.webp", () => ({ default: "dark.webp" }));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

const status = (over: Partial<RelayStatus> = {}): RelayStatus => ({
  signed_in: false,
  email: "",
  name: "",
  dept: "",
  role: "",
  expires_at: "",
  relay: "https://gemini.smjtools.com",
  has_api_key: false,
  stale_relay: false,
  ...over,
});

const GEMINI: ProviderInfo = {
  name: "gemini",
  title: "Gemini (Google)",
  needs_key: true,
  configured: false,
  values: {},
  suggested_models: [],
  recommended_model: "gemini-3.7-flash",
  fields: [
    { key: "api_key", label: "Gemini API key", secret: true, required: true, help: "", placeholder: "AIza…" },
  ],
};

function makePs(info: ProviderInfo): ProviderSetupState {
  return {
    providers: [info],
    ordered: [info],
    refreshProviders: async () => {},
    refreshAll: async () => {},
    sel: info.name,
    info,
    fields: {},
    setFieldValue: vi.fn(),
    dirty: false,
    verify: { state: "idle" },
    showEndpoint: false,
    setShowEndpoint: () => {},
    keylessOk: new Set(),
    credentialed: false,
    savedState: false,
    secretFilled: true,
    openProvider: () => {},
    backToGallery: () => {},
    runTestAndSave: async () => true,
    removeKey: async () => {},
    cancelBackTimer: () => {},
    statusFor: () => null,
    saveField: async () => {},
    fieldSaved: null,
    invalid: new Set(),
  };
}

describe("RelaySignIn", () => {
  it("offers the one-time-code sign-in while signed out, verifying once on mount", async () => {
    getRelayStatus.mockResolvedValue(status());
    render(<RelaySignIn tp="t" />);
    expect(await screen.findByTestId("t-relay-signin-button")).toBeTruthy();
    expect(getRelayStatus).toHaveBeenCalledWith(true);
    expect(screen.getByTestId("t-relay-signin").textContent).toContain("gemini.smjtools.com");
  });

  it("says the key is still missing once signed in without one", async () => {
    getRelayStatus.mockResolvedValue(
      status({ signed_in: true, email: "a@example.test", name: "A" }),
    );
    render(<RelaySignIn tp="t" />);
    expect(await screen.findByTestId("t-relay-needs-key")).toBeTruthy();
    expect(screen.getByTestId("t-relay-signout")).toBeTruthy();
  });
});

describe("Gemini (Google) provider pane", () => {
  it("mounts the relay sign-in card above the key field", async () => {
    getRelayStatus.mockResolvedValue(status());
    render(<ProviderForm ps={makePs(GEMINI)} tp="t" />);
    const card = await screen.findByTestId("t-relay-signin");
    const key = screen.getByTestId("t-field-api_key");
    expect(card.compareDocumentPosition(key) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("no other provider's pane asks for a relay sign-in", async () => {
    render(<ProviderForm ps={makePs({ ...GEMINI, name: "anthropic", title: "Anthropic" })} tp="t" />);
    await waitFor(() => expect(screen.getByTestId("t-field-api_key")).toBeTruthy());
    expect(screen.queryByTestId("t-relay-signin")).toBeNull();
    expect(screen.queryByTestId("t-relay-pending")).toBeNull();
    expect(getRelayStatus).not.toHaveBeenCalled();
  });

  it("is in the gallery with its mark, its key link and its key-shape rule", () => {
    expect(PROVIDER_LOGOS.gemini).toBeTruthy();
    expect(PROVIDER_ORDER.indexOf("gemini")).toBe(PROVIDER_ORDER.indexOf("openai") + 1);
    expect(PROVIDER_ORDER.indexOf("gemini")).toBeLessThan(PROVIDER_ORDER.indexOf("aigw"));
    expect(KEY_HELP.gemini.url).toBe("https://aistudio.google.com/apikey");
    expect(detectProvider("AIzaSyAbc123")).toBe("gemini");
    // NVIDIA stays retired: no mark, no gallery slot, no key-shape rule.
    expect(PROVIDER_LOGOS.nvidia).toBeUndefined();
    expect(PROVIDER_ORDER).not.toContain("nvidia");
    expect(detectProvider("nvapi-AbC123")).toBeNull();
  });
});
