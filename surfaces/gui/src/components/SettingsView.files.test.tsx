// Item 6 — "Settings › General › Files": the scratch-base card shows the real, resolved
// path (not a static placeholder), warns when the configured location degraded to the
// default, and treats an empty save as a legitimate "reset to default" rather than a
// disabled/rejected action. Same rendering approach as SettingsView.trust.test.tsx: the
// card isn't exported on its own, so this mounts the whole SettingsView (General is the
// default tab) with a full ../api mock.
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { SettingsView } from "./SettingsView";

const getSettings = vi.fn();
const setScratchBase = vi.fn();

vi.mock("../api", () => ({
  getSettings: (...args: unknown[]) => getSettings(...args),
  getTrustedWorkspaces: vi.fn(async () => [] as unknown[]),
  setAutoApprove: vi.fn(async () => ({ ok: true })),
  setAutoApproveShadow: vi.fn(async () => ({ ok: true })),
  setCompactionSettings: vi.fn(async () => ({ ok: true })),
  setContextBar: vi.fn(async () => ({ ok: true })),
  setOnboarded: vi.fn(async () => ({ ok: true, onboarded: false })),
  setPdfSettings: vi.fn(async () => ({ ok: true })),
  setScratchBase: (...args: unknown[]) => setScratchBase(...args),
  setSessionsPeek: vi.fn(async () => ({ ok: true })),
  setWorkspaceTrusted: vi.fn(async () => ({ ok: true })),
}));

const BASE_SETTINGS = {
  sessions_peek: 5,
  context_bar: false,
};

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("SettingsView — Files card (item 6: scratch-base default/degradation UX)", () => {
  it("shows the real resolved default path and the unset hint when nothing is configured", async () => {
    getSettings.mockResolvedValue({
      ...BASE_SETTINGS,
      scratch_base: "~/OpenWorker",
      scratch_base_effective: "C:\\Users\\dev\\OpenWorker",
      scratch_base_error: null,
    });

    render(<SettingsView />);

    const input = (await screen.findByPlaceholderText(
      "C:\\Users\\dev\\OpenWorker",
    )) as HTMLInputElement;
    // Unset: the field stays blank (the placeholder carries the real path), not pre-filled
    // with the literal default string.
    expect(input.value).toBe("");
    expect(await screen.findByText(/not set — using the default location/)).toBeTruthy();
    // No writability problem → no red warning.
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("saves a custom path and shows the saved confirmation", async () => {
    // Every card in the General tab (Sidebar/ContextBar/AutoApprove/Files) fetches
    // getSettings() independently on mount, so a single steady value (rather than
    // mockResolvedValueOnce sequencing) is what's actually deterministic here.
    getSettings.mockResolvedValue({
      ...BASE_SETTINGS,
      scratch_base: "~/OpenWorker",
      scratch_base_effective: "C:\\Users\\dev\\OpenWorker",
      scratch_base_error: null,
    });
    setScratchBase.mockResolvedValue({ ok: true, scratch_base: "D:\\coworker-files" });

    render(<SettingsView />);
    const input = (await screen.findByPlaceholderText(
      "C:\\Users\\dev\\OpenWorker",
    )) as HTMLInputElement;

    fireEvent.change(input, { target: { value: "D:\\coworker-files" } });
    fireEvent.click(screen.getByText("Save"));

    await waitFor(() => expect(setScratchBase).toHaveBeenCalledWith("D:\\coworker-files"));
    expect(await screen.findByText("Saved.")).toBeTruthy();
  });

  it("shows the backend's error message inline when saving fails, without clearing the draft", async () => {
    getSettings.mockResolvedValue({
      ...BASE_SETTINGS,
      scratch_base: "~/OpenWorker",
      scratch_base_effective: "C:\\Users\\dev\\OpenWorker",
      scratch_base_error: null,
    });
    setScratchBase.mockResolvedValue({ ok: false, error: "目录不可写：Permission denied" });

    render(<SettingsView />);
    const input = (await screen.findByPlaceholderText(
      "C:\\Users\\dev\\OpenWorker",
    )) as HTMLInputElement;

    fireEvent.change(input, { target: { value: "Z:\\no-access" } });
    fireEvent.click(screen.getByText("Save"));

    expect(await screen.findByText("目录不可写：Permission denied")).toBeTruthy();
    expect(input.value).toBe("Z:\\no-access"); // the draft survives a failed save
  });

  it("submits an empty path as a reset-to-default (Save is never disabled)", async () => {
    getSettings.mockResolvedValue({
      ...BASE_SETTINGS,
      scratch_base: "D:\\coworker-files",
      scratch_base_effective: "D:\\coworker-files",
      scratch_base_error: null,
    });
    setScratchBase.mockResolvedValue({ ok: true, scratch_base: "~/OpenWorker" });

    render(<SettingsView />);
    // Pre-filled with the previously-configured custom path.
    const input = (await screen.findByDisplayValue("D:\\coworker-files")) as HTMLInputElement;

    const saveButton = screen.getByText("Save") as HTMLButtonElement;
    expect(saveButton.disabled).toBe(false);

    fireEvent.change(input, { target: { value: "" } });
    expect(saveButton.disabled).toBe(false); // never disables on a blank field
    fireEvent.click(saveButton);

    await waitFor(() => expect(setScratchBase).toHaveBeenCalledWith(""));
    expect(await screen.findByText("Restored the default location.")).toBeTruthy();
  });

  it("shows a red warning when the configured location degraded to the default", async () => {
    getSettings.mockResolvedValue({
      ...BASE_SETTINGS,
      scratch_base: "Z:\\no-access",
      scratch_base_effective: "C:\\Users\\dev\\OpenWorker",
      scratch_base_error: "「Z:\\no-access」不可写（Permission denied），已改用默认目录 C:\\Users\\dev\\OpenWorker",
    });

    render(<SettingsView />);

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("Permission denied");
  });

  it("still renders a clear blank/placeholder + unset hint + red alert when even the default is unwritable", async () => {
    // Double failure (backend: both the configured base AND ~/OpenWorker are unwritable) —
    // nothing was ever configured (scratch_base stays the literal default string), so the
    // draft input, the placeholder, and the unset hint all render exactly as the unset case
    // does, alongside the red alert; none of the three should be dropped or garbled just
    // because the "effective" path the placeholder shows is itself the broken one.
    getSettings.mockResolvedValue({
      ...BASE_SETTINGS,
      scratch_base: "~/OpenWorker",
      scratch_base_effective: "C:\\Users\\dev\\OpenWorker",
      scratch_base_error:
        "「~/OpenWorker」与默认目录 C:\\Users\\dev\\OpenWorker 均不可写（Permission denied / Permission denied）",
    });

    render(<SettingsView />);

    const input = (await screen.findByPlaceholderText(
      "C:\\Users\\dev\\OpenWorker",
    )) as HTMLInputElement;
    expect(input.value).toBe(""); // draft stays blank, same as the ordinary unset case
    expect(await screen.findByText(/not set — using the default location/)).toBeTruthy();

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("均不可写");
  });
});
