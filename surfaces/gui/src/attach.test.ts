import { describe, expect, it } from "vitest";
import { readFile, splitDataTransfer } from "./attach";

// Minimal stand-ins for the drop event's DataTransfer. jsdom never fires real drops, so the
// shapes a Chromium/WebView2 drop produces are modeled by hand: `items` with an optional
// webkitGetAsEntry(), and the legacy `files` list for engines without the items API.
function fileItem(file: File, entry?: { isDirectory: boolean } | null): DataTransferItem {
  return {
    kind: "file",
    getAsFile: () => file,
    webkitGetAsEntry: () => (entry === undefined ? null : entry),
  } as unknown as DataTransferItem;
}

function dataTransfer(items: DataTransferItem[] | null, files: File[] = []): DataTransfer {
  return { items, files } as unknown as DataTransfer;
}

// A dropped directory surfaces as a File with an empty MIME type and zero size.
const folderFile = (name: string) => new File([], name, { type: "" });

describe("splitDataTransfer", () => {
  it("flags a directory entry as a folder, not a file", () => {
    const dt = dataTransfer([fileItem(folderFile("docs"), { isDirectory: true })]);
    expect(splitDataTransfer(dt)).toEqual({ files: [], folders: 1 });
  });

  it("keeps regular files alongside a dropped folder", () => {
    const readme = new File(["hello"], "README.md", { type: "text/markdown" });
    const dt = dataTransfer([
      fileItem(folderFile("src"), { isDirectory: true }),
      fileItem(readme, { isDirectory: false }),
    ]);
    const out = splitDataTransfer(dt);
    expect(out.folders).toBe(1);
    expect(out.files.map((f) => f.name)).toEqual(["README.md"]);
  });

  it("falls back to the empty-type/zero-size shape when no entry is available", () => {
    const dt = dataTransfer([fileItem(folderFile("node_modules"), null)]);
    expect(splitDataTransfer(dt)).toEqual({ files: [], folders: 1 });
  });

  it("does not mistake a non-empty extensionless file for a folder", () => {
    const license = new File(["MIT License"], "LICENSE", { type: "" });
    const dt = dataTransfer([fileItem(license, null)]);
    const out = splitDataTransfer(dt);
    expect(out.folders).toBe(0);
    expect(out.files.map((f) => f.name)).toEqual(["LICENSE"]);
  });

  it("trusts an isFile entry even for an empty extensionless file", () => {
    const empty = new File([], "TODO", { type: "" });
    const dt = dataTransfer([fileItem(empty, { isDirectory: false })]);
    expect(splitDataTransfer(dt)).toEqual({ files: [empty], folders: 0 });
  });

  it("applies the folder heuristic to dt.files when the items API is missing", () => {
    const notes = new File(["x"], "notes.txt", { type: "text/plain" });
    const dt = dataTransfer(null, [folderFile("build"), notes]);
    const out = splitDataTransfer(dt);
    expect(out.folders).toBe(1);
    expect(out.files.map((f) => f.name)).toEqual(["notes.txt"]);
  });
});

describe("readFile", () => {
  it("still rejects an extensionless text file (surfaced by the composer's skip notice)", async () => {
    const license = new File(["MIT License"], "LICENSE", { type: "" });
    await expect(readFile(license)).resolves.toBeNull();
  });

  it("reads a text file by extension when the MIME type is empty", async () => {
    const notes = new File(["hello"], "notes.md", { type: "" });
    const out = await readFile(notes);
    expect(out).toMatchObject({ kind: "text", name: "notes.md", text: "hello" });
  });

  // The byte cap is whatever the caller hands in — the composer passes the user's PDF limit
  // from Settings → Token savings — so a PDF that cleared that setting can't be eaten here
  // by a second, hard-coded number. Sizes are faked: readFile() only compares `size`, and
  // allocating tens of megabytes per test buys nothing.
  const pdfOfSize = (bytes: number) => {
    const pdf = new File(["%PDF-1.4"], "big.pdf", { type: "application/pdf" });
    Object.defineProperty(pdf, "size", { value: bytes });
    return pdf;
  };

  it("keeps the built-in 10 MB cap when no limit is passed", async () => {
    await expect(readFile(pdfOfSize(10 * 1024 * 1024 + 1))).resolves.toBeNull();
  });

  it("honors a caller-supplied cap above the built-in one", async () => {
    const out = await readFile(pdfOfSize(15 * 1024 * 1024), { maxBytes: 20 * 1024 * 1024 });
    expect(out).toMatchObject({ kind: "pdf", name: "big.pdf", mime: "application/pdf" });
    expect(out?.data_url).toMatch(/^data:application\/pdf;base64,/);
  });

  it("honors a caller-supplied cap below the built-in one", async () => {
    const notes = new File(["hello"], "notes.md", { type: "text/markdown" });
    await expect(readFile(notes, { maxBytes: 4 })).resolves.toBeNull();
  });
});
