// F1/F7: the automation work-folder picker — button + menu (never a native <select>, so it
// never collides with ScheduledView's getByRole("combobox") schedule dropdown), the recent
// list filtered to folders that still exist, the "back to private" option, and a cancelled
// browse leaving the value untouched.
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { TaskFolderField } from "./TaskFolderField";
import { getRecentWorkspaces } from "../api";
import { chooseFolder } from "../tauri";

vi.mock("../tauri", () => ({ chooseFolder: vi.fn() }));
vi.mock("../api", () => ({
  getRecentWorkspaces: vi.fn(async () => []),
}));

afterEach(cleanup);

function renderField(value = "", onChange = vi.fn()) {
  render(<TaskFolderField value={value} onChange={onChange} />);
  return { onChange };
}

describe("TaskFolderField", () => {
  it("shows the private-folder label when no folder is chosen, and never renders a <select>", () => {
    renderField("");
    expect(screen.getByTestId("task-folder-trigger").textContent).toContain("Dedicated folder");
    expect(screen.queryByRole("combobox")).toBeNull();
  });

  it("shows the folder's base name (with the full path as a tooltip) once one is chosen", () => {
    renderField("/Users/test/OpenWorker/launch-note");
    const trigger = screen.getByTestId("task-folder-trigger");
    expect(trigger.textContent).toContain("launch-note");
    expect(trigger.querySelector('[title="/Users/test/OpenWorker/launch-note"]')).toBeTruthy();
  });

  it("lists only recent folders that still exist, capped at 5, and picking one calls onChange", async () => {
    vi.mocked(getRecentWorkspaces).mockResolvedValueOnce([
      { path: "/a", name: "a", exists: true },
      { path: "/gone", name: "gone", exists: false },
      { path: "/b", name: "b", exists: true },
      { path: "/c", name: "c", exists: true },
      { path: "/d", name: "d", exists: true },
      { path: "/e", name: "e", exists: true },
      { path: "/f", name: "f", exists: true },
    ]);
    const { onChange } = renderField();
    fireEvent.click(screen.getByTestId("task-folder-trigger"));
    expect(await screen.findByTestId("task-folder-recent-/a")).toBeTruthy();
    expect(screen.queryByTestId("task-folder-recent-/gone")).toBeNull();
    // exists-filtered recents are capped at 5 (a, b, c, d, e — f drops off).
    expect(screen.getByTestId("task-folder-recent-/e")).toBeTruthy();
    expect(screen.queryByTestId("task-folder-recent-/f")).toBeNull();

    fireEvent.click(screen.getByTestId("task-folder-recent-/b"));
    expect(onChange).toHaveBeenCalledWith("/b");
  });

  it("the private-folder option always shows and picking it sends \"\"", async () => {
    const { onChange } = renderField("/some/path");
    fireEvent.click(screen.getByTestId("task-folder-trigger"));
    fireEvent.click(await screen.findByTestId("task-folder-private-option"));
    expect(onChange).toHaveBeenCalledWith("");
  });

  it("browse: a picked path calls onChange; a null (cancel) leaves the value untouched", async () => {
    vi.mocked(chooseFolder).mockResolvedValueOnce(null);
    const { onChange } = renderField();
    fireEvent.click(screen.getByTestId("task-folder-trigger"));
    fireEvent.click(await screen.findByTestId("task-folder-browse"));
    await vi.waitFor(() => expect(chooseFolder).toHaveBeenCalled());
    expect(onChange).not.toHaveBeenCalled();
    // the menu stays open after a cancelled browse, ready for another pick
    expect(screen.getByTestId("task-folder-menu")).toBeTruthy();

    vi.mocked(chooseFolder).mockResolvedValueOnce("/picked/folder");
    fireEvent.click(screen.getByTestId("task-folder-browse"));
    await vi.waitFor(() => expect(onChange).toHaveBeenCalledWith("/picked/folder"));
  });
});
