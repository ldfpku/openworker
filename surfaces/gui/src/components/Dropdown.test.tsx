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

// Row extras beside the label: a quiet `tag` after the name and a short `meta` note at the
// right edge (the composer's model picker uses them for "Restricted" and the price).
describe("Dropdown — tag and meta", () => {
  const RICH = [
    { value: "a", label: "Alpha", tag: "Restricted", tagTitle: "why", meta: "$3 / $15", metaTitle: "spelled out" },
    { value: "b", label: "Beta", badge: "Free", meta: "$1 / $2" },
    { value: "c", label: "Gamma" },
  ];

  it("renders the tag after the label and the meta before the check, each with its tooltip", () => {
    const { container } = render(<Dropdown value="a" options={RICH} onChange={() => {}} defaultOpen />);
    const rows = Array.from(container.querySelectorAll(".dd-label"));
    expect(Array.from(rows[0].children).map((el) => el.className)).toEqual(["dd-tag", "dd-meta", "chk"]);
    expect(rows[0].querySelector(".dd-tag")?.getAttribute("title")).toBe("why");
    expect(rows[0].querySelector(".dd-meta")?.getAttribute("title")).toBe("spelled out");
    expect(Array.from(rows[1].children).map((el) => el.className)).toEqual(["dd-badge", "dd-meta", "chk-space"]);
    // A row with no extras still reserves the check's width, so the notes line up.
    expect(Array.from(rows[2].children).map((el) => el.className)).toEqual(["chk-space"]);
    expect(container.querySelector(".dd-menu")?.classList.contains("has-meta")).toBe(true);
  });

  it("leaves a menu without any meta exactly as it was", () => {
    const { container } = render(<Dropdown value="a" options={OPTIONS} onChange={() => {}} defaultOpen />);
    expect(container.querySelector(".dd-menu")?.classList.contains("has-meta")).toBe(false);
    expect(container.querySelector(".chk-space")).toBeNull();
    expect(container.querySelectorAll(".dd-label")[1].children).toHaveLength(0);
  });

  it("still picks the row when the click lands on the tag or the note", () => {
    const onChange = vi.fn();
    render(<Dropdown value="c" options={RICH} onChange={onChange} defaultOpen />);
    fireEvent.click(screen.getByText("$3 / $15"));
    expect(onChange).toHaveBeenCalledWith("a");
  });
});
