// write_spreadsheet writes a real .xlsx via the backend's office tools (load_office_tools
// gates it into the tool list first). It should read exactly like write_file everywhere
// humanize.ts renders a tool-call line, since both are "wrote a file at this path" — the
// filename extension alone already tells the reader it's a spreadsheet.
import { describe, expect, it } from "vitest";
import { humanizeTool, humanizeApprovalTitle, humanizeAsk } from "./humanize";

describe("humanizeTool(write_spreadsheet)", () => {
  it("renders the same Wrote-line shape as write_file", () => {
    const line = humanizeTool("write_spreadsheet", { path: "reports/summary.xlsx" });
    expect(line.pre).toBe("Wrote ");
    expect(line.obj).toBe("summary.xlsx");
  });

  it("falls back to a generic filename when path is missing", () => {
    expect(humanizeTool("write_spreadsheet", {}).obj).toBe("a file");
    expect(humanizeTool("write_spreadsheet", null).obj).toBe("a file");
  });
});

describe("humanizeApprovalTitle(write_spreadsheet)", () => {
  it("renders the Write-line shape", () => {
    const line = humanizeApprovalTitle("write_spreadsheet", { path: "data/项目A清单.xlsx" });
    expect(line.pre).toBe("Write ");
    expect(line.obj).toBe("项目A清单.xlsx");
  });
});

describe("humanizeAsk(write_spreadsheet)", () => {
  it("renders the Wanted-to-write-line shape", () => {
    const line = humanizeAsk("write_spreadsheet", { path: "out/table.xlsx" });
    expect(line.pre).toBe("Wanted to write ");
    expect(line.obj).toBe("table.xlsx");
  });
});
