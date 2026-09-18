import { describe, expect, it } from "vitest";
// The source itself, not the rendered component (see topbarDrag.test.ts for the same
// approach and why: App.tsx is a ~2800-line component with no unit test coverage anywhere in
// this suite — importing it live would mean building a Tauri/WebSocket harness this suite
// doesn't have, just to reach one Set literal).
import APP from "./App.tsx?raw";

// What breaks if this regresses: on `tool_finished`, App.tsx refreshes the Artifacts right
// rail immediately when `FILE_WRITE_TOOLS.has(d.name)` (or the tool is a browser_* one) — see
// the comment above that check ("a file write that should appear under Artifacts immediately,
// not only after the turn"). write_spreadsheet writes a real file to disk exactly like
// write_file, so it belongs in that Set. If an upstream merge silently reverts this one line
// back to its pre-write_spreadsheet shape, nothing breaks loudly: the backend still writes the
// .xlsx correctly, the compact approval row and its preview (ApprovalCard.tsx) still render
// fine, and every other vitest case stays green — none of them exercise App.tsx's
// tool_finished handler. The only symptom is that a freshly written spreadsheet silently fails
// to appear under Artifacts until the turn ends or the user reloads (the exact class of bug
// fixed for write_file in memory note artifacts-panel-session-products.md). Hence a dedicated
// pin here, done as a source-text match rather than an import (see the comment above).
describe("App.tsx source — FILE_WRITE_TOOLS guard", () => {
  it("still lists write_spreadsheet alongside write_file (Artifacts-refresh trigger)", () => {
    const match = APP.match(/const FILE_WRITE_TOOLS = new Set\(\[([^\]]*)\]\)/);
    if (!match) {
      throw new Error(
        "FILE_WRITE_TOOLS declaration not found in App.tsx (renamed or restructured?) — update this guard test to match.",
      );
    }
    const tools = [...match[1].matchAll(/"([^"]+)"/g)].map((m) => m[1]);
    expect(tools).toContain("write_file");
    expect(tools).toContain("write_spreadsheet");
  });
});
