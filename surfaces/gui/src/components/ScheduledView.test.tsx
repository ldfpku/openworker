import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { ScheduledView } from "./ScheduledView";
import { getAutomation, updateAutomation, type Automation } from "../api";

vi.mock("../api", () => ({
  announceAutomationsChanged: vi.fn(),
  createAutomation: vi.fn(),
  deleteAutomation: vi.fn(),
  getAutomation: vi.fn(),
  getAutomations: vi.fn().mockResolvedValue([]),
  markAutomationSeen: vi.fn().mockResolvedValue(undefined),
  updateAutomation: vi.fn().mockResolvedValue({}),
}));

vi.mock("./AutomationQuickstart", () => ({
  AutomationQuickstart: () => <div data-testid="automation-quickstart" />,
}));

vi.mock("./IntegrationsView", () => ({
  PanelHead: ({ title, sub }: { title: string; sub: string }) => (
    <header>
      <h1>{title}</h1>
      <p>{sub}</p>
    </header>
  ),
}));

afterEach(cleanup);

describe("ScheduledView empty state", () => {
  it("renders translated emphasis as a strong element, not literal markup", () => {
    const { container } = render(
      <ScheduledView onOpenRun={vi.fn()} onRunNow={vi.fn()} />,
    );

    expect(
      screen.getByText("+ New automation", { selector: "strong" }),
    ).toBeTruthy();
    expect(container.textContent).not.toContain("<strong>");
  });
});

const task = (cron: string): Automation => ({
  id: "t1",
  title: "Spare-parts stock alert",
  instructions: "Check the ledger.",
  schedule: "Mondays at 08:30",
  schedule_raw: { kind: "cron", cron },
  workspace: "w",
  agent: "a",
  enabled: true,
  next_run: null,
  last_run: null,
  last_status: null,
  run_count: 0,
  notify_on_completion: false,
  always_allowed: [],
});

async function openEditor(cron: string) {
  vi.mocked(getAutomation).mockResolvedValue({ task: task(cron), runs: [] });
  render(<ScheduledView onOpenRun={vi.fn()} onRunNow={vi.fn()} initialOpenId="t1" />);
  fireEvent.click(await screen.findByText("Edit"));
  return screen.getByRole("combobox") as HTMLSelectElement;
}

describe("TaskDetail schedule editing", () => {
  it("keeps a single-day cron on save instead of collapsing it to daily", async () => {
    const select = await openEditor("30 8 * * 1");

    expect(select.value).toBe("mon"); // pre-fix this fell back to "daily"
    expect(screen.queryByTestId("cron-rewrite-warning")).toBeNull();

    fireEvent.click(screen.getByText("Save"));
    expect(vi.mocked(updateAutomation)).toHaveBeenCalledWith(
      "t1",
      expect.objectContaining({ cron: "30 8 * * 1" }),
    );
  });

  it("warns that saving rewrites a cron the simple form can't express", async () => {
    const select = await openEditor("*/10 * * * *");

    expect(select.value).toBe("daily");
    expect(screen.getByTestId("cron-rewrite-warning").textContent).toContain("*/10 * * * *");
  });
});
