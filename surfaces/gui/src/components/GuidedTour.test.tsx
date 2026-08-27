import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { GuidedTour } from "./GuidedTour";

// Assertions use the English literals (the i18next keys — see setupTests.ts). Anchors are
// bare divs carrying the same data attributes the real UI exposes; jsdom's all-zero
// getBoundingClientRect is fine — the tour only needs the elements to exist.

const ANCHORS: Array<[string, string]> = [
  ["data-tour", "new-session"],
  ["data-tour", "composer"],
  ["data-tour", "model"],
  ["data-testid", "setup-row"],
  ["data-testid", "account-row"],
];

function addAnchors(specs: Array<[string, string]>) {
  for (const [attr, value] of specs) {
    const el = document.createElement("div");
    el.setAttribute(attr, value);
    document.body.appendChild(el);
  }
}

afterEach(() => {
  cleanup();
  document.body.innerHTML = "";
});

describe("GuidedTour", () => {
  it("walks all five steps in order, then Done finishes", () => {
    addAnchors(ANCHORS);
    const onDone = vi.fn();
    render(<GuidedTour onDone={onDone} />);

    expect(screen.getByText("Start here")).toBeTruthy();
    expect(document.querySelectorAll(".tour-dots i").length).toBe(5);

    fireEvent.click(screen.getByTestId("tour-next"));
    expect(screen.getByText("Hand over the work")).toBeTruthy();
    fireEvent.click(screen.getByTestId("tour-next"));
    expect(screen.getByText("Pick a model")).toBeTruthy();
    fireEvent.click(screen.getByTestId("tour-next"));
    expect(screen.getByText("Coworker and folder")).toBeTruthy();
    fireEvent.click(screen.getByTestId("tour-next"));
    expect(screen.getByText("Experts, skills and settings")).toBeTruthy();

    // Last live step: the primary button flips to Done and finishes the tour.
    expect(screen.getByTestId("tour-next").textContent).toBe("Done");
    fireEvent.click(screen.getByTestId("tour-next"));
    expect(onDone).toHaveBeenCalledTimes(1);
  });

  it("skips steps whose anchors are missing", () => {
    addAnchors([
      ["data-tour", "composer"],
      ["data-testid", "account-row"],
    ]);
    render(<GuidedTour onDone={vi.fn()} />);

    // Step 1's anchor is absent — the tour opens straight on the composer step…
    expect(screen.getByText("Hand over the work")).toBeTruthy();
    // …and Next lands on the account step (model + setup-row skipped), already the last one.
    fireEvent.click(screen.getByTestId("tour-next"));
    expect(screen.getByText("Experts, skills and settings")).toBeTruthy();
    expect(screen.getByTestId("tour-next").textContent).toBe("Done");
  });

  it("ends immediately when no anchor exists at all", () => {
    const onDone = vi.fn();
    render(<GuidedTour onDone={onDone} />);
    expect(onDone).toHaveBeenCalled();
  });

  it("Skip tour and Escape both finish the tour", () => {
    addAnchors(ANCHORS);
    const onDone = vi.fn();
    render(<GuidedTour onDone={onDone} />);
    fireEvent.click(screen.getByTestId("tour-skip"));
    expect(onDone).toHaveBeenCalledTimes(1);

    fireEvent.keyDown(window, { key: "Escape" });
    expect(onDone).toHaveBeenCalledTimes(2);
  });
});
