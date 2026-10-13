// Auth-method segmented choice + show_when field visibility (Bedrock's "Connect with"):
// only the selected method's fields render, and clicking a segment switches them.
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import {
  KEY_HELP,
  ProviderForm,
  ProviderMark,
  localizeVerifyError,
  type ProviderSetupState,
} from "./ProviderSetup";
import type { ProviderInfo } from "../api";

vi.mock("../tauri", () => ({ openExternal: vi.fn() }));

afterEach(cleanup);

const BEDROCK: ProviderInfo = {
  name: "bedrock",
  title: "AWS Bedrock",
  needs_key: true,
  configured: false,
  values: {},
  suggested_models: [],
  recommended_model: null,
  fields: [
    { key: "region", label: "AWS region", secret: false, required: true, help: "", placeholder: "us-east-1" },
    {
      key: "auth_method",
      label: "Connect with",
      secret: false,
      required: false,
      help: "",
      placeholder: "",
      default: "api_key",
      choices: [
        { value: "api_key", label: "Bedrock API key" },
        { value: "profile", label: "AWS profile" },
        { value: "iam", label: "IAM keys" },
      ],
    },
    { key: "bedrock_api_key", label: "Bedrock API key", secret: true, required: false, help: "", placeholder: "ABSK…", show_when: { auth_method: "api_key" } },
    { key: "aws_profile", label: "AWS profile", secret: false, required: false, help: "", placeholder: "default", show_when: { auth_method: "profile" } },
    { key: "aws_secret_access_key", label: "Secret access key", secret: true, required: false, help: "", placeholder: "", show_when: { auth_method: "iam" } },
  ],
};

function makePs(fields: Record<string, string>, setFieldValue = vi.fn()): ProviderSetupState {
  return {
    providers: [BEDROCK],
    ordered: [BEDROCK],
    refreshProviders: async () => {},
    refreshAll: async () => {},
    sel: "bedrock",
    info: BEDROCK,
    fields,
    setFieldValue,
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

// NVIDIA-shaped: base_url is OPTIONAL with a vendor-prefilled default, so it hides behind
// the quiet "Custom endpoint" disclosure. The "Custom endpoint" provider itself (below)
// instead ships a REQUIRED base_url with no default, which must stay inline.
const NVIDIA_LIKE: ProviderInfo = {
  name: "nvidia",
  title: "NVIDIA (NIM)",
  needs_key: true,
  configured: false,
  values: {},
  suggested_models: [],
  recommended_model: "moonshotai/kimi-k3",
  fields: [
    { key: "api_key", label: "NVIDIA API key", secret: true, required: true, help: "", placeholder: "nvapi-…" },
    {
      key: "base_url",
      label: "Endpoint",
      secret: false,
      required: false,
      help: "Prefilled with the company relay to NVIDIA NIM; normally leave it as is.",
      placeholder: "https://nvidia.smjtools.com/v1",
      default: "https://nvidia.smjtools.com/v1",
    },
  ],
};

const CUSTOM: ProviderInfo = {
  name: "custom",
  title: "Custom endpoint",
  needs_key: true,
  configured: false,
  values: {},
  suggested_models: [],
  recommended_model: null,
  fields: [
    {
      key: "display_name",
      label: "Endpoint name",
      secret: false,
      required: true,
      help: "Shown as this provider's name in the provider list.",
      placeholder: "",
    },
    { key: "api_key", label: "API key", secret: true, required: true, help: "", placeholder: "" },
    {
      key: "base_url",
      label: "Endpoint",
      secret: false,
      required: true,
      help: "OpenAI-compatible base URL, usually ending in /v1.",
      placeholder: "https://…/v1",
    },
  ],
};

function makePsForInfo(info: ProviderInfo, fields: Record<string, string>): ProviderSetupState {
  return {
    providers: [info],
    ordered: [info],
    refreshProviders: async () => {},
    refreshAll: async () => {},
    sel: info.name,
    info,
    fields,
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

describe("Custom-endpoint field visibility (required vs. optional base_url)", () => {
  it("NVIDIA-shaped provider hides its optional, prefilled base_url behind the disclosure", () => {
    render(<ProviderForm ps={makePsForInfo(NVIDIA_LIKE, {})} tp="t" />);
    expect(screen.queryByTestId("t-field-base_url")).toBeNull();
    expect(screen.getByTestId("t-endpoint-link")).toBeTruthy();
  });

  it("the Custom-endpoint provider's required base_url renders inline, not behind a disclosure", () => {
    render(<ProviderForm ps={makePsForInfo(CUSTOM, {})} tp="t" />);
    expect(screen.getByTestId("t-field-display_name")).toBeTruthy();
    expect(screen.getByTestId("t-field-api_key")).toBeTruthy();
    expect(screen.getByTestId("t-field-base_url")).toBeTruthy();
    expect(screen.queryByTestId("t-endpoint-link")).toBeNull();
  });
});

describe("ProviderForm auth-method choice", () => {
  it("renders only the selected method's fields", () => {
    render(<ProviderForm ps={makePs({ auth_method: "api_key" })} tp="t" />);
    expect(screen.getByTestId("t-field-bedrock_api_key")).toBeTruthy();
    expect(screen.queryByTestId("t-field-aws_profile")).toBeNull();
    expect(screen.queryByTestId("t-field-aws_secret_access_key")).toBeNull();
    expect(screen.getByTestId("t-choice-auth_method-api_key").getAttribute("aria-checked")).toBe("true");
  });

  it("switching the segment swaps the visible fields", () => {
    const setFieldValue = vi.fn();
    const { rerender } = render(
      <ProviderForm ps={makePs({ auth_method: "api_key" }, setFieldValue)} tp="t" />,
    );
    fireEvent.click(screen.getByTestId("t-choice-auth_method-profile"));
    expect(setFieldValue).toHaveBeenCalledWith("auth_method", "profile");
    rerender(<ProviderForm ps={makePs({ auth_method: "profile" }, setFieldValue)} tp="t" />);
    expect(screen.getByTestId("t-field-aws_profile")).toBeTruthy();
    expect(screen.queryByTestId("t-field-bedrock_api_key")).toBeNull();
  });

  it("iam segment shows the key-pair fields", () => {
    render(<ProviderForm ps={makePs({ auth_method: "iam" })} tp="t" />);
    expect(screen.getByTestId("t-field-aws_secret_access_key")).toBeTruthy();
    expect(screen.queryByTestId("t-field-bedrock_api_key")).toBeNull();
  });
});

describe("ProviderForm Test feedback (owner-hit 2026-10-14: Vertex's Test seemed to do nothing)", () => {
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
          { value: "adc", label: "Google Cloud login", command: "gcloud auth application-default login" },
          { value: "api_key", label: "API key" },
        ],
      },
    ],
  };

  it("a failed Test shows its reason beside the button and marks the empty fields", () => {
    const ps = {
      ...makePsForInfo(VERTEX, { project: "", location: "global", auth_method: "adc" }),
      verify: { state: "error" as const, msg: "Fill these in first: GCP project ID" },
      invalid: new Set(["project"]),
    };
    render(<ProviderForm ps={ps} tp="t" />);
    const err = screen.getByTestId("t-verify-error");
    expect(err.textContent).toBe("Fill these in first: GCP project ID");
    expect(err.getAttribute("role")).toBe("alert");
    // Inside the method card, next to the button — and only once on the page.
    expect(err.parentElement?.contains(screen.getByTestId("t-test"))).toBe(true);
    expect(screen.getAllByText("Fill these in first: GCP project ID")).toHaveLength(1);
    const project = screen.getByTestId("t-field-project");
    expect(project.getAttribute("aria-invalid")).toBe("true");
    expect(project.className).toContain("border-danger");
    expect(screen.getByTestId("t-field-location").getAttribute("aria-invalid")).toBeNull();
    // The caret goes to the first field that needs filling.
    expect(document.activeElement).toBe(project);
  });

  it("the Test button says it is testing instead of a bare ellipsis", () => {
    const ps = {
      ...makePsForInfo(VERTEX, { project: "p", location: "global", auth_method: "adc" }),
      verify: { state: "testing" as const },
    };
    render(<ProviderForm ps={ps} tp="t" />);
    const btn = screen.getByTestId("t-test") as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
    expect(btn.textContent).not.toBe("…");
  });

  it("copying the command says so", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    render(<ProviderForm ps={makePsForInfo(VERTEX, { project: "", location: "global", auth_method: "adc" })} tp="t" />);
    expect(screen.queryByTestId("t-cmd-copied")).toBeNull();
    fireEvent.click(screen.getByTestId("t-cmd-copy"));
    expect(writeText).toHaveBeenCalledWith("gcloud auth application-default login");
    expect((await screen.findByTestId("t-cmd-copied")).getAttribute("role")).toBe("status");
  });

  it("a copy the clipboard refused claims nothing", async () => {
    const writeText = vi.fn().mockRejectedValue(new Error("denied"));
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    render(<ProviderForm ps={makePsForInfo(VERTEX, { project: "", location: "global", auth_method: "adc" })} tp="t" />);
    fireEvent.click(screen.getByTestId("t-cmd-copy"));
    await Promise.resolve();
    await Promise.resolve();
    expect(screen.queryByTestId("t-cmd-copied")).toBeNull();
  });

  it("backend errors are shown in the person's language", () => {
    const table: Record<string, string> = {
      "GCP project ID": "GCP 项目 ID",
      Location: "位置",
      "provider.list_sep": "、",
      "Google rejected the credentials.": "Google 拒绝了该凭证。",
    };
    const t = (key: string, o?: Record<string, unknown>) =>
      key === "provider.err_missing_fields" ? "请先填写：" + String(o?.fields) : (table[key] ?? key);
    expect(localizeVerifyError("missing: GCP project ID, Location", t)).toBe("请先填写：GCP 项目 ID、位置");
    expect(localizeVerifyError("Google rejected the credentials.", t)).toBe("Google 拒绝了该凭证。");
    expect(localizeVerifyError("Vertex AI returned HTTP 500.", t)).toBe("Vertex AI returned HTTP 500.");
  });
});

describe("Ark provider presentation", () => {
  it("uses separate BytePlus and Volcengine brand marks", () => {
    const { container, rerender } = render(
      <ProviderMark name="ark" title="BytePlus Ark" />,
    );
    expect(container.querySelector("img")).toBeTruthy();

    rerender(
      <ProviderMark
        name="ark-agent-plan-cn"
        title="Volcengine Ark Agent Plan"
      />,
    );
    expect(container.querySelector("img")).toBeTruthy();
  });

  it("links each provider to its own API key console", () => {
    expect(KEY_HELP.ark.url).toBe(
      "https://console.byteplus.com/ark/region:ark+ap-southeast-1/apiKey",
    );
    expect(KEY_HELP["ark-agent-plan-cn"].url).toContain(
      "advancedActiveKey=agentPlan",
    );
  });
});
