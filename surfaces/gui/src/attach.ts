import type { Attachment } from "./types";

const MAX_BYTES = 10 * 1024 * 1024; // skip files larger than ~10MB
const TEXT_RE =
  /\.(txt|md|markdown|csv|tsv|json|ya?ml|log|ini|toml|py|js|ts|tsx|jsx|rs|go|java|c|h|cpp|sh|html?|css|sql|xml)$/i;

// Read a File into an Attachment (image/PDF → data URL, text → inline text). Returns null for
// unsupported types or oversized files. Shared by the composer and the session start panel.
export const isPdfFile = (file: File) =>
  file.type === "application/pdf" || /\.pdf$/i.test(file.name);

// Split a drop's DataTransfer into attachable files and folder entries. Folders must be
// caught HERE: with Tauri's native drag-drop handler disabled, a dropped directory arrives
// as an HTML5 File whose FileReader only errors, so readFile() would swallow it without a
// trace. webkitGetAsEntry() (present in WebView2/Chromium) is authoritative when it returns
// an entry; otherwise fall back to the shape a directory File takes — no MIME type and zero
// bytes. A real extensionless text file keeps its byte size, so it stays a file.
export function splitDataTransfer(dt: DataTransfer): { files: File[]; folders: number } {
  const looksLikeFolder = (f: File) => f.type === "" && f.size === 0;
  const files: File[] = [];
  let folders = 0;
  const items = dt.items ? Array.from(dt.items) : [];
  if (items.some((it) => it.kind === "file")) {
    for (const item of items) {
      if (item.kind !== "file") continue;
      const entry = item.webkitGetAsEntry?.();
      if (entry?.isDirectory) {
        folders += 1;
        continue;
      }
      const file = item.getAsFile();
      if (!file) continue;
      if (!entry && looksLikeFolder(file)) folders += 1;
      else files.push(file);
    }
  } else {
    for (const file of Array.from(dt.files)) {
      if (looksLikeFolder(file)) folders += 1;
      else files.push(file);
    }
  }
  return { files, folders };
}

export function readFile(file: File): Promise<Attachment | null> {
  const isImage = file.type.startsWith("image/");
  const isPdf = isPdfFile(file);
  const isText = !isPdf && (file.type.startsWith("text/") || TEXT_RE.test(file.name));
  if ((!isImage && !isPdf && !isText) || file.size > MAX_BYTES) return Promise.resolve(null);
  return new Promise((resolve) => {
    const reader = new FileReader();
    reader.onerror = () => resolve(null);
    reader.onload = () =>
      resolve(
        isImage
          ? { kind: "image", name: file.name || "image", mime: file.type, data_url: String(reader.result) }
          : isPdf
            ? { kind: "pdf", name: file.name || "file.pdf", mime: "application/pdf", data_url: String(reader.result) }
            : { kind: "text", name: file.name || "file.txt", mime: file.type, text: String(reader.result) },
      );
    if (isImage || isPdf) reader.readAsDataURL(file);
    else reader.readAsText(file);
  });
}
