// Async artifact reads are session-owned: late work must never overwrite the active rail.
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ArtifactContent, ArtifactInfo } from "../api";
import { getArtifacts, readArtifact } from "../api";
import { RightRail } from "./RightRail";
import { OPEN_ARTIFACT_EVENT } from "./Markdown";

vi.mock("../api", async () => {
  const actual: any = await vi.importActual("../api");
  return {
    ...actual,
    getArtifacts: vi.fn(),
    getRoots: vi.fn().mockResolvedValue([]),
    getJournalCases: vi.fn().mockResolvedValue([]),
    readArtifact: vi.fn(),
    revealArtifact: vi.fn().mockResolvedValue({ ok: true }),
  };
});

vi.mock("./AccessSection", () => ({ AccessSection: () => null }));

const artifact = (name: string): ArtifactInfo => ({
  path: name,
  name,
  kind: "markdown",
  size: 10,
  modified_at: 1,
});

const content = (path: string, body: string): ArtifactContent => ({
  ok: true,
  path,
  kind: "markdown",
  content: body,
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

const baseProps = {
  active: true,
  sessionId: "session-a",
  refreshKey: 0,
  toolNames: [],
  todo: [],
  running: false,
};

// The fork starts every rail section collapsed; expand Artifacts so rows render.
const expandArtifacts = () => fireEvent.click(screen.getByTestId("rail-toggle-artifacts"));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("RightRail artifact request ownership", () => {
  it("clears the previous session's artifacts while the current list is loading", async () => {
    const currentRequest = deferred<ArtifactInfo[]>();
    vi.mocked(getArtifacts)
      .mockResolvedValueOnce([artifact("previous.md")])
      .mockReturnValueOnce(currentRequest.promise);

    const { rerender } = render(<RightRail {...baseProps} />);
    expandArtifacts();
    expect(await screen.findByText("previous.md")).toBeTruthy();

    rerender(<RightRail {...baseProps} sessionId="session-b" />);
    expect(screen.queryByText("previous.md")).toBeNull();

    await act(async () => currentRequest.resolve([artifact("current.md")]));
    expect(screen.getByText("current.md")).toBeTruthy();
  });

  it("ignores an artifact-list response from the previous session", async () => {
    const oldRequest = deferred<ArtifactInfo[]>();
    const currentRequest = deferred<ArtifactInfo[]>();
    vi.mocked(getArtifacts)
      .mockReturnValueOnce(oldRequest.promise)
      .mockReturnValueOnce(currentRequest.promise);

    const { rerender } = render(<RightRail {...baseProps} />);
    expandArtifacts();
    rerender(<RightRail {...baseProps} sessionId="session-b" />);

    await act(async () => currentRequest.resolve([artifact("current.md")]));
    expect(screen.getByText("current.md")).toBeTruthy();

    await act(async () => oldRequest.resolve([artifact("stale.md")]));
    expect(screen.getByText("current.md")).toBeTruthy();
    expect(screen.queryByText("stale.md")).toBeNull();
  });

  it("ignores a rejected artifact-list request after a newer request succeeds", async () => {
    const oldRequest = deferred<ArtifactInfo[]>();
    const currentRequest = deferred<ArtifactInfo[]>();
    vi.mocked(getArtifacts)
      .mockReturnValueOnce(oldRequest.promise)
      .mockReturnValueOnce(currentRequest.promise);

    const { rerender } = render(<RightRail {...baseProps} />);
    expandArtifacts();
    rerender(<RightRail {...baseProps} sessionId="session-b" />);

    await act(async () => currentRequest.resolve([artifact("current.md")]));
    await act(async () => oldRequest.reject(new Error("stale failure")));

    expect(screen.getByText("current.md")).toBeTruthy();
    expect(screen.queryByText("Could not load files.")).toBeNull();
  });

  it("ignores file content that finishes after the user selects another artifact", async () => {
    const firstRead = deferred<ArtifactContent>();
    const secondRead = deferred<ArtifactContent>();
    vi.mocked(getArtifacts).mockResolvedValue([artifact("first.md"), artifact("second.md")]);
    vi.mocked(readArtifact).mockImplementation((_sessionId, path) =>
      path === "first.md" ? firstRead.promise : secondRead.promise,
    );

    render(<RightRail {...baseProps} />);
    expandArtifacts();
    fireEvent.click(await screen.findByText("first.md"));
    fireEvent.click(screen.getByTestId("artifact-close"));
    fireEvent.click(screen.getByText("second.md"));

    await act(async () => secondRead.resolve(content("second.md", "Current content")));
    expect(screen.getByText("Current content")).toBeTruthy();

    await act(async () => firstRead.resolve(content("first.md", "Stale content")));
    expect(screen.getByText("Current content")).toBeTruthy();
    expect(screen.queryByText("Stale content")).toBeNull();
  });

  it("a chip clicked while the rail is hidden still opens the viewer when the unhide refresh overlaps", async () => {
    const chipRequest = deferred<ArtifactInfo[]>();
    const unhideRequest = deferred<ArtifactInfo[]>();
    vi.mocked(getArtifacts)
      .mockReturnValueOnce(chipRequest.promise)
      .mockReturnValueOnce(unhideRequest.promise);
    vi.mocked(readArtifact).mockResolvedValue(content("report.md", "Report body"));

    const { rerender } = render(<RightRail {...baseProps} active={false} />);
    await act(async () => {
      window.dispatchEvent(new CustomEvent(OPEN_ARTIFACT_EVENT, { detail: { path: "report.md" } }));
    });
    // App unhides the rail on the same click, which starts its own list refresh.
    rerender(<RightRail {...baseProps} />);

    await act(async () => unhideRequest.resolve([artifact("report.md")]));
    await act(async () => chipRequest.resolve([artifact("report.md")]));

    expect(await screen.findByText("Report body")).toBeTruthy();
  });

  it("drops a chip lookup that finishes after the session switched", async () => {
    const chipRequest = deferred<ArtifactInfo[]>();
    vi.mocked(getArtifacts)
      .mockResolvedValueOnce([])
      .mockReturnValueOnce(chipRequest.promise)
      .mockResolvedValue([]);

    const { rerender } = render(<RightRail {...baseProps} />);
    await act(async () => {});
    await act(async () => {
      window.dispatchEvent(new CustomEvent(OPEN_ARTIFACT_EVENT, { detail: { path: "old.md" } }));
    });
    rerender(<RightRail {...baseProps} sessionId="session-b" />);
    await act(async () => chipRequest.resolve([artifact("old.md")]));

    expect(screen.queryByTestId("artifact-close")).toBeNull();
    expect(readArtifact).not.toHaveBeenCalled();
  });
});
