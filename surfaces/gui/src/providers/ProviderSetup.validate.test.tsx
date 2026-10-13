// Test & save with required fields left empty must answer on the spot — which fields, on
// the fields — and must not call the backend (owner-hit 2026-10-14: on Vertex the click
// "did nothing"; the only feedback was one English line below the card).
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import type { ProviderInfo } from "../api";

const VERTEX: ProviderInfo = {
  name: "vertex",
  title: "Vertex AI (Google Cloud)",
  needs_key: true,
  configured: false,
  values: {},
  suggested_models: [],
  recommended_model: null,
  fields: [
    { key: "project", label: "GCP project ID", secret: false, required: true, help: "", placeholder: "my-project-123" },
    { key: "location", label: "Location", secret: false, required: true, help: "", placeholder: "global", default: "global" },
    {
      key: "auth_method",
      label: "Connect with",
      secret: false,
      required: false,
      help: "",
      placeholder: "",
      default: "adc",
      choices: [
        { value: "adc", label: "Google Cloud login" },
        { value: "service_account", label: "Service account" },
      ],
    },
    { key: "service_account_json", label: "Service-account JSON", secret: true, required: false, help: "", placeholder: "", show_when: { auth_method: "service_account" } },
  ],
};

const api = vi.hoisted(() => ({
  getProviders: vi.fn(),
  verifyProvider: vi.fn(),
  setProvider: vi.fn(),
}));
vi.mock("../api", () => ({
  ...api,
  removeProvider: vi.fn(),
  codexAuthStatus: vi.fn(),
  codexSignin: vi.fn(),
  codexSignout: vi.fn(),
}));
vi.mock("../tauri", () => ({ openExternal: vi.fn() }));
vi.mock("./GatewaySignIn", () => ({ GatewaySignIn: () => null }));

import { useProviderSetup } from "./ProviderSetup";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

async function openVertex() {
  api.getProviders.mockResolvedValue([VERTEX]);
  const hook = renderHook(() => useProviderSetup({ stayAfterTest: true }));
  await waitFor(() => expect(hook.result.current.providers).toHaveLength(1));
  act(() => hook.result.current.openProvider("vertex"));
  return hook;
}

describe("Test & save: required fields", () => {
  it("opens with the location default filled in", async () => {
    const { result } = await openVertex();
    expect(result.current.fields.location).toBe("global");
    expect(result.current.fields.project).toBe("");
  });

  it("an empty required field fails on the spot, without calling the backend", async () => {
    const { result } = await openVertex();
    let ok = true;
    await act(async () => {
      ok = await result.current.runTestAndSave();
    });
    expect(ok).toBe(false);
    expect(api.verifyProvider).not.toHaveBeenCalled();
    expect(result.current.verify.state).toBe("error");
    expect(result.current.verify.msg).toBeTruthy();
    expect([...result.current.invalid]).toEqual(["project"]);
  });

  it("typing into the field clears its mark; a complete form reaches the backend", async () => {
    const { result } = await openVertex();
    await act(async () => {
      await result.current.runTestAndSave();
    });
    act(() => result.current.setFieldValue("project", "my-project"));
    expect(result.current.invalid.size).toBe(0);
    expect(result.current.verify.state).toBe("idle");

    api.verifyProvider.mockResolvedValue({ ok: false, error: "missing: Location" });
    await act(async () => {
      await result.current.runTestAndSave();
    });
    expect(api.verifyProvider).toHaveBeenCalledWith(
      "vertex",
      expect.objectContaining({ project: "my-project", location: "global", auth_method: "adc" }),
    );
    // The backend's own "missing:" list is rebuilt rather than shown verbatim.
    expect(result.current.verify.msg).not.toContain("missing:");

    api.verifyProvider.mockResolvedValue({ ok: true });
    api.setProvider.mockResolvedValue({ ok: true });
    let ok = false;
    await act(async () => {
      ok = await result.current.runTestAndSave();
    });
    expect(ok).toBe(true);
    expect(api.setProvider).toHaveBeenCalledTimes(1);
  });

  it("a blank secret on an optional field is not this check's business", async () => {
    const { result } = await openVertex();
    act(() => result.current.setFieldValue("project", "p"));
    act(() => result.current.setFieldValue("auth_method", "service_account"));
    api.verifyProvider.mockResolvedValue({ ok: false, error: "Paste a service-account JSON to test." });
    await act(async () => {
      await result.current.runTestAndSave();
    });
    expect(api.verifyProvider).toHaveBeenCalledTimes(1);
    expect(result.current.invalid.size).toBe(0);
  });
});
