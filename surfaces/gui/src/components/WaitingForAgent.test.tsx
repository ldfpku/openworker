// Elapsed-wait indicator: the first ELAPSED_THRESHOLD_MS (10s) render exactly the pre-existing
// copy; past it, an elapsed-time suffix appears and ticks every second off Date.now(), not an
// accumulating counter (see relTime.ts formatElapsed). See memory note
// truncated-turn-reporting-and-auto-retry.md for why a stuck wait needs an on-screen signal.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render, screen } from "@testing-library/react";
import { WaitingForAgent } from "./WaitingForAgent";

// setupTests.ts already ran initI18n() against the global i18next instance (jsdom's
// navigator language is en-US), so no I18nextProvider wrapper is needed here — same
// convention as InboxItemCard.test.tsx.
const advance = (ms: number) => act(() => vi.advanceTimersByTimeAsync(ms));

function renderWaiting(label?: string) {
  return render(<WaitingForAgent label={label} />);
}

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("WaitingForAgent", () => {
  it("shows the plain label for the first 9 seconds", async () => {
    renderWaiting();
    await advance(9_000);
    expect(screen.getByText("Waiting for agent...")).toBeTruthy();
    expect(screen.queryByText(/Waiting for the agent…/)).toBeNull();
  });

  it("grows an elapsed-time suffix at 12 seconds", async () => {
    renderWaiting();
    await advance(12_000);
    expect(screen.getByText("Waiting for the agent… 12s")).toBeTruthy();
  });

  it("shows minutes and seconds past a minute of waiting", async () => {
    renderWaiting();
    await advance(75_000);
    expect(screen.getByText("Waiting for the agent… 1m 15s")).toBeTruthy();
  });

  it("clears its interval on unmount", async () => {
    const clearSpy = vi.spyOn(globalThis, "clearInterval");
    const { unmount } = renderWaiting();
    await advance(12_000);
    unmount();
    expect(clearSpy).toHaveBeenCalled();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("never ticks or shows an elapsed suffix when a custom label (e.g. compacting) is given", async () => {
    renderWaiting("Compacting context…");
    await advance(60_000);
    expect(screen.getByText("Compacting context…")).toBeTruthy();
    // No interval was ever started for the labeled case.
    expect(vi.getTimerCount()).toBe(0);
  });
});
