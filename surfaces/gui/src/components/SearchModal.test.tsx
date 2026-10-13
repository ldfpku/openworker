import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { SearchModal } from "./SearchModal";
import type { SessionInfo } from "../types";

const session = (id: string, title: string, extra: Partial<SessionInfo> = {}): SessionInfo => ({
  session_id: id,
  title,
  workspace: "",
  agent: "cowork",
  model: "m",
  mode: "interactive",
  updated_at: "2026-06-29",
  messages: 1,
  ...extra,
});

const SESSIONS = [
  session("s-1", "weekly plan"),
  session("s-2", "launch note", { pinned: true }),
  session("s-3", "last quarter numbers", { archived: true, updated_at: "2026-05-01" }),
  session("__run__1", "hidden run", { archived: true }),
];

afterEach(cleanup);

describe("SearchModal", () => {
  // Archived conversations used to be dropped from search entirely, so the one tool for
  // "where did that chat go" could not find the ones that had been put away.
  it("finds archived conversations, listed last under their own heading", () => {
    const onSelect = vi.fn();
    const onClose = vi.fn();
    render(<SearchModal sessions={SESSIONS} onSelect={onSelect} onClose={onClose} />);

    const group = screen.getByTestId("search-archived");
    expect(group.textContent).toContain("Archived chats");
    expect(group.textContent).toContain("last quarter numbers");
    expect(screen.queryByText("hidden run")).toBeNull(); // internal sessions stay hidden
    const titles = screen.getAllByRole("button").map((b) => b.textContent || "");
    expect(titles.findIndex((x) => x.includes("last quarter"))).toBe(titles.length - 1);

    const input = screen.getByPlaceholderText("Search chats");
    fireEvent.change(input, { target: { value: "quarter" } });
    expect(screen.queryByText("weekly plan")).toBeNull();
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onSelect).toHaveBeenCalledWith("s-3", "", "cowork");
    expect(onClose).toHaveBeenCalled();
  });

  it("no archived matches → no Archived heading", () => {
    render(<SearchModal sessions={SESSIONS.slice(0, 2)} onSelect={vi.fn()} onClose={vi.fn()} />);
    expect(screen.queryByTestId("search-archived")).toBeNull();
  });
});
