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

  it("keeps both complaints when a folder and an unsupported file land in one drop", async () => {
    stubFetch();
    render(<Composer {...props()} />);
    drop([
      fileItem(new File([], "docs", { type: "" }), { isDirectory: true }),
      fileItem(new File(["binary"], "report.docx", { type: "application/msword" }), {
        isDirectory: false,
      }),
    ]);
    const notice = await screen.findByTestId("attach-notice");
    await waitFor(() => expect(notice.textContent).toContain("report.docx"));
    expect(notice.textContent).toMatch(/folders can't be dropped/i);
  });

  it("attaches a plain text file with no notice", async () => {
    stubFetch();
    render(<Composer {...props()} />);
    drop([fileItem(new File(["hello"], "notes.txt", { type: "text/plain" }), { isDirectory: false })]);
    await waitFor(() => expect(screen.getByText("notes.txt")).toBeTruthy());
    expect(screen.queryByTestId("attach-notice")).toBeNull();
  });
});

// Settings → Token savings owns the PDF size limit. A PDF under that limit must attach even
// when it is over the reader's own 10 MB default — otherwise the "skipped … up to 10 MB"
// notice contradicts the limit the user just set. Sizes are faked (the composer and the
// reader only compare `size`), and inspect-pdf answers with a small page count so the byte
// gates are the only thing under test.
describe("Composer / PDF size limit from settings", () => {
  function stubFetchWithPdfLimit(mb: number) {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string | URL | Request) => {
        const path = String(url);
        const body = path.endsWith("/v1/settings")
          ? { pdf_max_mb: mb, pdf_max_pages: 20 }
          : path.endsWith("/v1/attachments/inspect-pdf")
            ? { ok: true, pages: 3, bytes: 1 }
            : {};
        return { ok: true, json: async () => body } as Response;
      }),
    );
  }

  const pdfOfMb = (mb: number) => {
    const pdf = new File(["%PDF-1.4"], "deck.pdf", { type: "application/pdf" });
    Object.defineProperty(pdf, "size", { value: mb * 1024 * 1024 });
    return pdf;
  };

  it("attaches a PDF between 10 MB and the user's higher limit instead of skipping it", async () => {
    stubFetchWithPdfLimit(20);
    render(<Composer {...props()} />);
    drop([fileItem(pdfOfMb(15), { isDirectory: false })]);
    await waitFor(() => expect(screen.getByText("deck.pdf")).toBeTruthy());
    expect(screen.queryByTestId("attach-notice")).toBeNull();
  });

  it("rejects a PDF over the user's limit with the limit-specific notice", async () => {
    stubFetchWithPdfLimit(20);
    render(<Composer {...props()} />);
    drop([fileItem(pdfOfMb(25), { isDirectory: false })]);
    const notice = await screen.findByTestId("attach-notice");
    expect(notice.textContent).toContain("deck.pdf");
    expect(notice.textContent).toContain("20 MB limit");
    expect(screen.queryByText("deck.pdf")).toBeNull(); // no chip — the exact-name match is the chip
  });
});
