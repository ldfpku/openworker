import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { BackLink } from "./BackLink";
import { IconButton } from "./IconButton";
import { Toggle } from "./Toggle";

// The three shared controls exist so that no glyph-only button ships mute: one `label`
// must land as BOTH the native tooltip and the accessible name.

describe("IconButton", () => {
  it("renders the label as tooltip and accessible name, and is a plain button", () => {
    const onClick = vi.fn();
    render(<IconButton icon="trash" label="Delete weekly-report" onClick={onClick} />);
    const btn = screen.getByLabelText("Delete weekly-report");
    expect(btn.getAttribute("title")).toBe("Delete weekly-report");
    expect(btn.getAttribute("type")).toBe("button");
    expect(btn.className).toBe("icon-btn");
    fireEvent.click(btn);
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("maps variant / tone / active / small onto the .icon-btn modifiers", () => {
    render(
      <IconButton icon="x" label="Close" variant="bordered" tone="danger" active small className="ml-auto" />,
    );
    const btn = screen.getByLabelText("Close");
    expect(btn.className).toBe("icon-btn bordered danger active sm ml-auto");
    expect(btn.getAttribute("aria-pressed")).toBe("true");
  });

  it("inline variant carries no box class beyond `inline`", () => {
    render(<IconButton icon="x" label="Remove" variant="inline" />);
    expect(screen.getByLabelText("Remove").className).toBe("icon-btn inline");
  });
});

describe("BackLink", () => {
  it("draws the arrow itself so labels stay plain nouns", () => {
    const onClick = vi.fn();
    render(<BackLink onClick={onClick}>All providers</BackLink>);
    const btn = screen.getByRole("button", { name: "All providers" });
    expect(btn.className).toBe("back-link");
    expect(btn.querySelector("svg")).not.toBeNull();
    fireEvent.click(btn);
    expect(onClick).toHaveBeenCalledTimes(1);
  });
});

describe("Toggle", () => {
  it("uses `label` for both the accessible name and the tooltip", () => {
    render(<Toggle checked onChange={() => {}} label="weekly-report enabled" />);
    const sw = screen.getByRole("switch", { name: "weekly-report enabled" });
    expect(sw.getAttribute("title")).toBe("weekly-report enabled");
    expect(sw.getAttribute("aria-checked")).toBe("true");
  });

  it("an explicit title wins over the label for the tooltip", () => {
    render(<Toggle checked={false} onChange={() => {}} label="Slack enabled" title="Turn Slack on" />);
    const sw = screen.getByRole("switch", { name: "Slack enabled" });
    expect(sw.getAttribute("title")).toBe("Turn Slack on");
  });
});
