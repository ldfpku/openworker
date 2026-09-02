// The rail's preview notification must be edge-triggered: a new onPreviewChange
// identity (App re-renders whenever the nav toggles) must NOT replay "open" while
// the viewer sits open — that re-collapsed a sidebar the user had just expanded
// (owner-hit 2026-08-21).
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { RightRail } from "./RightRail";
import { OPEN_ARTIFACT_EVENT } from "./Markdown";
import { getArtifacts } from "../api";

vi.mock("../api", async () => {
  const actual: any = await vi.importActual("../api");
  return {
    ...actual,
    getArtifacts: vi.fn().mockResolvedValue([]),
    getRoots: vi.fn().mockResolvedValue([]),
    getJournalCases: vi.fn().mockResolvedValue([]),
    readArtifact: vi.fn().mockResolvedValue({ ok: true, path: "r.md", kind: "markdown", content: "x" }),
    revealArtifact: vi.fn().mockResolvedValue({ ok: true }),
  };
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function rail(onPreviewChange: (open: boolean) => void) {
  return (
    <RightRail
      active
      sessionId="s1"
      refreshKey={0}
      toolNames={[]}
      todo={[]}
      running={false}
      onPreviewChange={onPreviewChange}
    />
  );
}

describe("RightRail preview notification", () => {
  it("fires only on open/close transitions, not on callback identity changes", async () => {
    const first = vi.fn();
    const { rerender } = render(rail(first));
    await act(async () => {});
    expect(first).not.toHaveBeenCalled(); // closed at mount: no "closed" replay either

    // Open the viewer via a transcript chip event.
    await act(async () => {
      window.dispatchEvent(
        new CustomEvent(OPEN_ARTIFACT_EVENT, { detail: { path: "r.md" } }),
      );
    });
    expect(first).toHaveBeenCalledTimes(1);
    expect(first).toHaveBeenLastCalledWith(true);

    // App re-renders with a NEW callback identity (e.g. the user expanded the nav).
    const second = vi.fn();
    rerender(rail(second));
    await act(async () => {});
    // The viewer never transitioned, so the new callback must not be told "open".
    expect(second).not.toHaveBeenCalled();
  });
});

function railBase(refreshKey: number) {
  return (
    <RightRail
      active
      sessionId="s1"
      refreshKey={refreshKey}
      toolNames={[]}
      todo={[]}
      running={false}
    />
  );
}

const FILE_A = { path: "out/report.md", name: "report.md", kind: "markdown", size: 120, modified_at: 0 };

describe("RightRail Artifacts — load failure vs empty", () => {
  it("shows a retryable failure state (not the empty copy) when the first fetch is rejected, and recovers on retry", async () => {
    vi.mocked(getArtifacts).mockRejectedValueOnce(new Error("network"));
    render(railBase(0));
    fireEvent.click(screen.getByTestId("rail-toggle-artifacts"));

    expect(await screen.findByText("Could not load files.")).toBeTruthy();
    expect(screen.queryByText("No previewable files yet.")).toBeNull();

    vi.mocked(getArtifacts).mockResolvedValueOnce([FILE_A]);
    fireEvent.click(screen.getByTestId("artifacts-retry"));

    expect(await screen.findByText("report.md")).toBeTruthy();
    expect(screen.queryByText("Could not load files.")).toBeNull();
  });

  it("a failed refresh keeps showing the previously loaded files instead of clobbering them", async () => {
    vi.mocked(getArtifacts).mockResolvedValueOnce([FILE_A]);
    const { rerender } = render(railBase(0));
    fireEvent.click(screen.getByTestId("rail-toggle-artifacts"));
    expect(await screen.findByText("report.md")).toBeTruthy();

    // A refreshKey bump mirrors the periodic/on-event reload the rail already performs.
    vi.mocked(getArtifacts).mockRejectedValueOnce(new Error("network"));
    rerender(railBase(1));
    await waitFor(() => expect(getArtifacts).toHaveBeenCalledTimes(2));

    expect(screen.getByText("report.md")).toBeTruthy();
    expect(screen.queryByText("Could not load files.")).toBeNull();
  });
});
