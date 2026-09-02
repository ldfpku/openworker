import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { Markdown, OPEN_APP_TARGET_EVENT, OPEN_ARTIFACT_EVENT, OPEN_BOARD_EVENT } from "./Markdown";

afterEach(cleanup);

// §34 (UX-016): [Title](artifact:path) renders as a chip that opens the artifact viewer via
// a window event; ordinary links keep the open-externally treatment.
describe("Markdown artifact links", () => {
  it("renders an artifact: link as a chip and dispatches the open event with the path", () => {
    const seen: string[] = [];
    const listener = (e: Event) => seen.push((e as CustomEvent).detail.path);
    window.addEventListener(OPEN_ARTIFACT_EVENT, listener);

    render(<Markdown text="Done — [Semiconductor dashboard](artifact:reports/semi.html)" />);
    const chip = screen.getByTestId("artifact-chip");
    expect(chip.textContent).toContain("Semiconductor dashboard");
    expect(chip.textContent).toContain("semi.html"); // filename shown under the title
    fireEvent.click(chip);
    expect(seen).toEqual(["reports/semi.html"]);

    window.removeEventListener(OPEN_ARTIFACT_EVENT, listener);
  });

  it("ordinary links stay external and never become chips", () => {
    const { container } = render(<Markdown text="see [the docs](https://example.com)" />);
    expect(screen.queryByTestId("artifact-chip")).toBeNull();
    const a = container.querySelector("a")!;
    expect(a.getAttribute("target")).toBe("_blank");
    expect(a.getAttribute("href")).toBe("https://example.com");
  });

  it("chip title falls back to the filename when the link text is empty", () => {
    vi.spyOn(window, "dispatchEvent");
    render(<Markdown text="[](artifact:out/report.pdf)" />);
    expect(screen.getByTestId("artifact-chip").textContent).toContain("report.pdf");
  });

  // Seventeenth pass: the lead's one-time board mention — [Board · 5 items](board:)
  // renders as an inline pill that opens the drawer on its Board section.
  it("renders a board: link as a pill and dispatches the open-board event", () => {
    let fired = 0;
    const listener = () => fired++;
    window.addEventListener(OPEN_BOARD_EVENT, listener);

    render(<Markdown text="Plan approved — [Board · 5 items](board:) if you want to watch." />);
    const chip = screen.getByTestId("board-chip");
    expect(chip.textContent).toContain("Board · 5 items");
    fireEvent.click(chip);
    expect(fired).toBe(1);

    window.removeEventListener(OPEN_BOARD_EVENT, listener);
  });

  // The in-app manual's [label](app:…) links. Markdown only reports the raw spec — App owns
  // the routing — so the chip must carry the spec through untouched.
  it("renders an app: link as a chip and dispatches the raw spec", () => {
    const seen: string[] = [];
    const listener = (e: Event) => seen.push((e as CustomEvent).detail.spec);
    window.addEventListener(OPEN_APP_TARGET_EVENT, listener);

    render(<Markdown text="先去 [设置 ▸ 模型](app:settings/models) 填一次 key。" />);
    const chip = screen.getByTestId("app-link-chip");
    expect(chip.textContent).toContain("设置 ▸ 模型");
    fireEvent.click(chip);
    expect(seen).toEqual(["settings/models"]);

    window.removeEventListener(OPEN_APP_TARGET_EVENT, listener);
  });
});

// Fenced code blocks get a head bar (language tag + copy button); inline `code` never does.
describe("Markdown code blocks", () => {
  it("shows the fence's language as the head-bar label", () => {
    render(<Markdown text={"```ts\nconst x = 1;\n```"} />);
    expect(screen.getByText("ts")).toBeTruthy();
    expect(document.querySelector(".codeblock")).toBeTruthy();
  });

  it("copies the block's raw text, not the head bar's", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    render(<Markdown text={"```js\nconsole.log('hi');\n```"} />);
    fireEvent.click(screen.getByTestId("codeblock-copy"));
    expect(writeText).toHaveBeenCalledWith("console.log('hi');\n");
  });

  it("a fence with no language shows no label but still offers copy", () => {
    render(<Markdown text={"```\nplain text\n```"} />);
    expect(screen.queryByText("ts")).toBeNull();
    expect(screen.getByTestId("codeblock-copy")).toBeTruthy();
  });

  it("inline code is never wrapped in a codeblock", () => {
    render(<Markdown text="see `inline` code" />);
    expect(document.querySelector(".codeblock")).toBeNull();
    expect(screen.queryByTestId("codeblock-copy")).toBeNull();
    expect(screen.getByText("inline").tagName).toBe("CODE");
  });
});
