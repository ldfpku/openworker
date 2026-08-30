import { describe, expect, it, vi } from "vitest";
// The source itself, not the rendered component: the rule is about which event a guard
// listens on, which no amount of jsdom rendering can distinguish from a working button.
import APP from "./App.tsx?raw";

// The topbar's three containers start a native window drag from `pointerdown`
// (`onPointerDown={beginWindowDrag}` → Tauri `startDragging()`). Any button living inside
// one must stop THAT event. Guarding `mousedown` instead does nothing: the two are separate
// events, pointerdown fires first, and once startDragging() runs the OS move loop owns the
// mouse and swallows the mouseup — so `click` never fires and the button is dead in the
// desktop build. That is exactly how the side-panel toggle, the Artifacts button and
// "Save as project…" stopped working (owner-hit 2026-08-31). The two tests below pin the
// rule and the reason behind it.

describe("topbar drag guard", () => {
  it("guards presses with pointerdown, never mousedown", () => {
    // App.tsx has exactly one reason to swallow a press — the drag region — so a
    // mousedown-only guard anywhere in this file is the bug, whatever the button.
    expect(APP).not.toMatch(/onMouseDown=\{\(e\) => e\.stopPropagation\(\)\}/);
    // The button the regression was reported on, specifically.
    const toggle = APP.slice(APP.indexOf('data-testid="rail-toggle"'));
    expect(toggle.slice(0, 200)).toContain("onPointerDown={(e) => e.stopPropagation()}");
  });

  it("a mousedown guard does not stop the parent's pointerdown handler", () => {
    // Why the rule exists, executably: stopPropagation on one event type is invisible
    // to the other, so the drag fires anyway.
    const drag = vi.fn();
    const parent = document.createElement("div");
    const button = document.createElement("button");
    parent.appendChild(button);
    document.body.appendChild(parent);
    parent.addEventListener("pointerdown", drag);
    button.addEventListener("mousedown", (e) => e.stopPropagation());

    button.dispatchEvent(new Event("pointerdown", { bubbles: true }));
    expect(drag).toHaveBeenCalledTimes(1); // leaked → startDragging() eats the click

    parent.removeChild(button);
    document.body.removeChild(parent);
  });
});
