// write_document renders a real .docx via the backend's office tools (from Markdown). It
// should read exactly like write_file everywhere humanize.ts renders a tool-call line, since
// both are "wrote a file at this path" — the filename extension alone already tells the
// reader it's a Word document.
import { describe, expect, it } from "vitest";
import { humanizeTool, humanizeApprovalTitle, humanizeAsk } from "./humanize";

describe("humanizeTool(write_document)", () => {
  it("renders the same Wrote-line shape as write_file", () => {
    const line = humanizeTool("write_document", { path: "reports/summary.docx" });
    expect(line.pre).toBe("Wrote ");
    expect(line.obj).toBe("summary.docx");
  });

  it("falls back to a generic filename when path is missing", () => {
    expect(humanizeTool("write_document", {}).obj).toBe("a file");
    expect(humanizeTool("write_document", null).obj).toBe("a file");
  });
});

describe("humanizeApprovalTitle(write_document)", () => {
  it("renders the Write-line shape", () => {
    const line = humanizeApprovalTitle("write_document", { path: "data/项目A报告.docx" });
    expect(line.pre).toBe("Write ");
    expect(line.obj).toBe("项目A报告.docx");
  });
});

describe("humanizeAsk(write_document)", () => {
  it("renders the Wanted-to-write-line shape", () => {
    const line = humanizeAsk("write_document", { path: "out/memo.docx" });
    expect(line.pre).toBe("Wanted to write ");
    expect(line.obj).toBe("memo.docx");
  });
});
