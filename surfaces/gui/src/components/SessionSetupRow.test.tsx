// The composer's coworker picker (owner ask 2026-09-10): a switch turns the specialist
// coworker off for this draft (→ the general OpenWorker) and back on (→ the last one
// picked), and every row has a "View" that opens the read-only glance at that coworker.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { SessionSetupRow } from "./SessionSetupRow";
import type { Persona } from "../api";

vi.mock("../tauri", () => ({ chooseFolder: vi.fn() }));
vi.mock("../api", () => ({
  getRecentWorkspaces: vi.fn(async () => []),
  openWorkspace: vi.fn(async (path: string) => ({ ok: true, path })),
}));

afterEach(cleanup);
beforeEach(() => {
  try {
    localStorage.clear();
  } catch {
    /* jsdom without storage */
  }
});

const persona = (id: string, name: string, extra: Partial<Persona> = {}): Persona => ({
  id,
  name,
  icon: "",
  tagline: "",
  requires_folder: false,
  builtin: true,
  tools: [],
  enabled: true,
  surfaced: true,
  default: id === "cowork",
  ...extra,
});

const PERSONAS = [
  persona("cowork", "OpenWorker"),
  persona("production-planning", "生产计划与排产", { tagline: "为交期负责" }),
  persona("ops", "Ops Coworker"),
];

function renderRow(agent: string, overrides: Partial<Parameters<typeof SessionSetupRow>[0]> = {}) {
  const onPickCoworker = vi.fn();
  const onPeek = vi.fn();
  render(
    <SessionSetupRow
      personas={PERSONAS}
      agent={agent}
      showFolder={false}
      folderName={null}
      onPickCoworker={onPickCoworker}
      onPickFolder={() => {}}
      onManage={() => {}}
      onImport={() => {}}
      onPeek={onPeek}
      {...overrides}
    />,
  );
  return { onPickCoworker, onPeek };
}

describe("SessionSetupRow — specialist switch", () => {
  it("switching off re-targets the draft to the general OpenWorker", () => {
    const { onPickCoworker } = renderRow("production-planning");
    expect(screen.getByTestId("coworker-chip").textContent).toContain("生产计划与排产");
    fireEvent.click(screen.getByTestId("coworker-chip"));
    const sw = screen.getByRole("switch", { name: "Use a specialist coworker" });
    expect(sw.getAttribute("aria-checked")).toBe("true");
    fireEvent.click(sw);
    expect(onPickCoworker).toHaveBeenCalledWith("cowork");
  });

  it("switching on brings back the last specialist picked on this machine", () => {
    // A previous draft ran on production-planning; this one is on the general coworker.
    localStorage.setItem("openworker.lastSpecialistCoworker", "production-planning");
    const { onPickCoworker } = renderRow("cowork");
    expect(screen.getByTestId("coworker-chip").textContent).toContain("OpenWorker (general)");
    fireEvent.click(screen.getByTestId("coworker-chip"));
    const sw = screen.getByRole("switch", { name: "Use a specialist coworker" });
    expect(sw.getAttribute("aria-checked")).toBe("false");
    fireEvent.click(sw);
    expect(onPickCoworker).toHaveBeenCalledWith("production-planning");
  });

  it("with nothing remembered, switching on picks the first specialist offered", () => {
    const { onPickCoworker } = renderRow("cowork");
    fireEvent.click(screen.getByTestId("coworker-chip"));
    fireEvent.click(screen.getByRole("switch", { name: "Use a specialist coworker" }));
    expect(onPickCoworker).toHaveBeenCalledWith("production-planning");
  });

  it("brings back a library expert (enabled but never in the picker) after switching off", () => {
    // "开会话" on a library expert enables it unsurfaced; only the switch remembers it.
    localStorage.setItem("openworker.lastSpecialistCoworker", "geographer");
    const expert = persona("geographer", "地理学家", { surfaced: false, builtin: false });
    const { onPickCoworker } = renderRow("cowork", { personas: [PERSONAS[0], expert] });
    fireEvent.click(screen.getByTestId("coworker-chip"));
    // Listed (so the person sees what "on" means), and the switch targets it.
    expect(screen.getByTestId("coworker-row-geographer")).toBeTruthy();
    fireEvent.click(screen.getByRole("switch", { name: "Use a specialist coworker" }));
    expect(onPickCoworker).toHaveBeenCalledWith("geographer");
  });

  it("hides the switch when the general coworker is the only one enabled", () => {
    renderRow("cowork", { personas: [PERSONAS[0]] });
    fireEvent.click(screen.getByTestId("coworker-chip"));
    expect(screen.queryByTestId("coworker-switch-row")).toBeNull();
  });

  it("every row's View opens the glance for that coworker, without picking it", () => {
    const { onPickCoworker, onPeek } = renderRow("cowork");
    fireEvent.click(screen.getByTestId("coworker-chip"));
    fireEvent.click(screen.getByTestId("coworker-peek-production-planning"));
    expect(onPeek).toHaveBeenCalledWith("production-planning");
    expect(onPickCoworker).not.toHaveBeenCalled();
  });

  it("the row itself still picks the coworker", () => {
    const { onPickCoworker } = renderRow("cowork");
    fireEvent.click(screen.getByTestId("coworker-chip"));
    fireEvent.click(screen.getByRole("button", { name: /Ops Coworker/ }));
    expect(onPickCoworker).toHaveBeenCalledWith("ops");
  });
});
