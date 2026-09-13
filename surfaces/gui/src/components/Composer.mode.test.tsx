// The Mode chip speaks the server's vocabulary (audit 2026-09-13). The server emits canonical
// Mode values ("bypass-approvals", "custom", …) in every "ready"; before this the picker knew
// only the legacy "auto", so the chip rendered the raw id and the open menu had no ✓ anywhere.
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { Composer } from "./Composer";

function stubFetch() {
  // getSettings() drives the gated Auto-approve row; an empty object means "flag off".
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({ ok: true, json: async () => ({}) }) as Response),
  );
}

const props = (extra: Partial<Parameters<typeof Composer>[0]> = {}) => ({
  mode: "interactive",
  model: "gpt-5.6-sol",
  running: false,
  connected: true,
  // The Mode chip only renders on a workspace surface (Code/Cowork).
  workspace: "code",
  sessionId: "s1",
  onSend: vi.fn(),
  onInterrupt: vi.fn(),
  onModeChange: vi.fn(),
  onModelChange: vi.fn(),
  ...extra,
});

const chip = () => screen.getByLabelText("Mode");
/** The rows of the open menu that carry the ✓ — the current mode, and nothing else. */
const checkedRows = () =>
  within(screen.getByTestId("mode-menu"))
    .getAllByRole("button")
    .filter((b) => b.textContent?.includes("✓"));

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Composer — the Mode chip reads canonical wire values", () => {
  it('mode="bypass-approvals" shows the localized label, not the raw id', () => {
    stubFetch();
    render(<Composer {...props({ mode: "bypass-approvals" })} />);
    expect(chip().textContent).toContain("Bypass approvals");
    expect(chip().textContent).not.toContain("bypass-approvals");
    expect(chip().getAttribute("title")).toBe("Mode: Bypass approvals");
  });

  it('mode="bypass-approvals" puts the ✓ on the Bypass approvals row, and only there', () => {
    stubFetch();
    render(<Composer {...props({ mode: "bypass-approvals" })} />);
    fireEvent.click(chip());
    const checked = checkedRows();
    expect(checked).toHaveLength(1);
    expect(checked[0].textContent).toContain("Bypass approvals");
  });

  it("the legacy 'auto' spelling still lands on the same row", () => {
    stubFetch();
    render(<Composer {...props({ mode: "auto" })} />);
    expect(chip().textContent).toContain("Bypass approvals");
    fireEvent.click(chip());
    expect(checkedRows()[0].textContent).toContain("Bypass approvals");
  });

  it("picking Bypass approvals emits the canonical value", () => {
    stubFetch();
    const onModeChange = vi.fn();
    render(<Composer {...props({ onModeChange })} />);
    fireEvent.click(chip());
    fireEvent.click(
      within(screen.getByTestId("mode-menu"))
        .getAllByRole("button")
        .find((b) => b.textContent?.includes("Bypass approvals"))!,
    );
    expect(onModeChange).toHaveBeenCalledWith("bypass-approvals");
  });

  it('mode="custom" (CLI-started session) is named and gets exactly one selected row', () => {
    // Custom isn't offered in the picker, but a session can already be in it — the menu
    // synthesises the row so the ✓ has a home.
    stubFetch();
    render(<Composer {...props({ mode: "custom" })} />);
    expect(chip().textContent).toContain("Custom rules");
    fireEvent.click(chip());
    const checked = checkedRows();
    expect(checked).toHaveLength(1);
    expect(checked[0].textContent).toContain("Custom rules");
  });

  it('mode="plan" is named too, and its row is the selected one', () => {
    stubFetch();
    render(<Composer {...props({ mode: "plan" })} />);
    expect(chip().textContent).toContain("Plan");
    fireEvent.click(chip());
    const checked = checkedRows();
    expect(checked).toHaveLength(1);
    expect(checked[0].textContent).toContain("Plan");
  });
});
