// Drag-and-drop attach: a whole-folder drop must SAY it isn't supported (Tauri disables the
// native drag-drop handler, so a directory arrives as an unreadable HTML5 File that used to
// vanish without a trace), unsupported files are named in a skip notice, and ordinary text
// files still attach silently.
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { Composer } from "./Composer";

function stubFetch() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({ ok: true, json: async () => ({}) }) as Response),
  );
}

const props = () => ({
  mode: "interactive",
  model: "gpt-5.6-sol",
  running: false,
  connected: true,
  sessionId: "s1",
  onSend: vi.fn(),
  onInterrupt: vi.fn(),
  onModeChange: vi.fn(),
  onModelChange: vi.fn(),
});

const box = () => screen.getByPlaceholderText(/Ask the coworker/);

// The composer only reads `dataTransfer.items` / `.files`, so a hand-built stand-in is
// enough for jsdom (whose DragEvent has no real DataTransfer).
function fileItem(file: File, entry?: { isDirectory: boolean } | null) {
  return {
    kind: "file",
    getAsFile: () => file,
    webkitGetAsEntry: () => (entry === undefined ? null : entry),
  };
}

const drop = (items: ReturnType<typeof fileItem>[]) =>
  fireEvent.drop(box(), { dataTransfer: { items, files: items.map((it) => it.getAsFile()) } });

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Composer / drag-and-drop attach", () => {
  it("shows the folder notice when a directory is dropped", async () => {
    stubFetch();
    render(<Composer {...props()} />);
    drop([fileItem(new File([], "docs", { type: "" }), { isDirectory: true })]);
    const notice = await screen.findByTestId("attach-notice");
    expect(notice.textContent).toMatch(/folders can't be dropped/i);
  });

  it("names unsupported files instead of dropping them silently", async () => {
    stubFetch();
    render(<Composer {...props()} />);
    drop([
      fileItem(new File(["binary"], "report.docx", { type: "application/msword" }), {
        isDirectory: false,
      }),
    ]);
    const notice = await screen.findByTestId("attach-notice");
    expect(notice.textContent).toContain("report.docx");
  });

  it("attaches a plain text file with no notice", async () => {
    stubFetch();
    render(<Composer {...props()} />);
    drop([fileItem(new File(["hello"], "notes.txt", { type: "text/plain" }), { isDirectory: false })]);
    await waitFor(() => expect(screen.getByText("notes.txt")).toBeTruthy());
    expect(screen.queryByTestId("attach-notice")).toBeNull();
  });
});
