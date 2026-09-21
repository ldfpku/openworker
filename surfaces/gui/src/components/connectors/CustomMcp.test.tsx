// A refused MCP write has to say WHY. The server writes nothing when it cannot read
// `mcp.json` first — rewriting the file from an empty base would delete every other
// server the user has — but the refusal used to die inside `res.json()`: the row simply
// never appeared, the toggle snapped back, and the one thing the user could actually go
// and fix (a locked or damaged config file) was never said out loud.
//
// UI chrome asserts on the English copy (setupTests.ts boots the real en catalog under
// jsdom's en-US locale), same convention as AccessSection's tests.
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { AddMcpModal, CustomMcpGroup, McpServerDetail, mcpErrorText } from "./CustomMcp";
import type { McpServer } from "../../api";
import en from "../../locales/en.json";

vi.mock("../../api", () => ({
  addMcpServer: vi.fn(async () => ({ ok: true })),
  patchMcpServer: vi.fn(async () => ({ ok: true })),
  deleteMcpServer: vi.fn(async () => ({ ok: true })),
  connectMcp: vi.fn(async () => ({ ok: true, started: true })),
  signoutMcp: vi.fn(async () => ({ ok: true })),
  getMcpTools: vi.fn(async () => ({ ok: true, tools: [] })),
}));

// What the sidecar sends when `mcp.json` cannot be read: nothing was written, and the
// reason travels as a stable machine code (the prose is the fallback for other clients).
const REFUSED = {
  ok: false,
  name: "x",
  code: "config_unreadable",
  error: "the MCP server config file could not be read",
};

const SERVER: McpServer = {
  name: "sales-db",
  enabled: true,
  transport: "stdio",
  requires_approval: true,
  status: "configured",
  tool_count: null,
  config: { command: "sales" },
};

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("mcpErrorText", () => {
  // A stand-in for i18next's `t`: resolves "a.b" against the real English catalog, so the
  // test pins the actual keys rather than a mock's idea of them.
  const t = ((key: string) =>
    key.split(".").reduce<any>((node, k) => node?.[k], en as any) ?? key) as any;

  it("translates a known refusal code and ignores the server's English", () => {
    expect(mcpErrorText(REFUSED, t)).toBe(en.mcp.err_config_unreadable);
  });

  it("falls back to the server's words for a code this build has never heard of", () => {
    // A newer sidecar refusing for a new reason must still explain itself — specific
    // English beats a generic localized shrug.
    expect(mcpErrorText({ ok: false, code: "invented_later", error: "disk full" }, t)).toBe(
      "disk full",
    );
    expect(mcpErrorText({ ok: false, error: "disk full" }, t)).toBe("disk full");
  });

  it("falls back to the generic line when the server said nothing at all", () => {
    expect(mcpErrorText({ ok: false }, t)).toBe(en.mcp.err_save_failed);
  });
});

describe("AddMcpModal — a refused add stays open and says why", () => {
  it("shows the reason, keeps the modal open, and never probes the server", async () => {
    const { addMcpServer, connectMcp } = await import("../../api");
    vi.mocked(addMcpServer).mockResolvedValueOnce(REFUSED);
    const onClose = vi.fn();
    const onChanged = vi.fn();

    render(<AddMcpModal onClose={onClose} onChanged={onChanged} />);
    fireEvent.change(screen.getByTestId("mcp-add-name"), { target: { value: "docs" } });
    fireEvent.change(screen.getByTestId("mcp-add-url"), {
      target: { value: "https://mcp.example.com/mcp" },
    });
    fireEvent.click(screen.getByText(en.mcp.add_and_test));

    expect(await screen.findByText(en.mcp.err_config_unreadable)).toBeTruthy();
    // Nothing was saved, so there is nothing to connect to and no reason to close over
    // the user's typing.
    expect(connectMcp).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
  });

  it("closes as usual when the add succeeds", async () => {
    const { connectMcp } = await import("../../api");
    const onClose = vi.fn();

    render(<AddMcpModal onClose={onClose} onChanged={vi.fn()} />);
    fireEvent.change(screen.getByTestId("mcp-add-name"), { target: { value: "docs" } });
    fireEvent.change(screen.getByTestId("mcp-add-url"), {
      target: { value: "https://mcp.example.com/mcp" },
    });
    fireEvent.click(screen.getByText(en.mcp.add_and_test));

    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(connectMcp).toHaveBeenCalledWith("docs");
    expect(screen.queryByText(en.mcp.err_config_unreadable)).toBeNull();
  });
});

describe("CustomMcpGroup — a refused quick-add says why", () => {
  it("shows the reason on the preset row and does not start the sign-in", async () => {
    const { addMcpServer, connectMcp } = await import("../../api");
    vi.mocked(addMcpServer).mockResolvedValueOnce(REFUSED);

    render(<CustomMcpGroup servers={[]} onOpen={vi.fn()} onChanged={vi.fn()} />);
    fireEvent.click(screen.getByText(en.connector.connect));

    expect(await screen.findByTestId("mcp-preset-error")).toBeTruthy();
    expect(screen.getByText(en.mcp.err_config_unreadable)).toBeTruthy();
    expect(connectMcp).not.toHaveBeenCalled();
  });
});

describe("McpServerDetail — a refused write is never a silent snap-back", () => {
  it("explains a refused enable toggle next to the switch", async () => {
    const { patchMcpServer } = await import("../../api");
    vi.mocked(patchMcpServer).mockResolvedValueOnce(REFUSED);

    render(<McpServerDetail server={SERVER} onChanged={vi.fn()} onGone={vi.fn()} />);
    fireEvent.click(screen.getByTitle(en.mcp.enable_title));

    expect(await screen.findByTestId("mcp-write-error-sales-db")).toBeTruthy();
    expect(screen.getByText(en.mcp.err_config_unreadable)).toBeTruthy();
  });

  it("stays on the page when a remove is refused", async () => {
    const { deleteMcpServer } = await import("../../api");
    vi.mocked(deleteMcpServer).mockResolvedValueOnce(REFUSED);
    const onGone = vi.fn();

    render(<McpServerDetail server={SERVER} onChanged={vi.fn()} onGone={onGone} />);
    fireEvent.click(screen.getByTestId("mcp-remove-sales-db"));

    expect(await screen.findByTestId("mcp-remove-error-sales-db")).toBeTruthy();
    // Navigating away would leave the row sitting in the list with no explanation.
    expect(onGone).not.toHaveBeenCalled();
  });

  it("navigates away when the server was already gone", async () => {
    // Idempotent delete: a second click or a stale page is not a failure.
    const { deleteMcpServer } = await import("../../api");
    vi.mocked(deleteMcpServer).mockResolvedValueOnce({ ok: true, existed: false });
    const onGone = vi.fn();

    render(<McpServerDetail server={SERVER} onChanged={vi.fn()} onGone={onGone} />);
    fireEvent.click(screen.getByTestId("mcp-remove-sales-db"));

    await waitFor(() => expect(onGone).toHaveBeenCalled());
    expect(screen.queryByTestId("mcp-remove-error-sales-db")).toBeNull();
  });

  it("navigates away as usual when the remove succeeds", async () => {
    const onGone = vi.fn();
    render(<McpServerDetail server={SERVER} onChanged={vi.fn()} onGone={onGone} />);
    fireEvent.click(screen.getByTestId("mcp-remove-sales-db"));

    await waitFor(() => expect(onGone).toHaveBeenCalled());
    expect(screen.queryByTestId("mcp-remove-error-sales-db")).toBeNull();
  });
});
