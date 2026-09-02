// The composer's model picker (and every other Dropdown): one click opens, the backdrop
// closes, a pick reports and closes — and `defaultOpen` mounts it already open, which is
// how a click made on the "Loading models…" placeholder gets honoured (owner-hit
// 2026-09-03: first click did nothing, second opened).
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { Dropdown } from "./Dropdown";

afterEach(cleanup);

const OPTIONS = [
  { value: "a", label: "Alpha" },
  { value: "b", label: "Beta" },
];

describe("Dropdown", () => {
  it("opens on the first click and closes on the backdrop", () => {
    const { container } = render(<Dropdown value="a" options={OPTIONS} onChange={() => {}} />);
    expect(container.querySelector(".dd-menu")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Alpha" }));
    expect(container.querySelector(".dd-menu")).not.toBeNull();
    fireEvent.click(container.querySelector(".dd-backdrop")!);
    expect(container.querySelector(".dd-menu")).toBeNull();
  });

  it("reports a pick and closes", () => {
    const onChange = vi.fn();
    const { container } = render(<Dropdown value="a" options={OPTIONS} onChange={onChange} />);
    fireEvent.click(screen.getByRole("button", { name: "Alpha" }));
    fireEvent.click(screen.getByText("Beta"));
    expect(onChange).toHaveBeenCalledWith("b");
    expect(container.querySelector(".dd-menu")).toBeNull();
  });

  it("mounts open when defaultOpen is set, and the trigger is a plain button", () => {
    const { container } = render(
      <Dropdown value="a" options={OPTIONS} onChange={() => {}} defaultOpen />,
    );
    expect(container.querySelector(".dd-menu")).not.toBeNull();
    expect(screen.getByRole("button", { name: "Alpha" }).getAttribute("type")).toBe("button");
  });
});
