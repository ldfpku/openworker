import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { LibraryView, resetLibraryBrowseMemory } from "./LibraryView";
import i18n from "../i18n";

// UI chrome asserts on the English literal (the i18next key itself — see setupTests.ts: jsdom
// defaults to en-US and the zh-CN catalog isn't loaded here), while names/descriptions/category
// labels come straight from the mocked API data, exactly as the real library pack would return.
// categoryName renders twice on screen (the filter chip AND the card label) by design, so those
// assertions scope into a specific card via its data-testid rather than a bare getByText.
const EXPERTS_ZH = [
  {
    id: "academic/academic-geographer",
    category: "academic",
    categoryName: "学术研究",
    name: "地理学家",
    description: "分析空间数据、地图与区域发展模式。",
    emoji: "🌍",
    color: "blue",
    pair: true,
  },
  {
    id: "writing/copywriter",
    category: "writing",
    categoryName: "写作",
    name: "文案撰稿人",
    description: "撰写有说服力的营销文案与广告语。",
    emoji: "✍️",
    color: "#e07a5f",
    pair: false,
  },
];

const SKILLS = [
  {
    name: "scanpy",
    description: "Single-cell analysis toolkit for Python.",
    category: "packages",
    categoryName: "科学软件包",
    scripts: 15,
    references: 5,
    assets: 4,
    files: 25,
    compatibility: "Python 3.9+",
    license: "BSD-3-Clause license",
  },
];

// The consent record install-expert hands back (same shape as POST /v1/personas/install's
// `consent` array) for the geographer — used by every install→consent→enable test below.
const CONSENT_GEOGRAPHER = {
  id: "academic-geographer",
  name: "地理学家",
  description: "分析空间数据、地图与区域发展模式。",
  tools: ["read_file", "write_file"],
  risk: ["read", "write_local"],
  connectors: [] as string[],
  mcp: [] as string[],
  messaging: false,
  recommended_mode: "auto",
  recommended_models: [] as string[],
  source: "library-staged/zh/academic/academic-geographer",
  builtin: false,
};

vi.mock("../api", () => ({
  libraryOverview: vi.fn(async () => ({ ok: true, version: 1, experts: { zh: 2, en: 2 }, skills: 1 })),
  libraryExperts: vi.fn(async () => EXPERTS_ZH),
  libraryExpertPrompt: vi.fn(async (lib: string, id: string) => ({
    name: id === "academic/academic-geographer" ? (lib === "zh" ? "地理学家" : "Geographer") : "文案撰稿人",
    prompt: `prompt for ${id} (${lib})`,
  })),
  librarySkills: vi.fn(async () => SKILLS),
  librarySkillDetail: vi.fn(async (name: string) => ({
    name,
    description: "Single-cell analysis toolkit for Python.",
    skill_md: `# ${name}\n\nfull instructions here`,
    files: ["scripts/preprocess.py", "references/notes.md"],
  })),
  libraryStatus: vi.fn(async () => ({ experts: {}, skills: [] })),
  libraryInstallExpert: vi.fn(async () => ({
    ok: true,
    persona_id: "academic-geographer",
    consent: [CONSENT_GEOGRAPHER],
  })),
  libraryActivateExpert: vi.fn(async () => ({ ok: true, enabled: true })),
  libraryInstallSkills: vi.fn(async (names: string[]) => ({
    ok: true,
    results: names.map((name) => ({ name, ok: true })),
  })),
  // P4: the local layer + the installed-skill editing the skill page reaches into.
  librarySaveExpert: vi.fn(async (body: { id?: string; name: string }) => ({
    ok: true,
    id: body.id || "local/new-expert",
    created: !body.id,
    reinstalled: body.id === "academic/academic-geographer" ? ["academic-geographer"] : [],
  })),
  libraryDeleteExpert: vi.fn(async (_lib: string, id: string) => ({
    ok: true,
    deleted: id.startsWith("local/"),
    restored: !id.startsWith("local/"),
    reinstalled: [],
  })),
  listSkills: vi.fn(async () => [
    {
      name: "scanpy",
      description: "Single-cell analysis toolkit for Python.",
      instructions: "# scanpy\n\nfull instructions here",
      scope: "global",
      source: "local",
      enabled: true,
      path: "/state/skills/scanpy",
      files: 24,
    },
  ]),
  updateSkill: vi.fn(async () => ({ ok: true })),
  revealSkill: vi.fn(async () => ({ ok: true })),
}));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  resetLibraryBrowseMemory(); // the page remembers tab/search across mounts by design
});

describe("LibraryView — experts tab", () => {
  it("renders expert cards from the zh library by default", async () => {
    render(<LibraryView onStartExpertSession={vi.fn()} onStartTeamSession={vi.fn()} />);
    expect(await screen.findByText("地理学家")).toBeTruthy();
    expect(screen.getByText("文案撰稿人")).toBeTruthy();
    const geoCard = screen.getByTestId("expert-card-academic/academic-geographer");
    expect(within(geoCard).getByText("学术研究")).toBeTruthy();
  });

  it("search filters by name / description / category, case-insensitively", async () => {
    render(<LibraryView onStartExpertSession={vi.fn()} onStartTeamSession={vi.fn()} />);
    await screen.findByText("地理学家");

    fireEvent.change(screen.getByTestId("library-search"), { target: { value: "营销" } });
    expect(screen.queryByText("地理学家")).toBeNull();
    expect(screen.getByText("文案撰稿人")).toBeTruthy();

    fireEvent.change(screen.getByTestId("library-search"), { target: { value: "" } });
    expect(screen.getByText("地理学家")).toBeTruthy();
  });

  it("category chips filter the visible cards", async () => {
    render(<LibraryView onStartExpertSession={vi.fn()} onStartTeamSession={vi.fn()} />);
    await screen.findByText("地理学家");

    // categoryName repeats as both the chip label and a card's own label, so scope into the
    // chip row (its own testid) rather than a bare, ambiguous getByText.
    const chips = screen.getByTestId("library-category-chips");
    fireEvent.click(within(chips).getByText("写作"));
    expect(screen.queryByText("地理学家")).toBeNull();
    expect(screen.getByText("文案撰稿人")).toBeTruthy();

    fireEvent.click(within(chips).getByText("All"));
    expect(screen.getByText("地理学家")).toBeTruthy();
    expect(screen.getByText("文案撰稿人")).toBeTruthy();
  });

  it("opens the prompt detail modal and copies its content", async () => {
    const writeText = vi.fn(async () => {});
    Object.assign(navigator, { clipboard: { writeText } });

    render(<LibraryView onStartExpertSession={vi.fn()} onStartTeamSession={vi.fn()} />);
    await screen.findByText("地理学家");

    fireEvent.click(screen.getAllByText("View prompt")[0]);
    expect(await screen.findByTestId("library-detail-modal")).toBeTruthy();
    await screen.findByText("prompt for academic/academic-geographer (zh)");

    fireEvent.click(screen.getByText("Copy"));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith("prompt for academic/academic-geographer (zh)"));
  });
});

describe("LibraryView — install an expert as a coworker", () => {
  it("installs, opens the consent modal, enables, and starts a session on 'Start session'", async () => {
    const onStartExpertSession = vi.fn();
    const { libraryInstallExpert, libraryActivateExpert } = await import("../api");

    render(<LibraryView onStartExpertSession={onStartExpertSession} onStartTeamSession={vi.fn()} />);
    await screen.findByText("地理学家");

    const geoCard = screen.getByTestId("expert-card-academic/academic-geographer");
    fireEvent.click(within(geoCard).getByTestId("expert-start-academic/academic-geographer"));

    await waitFor(() =>
      expect(libraryInstallExpert).toHaveBeenCalledWith("zh", "academic/academic-geographer"),
    );

    const modal = await screen.findByTestId("library-consent-modal");
    expect(within(modal).getByText("地理学家")).toBeTruthy();
    expect(within(modal).getByText("Exact tools (2)")).toBeTruthy();

    fireEvent.click(within(modal).getByTestId("library-consent-confirm"));
    await waitFor(() => expect(libraryActivateExpert).toHaveBeenCalledWith("academic-geographer"));
    await waitFor(() => expect(onStartExpertSession).toHaveBeenCalledWith("academic-geographer"));
    expect(screen.queryByTestId("library-consent-modal")).toBeNull();
  });

  it("shows the enable failure inline and lets the user cancel out", async () => {
    const { libraryActivateExpert } = await import("../api");
    vi.mocked(libraryActivateExpert).mockResolvedValueOnce({ ok: false, error: "too many personas" });

    render(<LibraryView onStartExpertSession={vi.fn()} onStartTeamSession={vi.fn()} />);
    await screen.findByText("地理学家");
    fireEvent.click(
      within(screen.getByTestId("expert-card-academic/academic-geographer")).getByTestId(
        "expert-start-academic/academic-geographer",
      ),
    );
    const modal = await screen.findByTestId("library-consent-modal");
    fireEvent.click(within(modal).getByTestId("library-consent-confirm"));
    expect(await within(modal).findByText("too many personas")).toBeTruthy();

    fireEvent.click(within(modal).getByTestId("library-consent-cancel"));
    expect(screen.queryByTestId("library-consent-modal")).toBeNull();
  });

  it("starts a session directly, with no install call or modal, once already enabled", async () => {
    const { libraryStatus, libraryInstallExpert } = await import("../api");
    vi.mocked(libraryStatus).mockResolvedValueOnce({
      experts: {
        "zh:academic/academic-geographer": { solo: { persona_id: "academic-geographer", enabled: true } },
      },
      skills: [],
    });
    const onStartExpertSession = vi.fn();

    render(<LibraryView onStartExpertSession={onStartExpertSession} onStartTeamSession={vi.fn()} />);
    const geoCard = await screen.findByTestId("expert-card-academic/academic-geographer");
    await within(geoCard).findByText("Installed"); // status has landed

    fireEvent.click(within(geoCard).getByTestId("expert-start-academic/academic-geographer"));

    expect(onStartExpertSession).toHaveBeenCalledWith("academic-geographer");
    expect(libraryInstallExpert).not.toHaveBeenCalled();
    expect(screen.queryByTestId("library-consent-modal")).toBeNull();
  });

  it("installs a coworker from the detail modal without starting a session", async () => {
    const onStartExpertSession = vi.fn();
    const { libraryActivateExpert, libraryStatus } = await import("../api");
    vi.mocked(libraryStatus)
      .mockResolvedValueOnce({ experts: {}, skills: [] }) // initial mount
      .mockResolvedValueOnce({
        experts: {
          "zh:academic/academic-geographer": { solo: { persona_id: "academic-geographer", enabled: true } },
        },
        skills: [],
      }); // post-enable refresh

    render(<LibraryView onStartExpertSession={onStartExpertSession} onStartTeamSession={vi.fn()} />);
    await screen.findByText("地理学家");
    fireEvent.click(screen.getAllByText("View prompt")[0]);
    await screen.findByTestId("library-detail-modal");

    fireEvent.click(await screen.findByTestId("expert-install-as-coworker"));
    const modal = await screen.findByTestId("library-consent-modal");
    fireEvent.click(within(modal).getByTestId("library-consent-confirm"));

    await waitFor(() => expect(libraryActivateExpert).toHaveBeenCalledWith("academic-geographer"));
    expect(await screen.findByTestId("expert-installed-badge")).toBeTruthy();
    expect(onStartExpertSession).not.toHaveBeenCalled();
  });
});

describe("LibraryView — tab switching", () => {
  it("switches to the skills tab and renders skill cards", async () => {
    render(<LibraryView onStartExpertSession={vi.fn()} onStartTeamSession={vi.fn()} />);
    await screen.findByText("地理学家");

    fireEvent.click(screen.getByTestId("library-tab-skills"));
    const card = await screen.findByTestId("skill-card-scanpy");
    expect(within(card).getByText("scanpy")).toBeTruthy();
    expect(within(card).getByText("科学软件包")).toBeTruthy();
    expect(within(card).getByText("15 scripts")).toBeTruthy();
    expect(screen.queryByText("地理学家")).toBeNull();

    fireEvent.click(screen.getByTestId("library-tab-experts"));
    expect(await screen.findByText("地理学家")).toBeTruthy();
  });

  it("opens the skill detail modal listing bundled files", async () => {
    render(<LibraryView onStartExpertSession={vi.fn()} onStartTeamSession={vi.fn()} />);
    await screen.findByText("地理学家");
    fireEvent.click(screen.getByTestId("library-tab-skills"));
    await screen.findByTestId("skill-card-scanpy");

    fireEvent.click(screen.getByText("View description"));
    expect(await screen.findByTestId("library-detail-modal")).toBeTruthy();
    await screen.findByText(/full instructions here/);
    expect(screen.getByText("scripts/preprocess.py")).toBeTruthy();
  });
});

describe("LibraryView — install a skill", () => {
  it("shows the scripts/compatibility disclosure, installs, and flips to Installed", async () => {
    const { libraryStatus, libraryInstallSkills } = await import("../api");
    vi.mocked(libraryStatus)
      .mockResolvedValueOnce({ experts: {}, skills: [] }) // initial mount
      .mockResolvedValueOnce({ experts: {}, skills: ["scanpy"] }); // post-install refresh

    render(<LibraryView onStartExpertSession={vi.fn()} onStartTeamSession={vi.fn()} />);
    await screen.findByText("地理学家");
    fireEvent.click(screen.getByTestId("library-tab-skills"));
    await screen.findByTestId("skill-card-scanpy");

    fireEvent.click(screen.getByText("View description"));
    await screen.findByTestId("library-detail-modal");

    fireEvent.click(screen.getByTestId("skill-install-open"));
    const confirmBlock = await screen.findByTestId("skill-install-confirm");
    expect(within(confirmBlock).getByText(/Contains 15 executable scripts/)).toBeTruthy();
    expect(within(confirmBlock).getByText("Python 3.9+")).toBeTruthy();

    fireEvent.click(screen.getByTestId("skill-install-confirm-btn"));
    await waitFor(() => expect(libraryInstallSkills).toHaveBeenCalledWith(["scanpy"]));
    expect(await screen.findByTestId("skill-installed-badge")).toBeTruthy();
  });
});

describe("LibraryView — skills zh translation layer", () => {
  // 中文界面优先展示译文层（description_zh / skill_md_zh），英文界面或缺译文时回退英文。
  // 注意：切到 zh 后 UI 文案本身也会走 zh 词表（"查看说明" 等），选择器按中文取。
  afterEach(async () => {
    await i18n.changeLanguage("en");
  });

  it("prefers the zh description and zh doc under a zh UI", async () => {
    await i18n.changeLanguage("zh");
    const { librarySkills, librarySkillDetail } = await import("../api");
    vi.mocked(librarySkills).mockResolvedValueOnce([
      { ...SKILLS[0], description_zh: "Python 单细胞分析工具包。" },
    ]);
    vi.mocked(librarySkillDetail).mockResolvedValueOnce({
      name: "scanpy",
      description: "Single-cell analysis toolkit for Python.",
      description_zh: "Python 单细胞分析工具包。",
      skill_md: "# scanpy\n\nfull instructions here",
      skill_md_zh: "# scanpy\n\n中文全套说明在此",
      files: [],
    });

    render(<LibraryView onStartExpertSession={vi.fn()} onStartTeamSession={vi.fn()} />);
    await screen.findByText("地理学家");
    fireEvent.click(screen.getByTestId("library-tab-skills"));
    const card = await screen.findByTestId("skill-card-scanpy");
    expect(within(card).getByText("Python 单细胞分析工具包。")).toBeTruthy();

    fireEvent.click(within(card).getByText("查看说明"));
    await screen.findByTestId("library-detail-modal");
    expect(await screen.findByText(/中文全套说明在此/)).toBeTruthy();
    expect(screen.queryByText(/full instructions here/)).toBeNull();
  });

  it("keeps the English original under an English UI even when zh data exists", async () => {
    const { librarySkills } = await import("../api");
    vi.mocked(librarySkills).mockResolvedValueOnce([
      { ...SKILLS[0], description_zh: "Python 单细胞分析工具包。" },
    ]);

    render(<LibraryView onStartExpertSession={vi.fn()} onStartTeamSession={vi.fn()} />);
    await screen.findByText("地理学家");
    fireEvent.click(screen.getByTestId("library-tab-skills"));
    const card = await screen.findByTestId("skill-card-scanpy");
    expect(within(card).getByText("Single-cell analysis toolkit for Python.")).toBeTruthy();
    expect(within(card).queryByText("Python 单细胞分析工具包。")).toBeNull();
  });
});

describe("LibraryView — load failure vs pack missing", () => {
  it("offers a retry (not the dev pack-missing notice) when experts come back empty, and recovers", async () => {
    const { libraryExperts } = await import("../api");
    // One transient empty result — the race/fetch-failure shape the desktop app hit.
    vi.mocked(libraryExperts).mockResolvedValueOnce([]);

    render(<LibraryView onStartExpertSession={vi.fn()} onStartTeamSession={vi.fn()} />);

    expect(await screen.findByText("Could not load the expert library.")).toBeTruthy();
    expect(screen.queryByText(/gen_library/)).toBeNull();

    fireEvent.click(screen.getByTestId("library-retry"));
    expect(await screen.findByText("地理学家")).toBeTruthy();
    expect(screen.queryByTestId("library-retry")).toBeNull();
  });

  it("shows the pack-missing notice on the backend's explicit verdict, still with a retry", async () => {
    const { libraryOverview, libraryExperts, librarySkills } = await import("../api");
    vi.mocked(libraryOverview).mockResolvedValueOnce({
      ok: false,
      version: 1,
      experts: { zh: 0, en: 0 },
      skills: 0,
    });
    vi.mocked(libraryExperts).mockResolvedValueOnce([]);
    vi.mocked(librarySkills).mockResolvedValueOnce([]);

    render(<LibraryView onStartExpertSession={vi.fn()} onStartTeamSession={vi.fn()} />);

    // The dev-facing notice — and, since the backend re-checks the pack per request
    // (a one-off read failure yields the same verdict), a way back out of it.
    expect(await screen.findByText(/gen_library/)).toBeTruthy();
    fireEvent.click(screen.getByTestId("library-retry"));
    expect(await screen.findByText("地理学家")).toBeTruthy();
    expect(screen.queryByText(/gen_library/)).toBeNull();
  });
});

describe("LibraryView — build an expert team", () => {
  it("selects two experts, installs their teammate variants, and starts a team session", async () => {
    const onStartTeamSession = vi.fn();
    const { libraryInstallExpert, libraryActivateExpert } = await import("../api");
    // Install order follows selection order (geographer clicked first, then copywriter) —
    // two distinct one-time results stand in for the two experts' own teammate personas.
    vi.mocked(libraryInstallExpert)
      .mockResolvedValueOnce({
        ok: true,
        persona_id: "academic-geographer-worker",
        consent: [CONSENT_GEOGRAPHER],
      })
      .mockResolvedValueOnce({
        ok: true,
        persona_id: "copywriter-worker",
        consent: [{ ...CONSENT_GEOGRAPHER, id: "copywriter", name: "文案撰稿人" }],
      });

    render(<LibraryView onStartExpertSession={vi.fn()} onStartTeamSession={onStartTeamSession} />);
    await screen.findByText("地理学家");

    fireEvent.click(screen.getByTestId("library-team-toggle"));
    fireEvent.click(screen.getByTestId("expert-team-check-academic/academic-geographer"));
    fireEvent.click(screen.getByTestId("expert-team-check-writing/copywriter"));

    const bar = await screen.findByTestId("library-team-bar");
    expect(within(bar).getByText("2 experts selected")).toBeTruthy();

    fireEvent.click(screen.getByTestId("library-team-build"));
    const modal = await screen.findByTestId("library-team-modal");

    fireEvent.change(within(modal).getByTestId("library-team-goal"), {
      target: { value: "Ship a launch plan" },
    });
    fireEvent.click(within(modal).getByTestId("library-team-install"));

    await waitFor(() =>
      expect(libraryInstallExpert).toHaveBeenNthCalledWith(1, "zh", "academic/academic-geographer", true),
    );
    await waitFor(() =>
      expect(libraryInstallExpert).toHaveBeenNthCalledWith(2, "zh", "writing/copywriter", true),
    );
    expect(libraryInstallExpert).toHaveBeenCalledTimes(2);

    fireEvent.click(await within(modal).findByTestId("library-team-confirm"));

    await waitFor(() => expect(libraryActivateExpert).toHaveBeenCalledTimes(2));
    expect(libraryActivateExpert).toHaveBeenCalledWith("academic-geographer-worker");
    expect(libraryActivateExpert).toHaveBeenCalledWith("copywriter-worker");

    await waitFor(() =>
      expect(onStartTeamSession).toHaveBeenCalledWith("Ship a launch plan", "地理学家, 文案撰稿人"),
    );
    expect(screen.queryByTestId("library-team-modal")).toBeNull();
    // Completing clears multi-select mode — the pill is back to its off state.
    expect(screen.queryByTestId("library-team-bar")).toBeNull();
  });

  it("stops in the modal on an install failure, with completed rows still marked done", async () => {
    const { libraryInstallExpert, libraryActivateExpert } = await import("../api");
    vi.mocked(libraryInstallExpert)
      .mockResolvedValueOnce({
        ok: true,
        persona_id: "academic-geographer-worker",
        consent: [CONSENT_GEOGRAPHER],
      })
      .mockResolvedValueOnce({ ok: false, error: "disk full" });

    render(<LibraryView onStartExpertSession={vi.fn()} onStartTeamSession={vi.fn()} />);
    await screen.findByText("地理学家");

    fireEvent.click(screen.getByTestId("library-team-toggle"));
    fireEvent.click(screen.getByTestId("expert-team-check-academic/academic-geographer"));
    fireEvent.click(screen.getByTestId("expert-team-check-writing/copywriter"));
    fireEvent.click(screen.getByTestId("library-team-build"));
    const modal = await screen.findByTestId("library-team-modal");

    fireEvent.change(within(modal).getByTestId("library-team-goal"), {
      target: { value: "Ship a launch plan" },
    });
    fireEvent.click(within(modal).getByTestId("library-team-install"));

    expect(await within(modal).findByText("disk full")).toBeTruthy();
    expect(within(modal).getByTestId("library-team-retry")).toBeTruthy();
    // Stayed open — no activation attempted, no confirm step reached.
    expect(screen.getByTestId("library-team-modal")).toBeTruthy();
    expect(libraryActivateExpert).not.toHaveBeenCalled();
  });

  it("makes the team checkbox findable — the unchecked box is a real control", async () => {
    // Owner-hit 2026-08-31: unchecked was a 1px `--line` hairline with NO fill on a
    // near-white card, so across 276 cards the one control that says "you may pick this"
    // read as a rendering artifact. The user had to circle two of them in a screenshot
    // to point at what they meant.
    render(<LibraryView onStartExpertSession={vi.fn()} onStartTeamSession={vi.fn()} />);
    await screen.findByText("地理学家");

    const cardId = "expert-card-academic/academic-geographer";
    const boxId = "expert-team-check-academic/academic-geographer";
    expect(screen.queryByTestId(boxId)).toBeNull(); // no box until team mode

    fireEvent.click(screen.getByTestId("library-team-toggle"));
    const card = screen.getByTestId(cardId);
    const box = screen.getByTestId(boxId);

    // The CARD is the control — it is where the click lands, so the role and the state
    // live there and the little box stays decorative.
    expect(card.getAttribute("role")).toBe("checkbox");
    expect(card.getAttribute("aria-checked")).toBe("false");
    expect(card.getAttribute("tabindex")).toBe("0");

    // Unchecked must still LOOK like a checkbox: a 2px strong border over a filled
    // ground, never a hairline on nothing.
    expect(box.className).toContain("border-2");
    expect(box.className).toContain("border-lineStrong");
    expect(box.className).toContain("bg-paper");
    expect(box.className).not.toContain("border-line ");

    // Keyboard reaches it too — Space toggles, like any checkbox.
    fireEvent.keyDown(card, { key: " " });
    expect(screen.getByTestId(cardId).getAttribute("aria-checked")).toBe("true");
    expect(screen.getByTestId(boxId).className).toContain("bg-accent");

    fireEvent.keyDown(screen.getByTestId(cardId), { key: "Enter" });
    expect(screen.getByTestId(cardId).getAttribute("aria-checked")).toBe("false");
  });
});

// P4 (owner ask 2026-09-10): the library is editable on this machine — new experts,
// in-place edits of pack experts (overrides), restore/delete — and an installed skill's
// local copy can be edited from its page.
describe("LibraryView — editing on this machine", () => {
  it("New expert: fills the editor, saves, and the list refreshes with the local card", async () => {
    const { librarySaveExpert, libraryExperts } = await import("../api");
    vi.mocked(libraryExperts)
      .mockResolvedValueOnce(EXPERTS_ZH)
      .mockResolvedValueOnce([
        ...EXPERTS_ZH,
        {
          id: "local/new-expert",
          category: "academic",
          categoryName: "学术研究",
          name: "排产专家",
          description: "为交期负责",
          emoji: "📅",
          color: "#888",
          pair: false,
          local: true,
          modified: false,
        },
      ]);

    render(<LibraryView onStartExpertSession={vi.fn()} onStartTeamSession={vi.fn()} />);
    await screen.findByText("地理学家");
    fireEvent.click(screen.getByTestId("library-new-expert"));
    const modal = await screen.findByTestId("library-editor-modal");
    expect(within(modal).getByText("New expert")).toBeTruthy();

    // Save is armed only once a name and a prompt are in.
    const save = within(modal).getByTestId("expert-editor-save") as HTMLButtonElement;
    expect(save.disabled).toBe(true);
    fireEvent.change(within(modal).getByTestId("expert-editor-name"), { target: { value: "排产专家" } });
    fireEvent.change(within(modal).getByTestId("expert-editor-emoji"), { target: { value: "📅" } });
    fireEvent.change(within(modal).getByTestId("expert-editor-desc"), { target: { value: "为交期负责" } });
    fireEvent.change(within(modal).getByTestId("expert-editor-prompt"), { target: { value: "你是排产专家。" } });
    expect(save.disabled).toBe(false);
    fireEvent.click(save);

    await waitFor(() =>
      expect(librarySaveExpert).toHaveBeenCalledWith(
        expect.objectContaining({
          lib: "zh",
          id: undefined,
          name: "排产专家",
          emoji: "📅",
          description: "为交期负责",
          category: "academic",
          categoryName: "学术研究",
          prompt: "你是排产专家。",
        }),
      ),
    );
    await waitFor(() => expect(screen.queryByTestId("library-editor-modal")).toBeNull());
    expect(await screen.findByTestId("expert-card-local/new-expert")).toBeTruthy();
    expect(screen.getByTestId("expert-local-chip-local/new-expert")).toBeTruthy();
    expect(screen.getByTestId("library-notice").textContent).toContain("Expert saved on this machine.");
  });

  it("Edit prompt on a pack expert: loads its text, saves an override, reports the re-install", async () => {
    const { librarySaveExpert, libraryExpertPrompt } = await import("../api");
    vi.mocked(libraryExpertPrompt).mockResolvedValue({
      name: "地理学家",
      prompt: "shipped prompt",
      local: false,
      modified: false,
      pack_prompt: "shipped prompt",
      meta: { name: "地理学家", description: "分析空间数据", emoji: "🌍", color: "blue", category: "academic", categoryName: "学术研究" },
    });

    render(<LibraryView onStartExpertSession={vi.fn()} onStartTeamSession={vi.fn()} />);
    await screen.findByText("地理学家");
    fireEvent.click(screen.getByTestId("expert-edit-academic/academic-geographer"));
    const modal = await screen.findByTestId("library-editor-modal");
    const prompt = (await within(modal).findByTestId("expert-editor-prompt")) as HTMLTextAreaElement;
    expect(prompt.value).toBe("shipped prompt");
    // The category is the pack's — shown, not editable.
    expect(within(modal).queryByTestId("expert-editor-category")).toBeNull();
    expect(within(modal).getByText("学术研究")).toBeTruthy();

    fireEvent.change(prompt, { target: { value: "my better prompt" } });
    // Reset link appears once the text differs from the shipped one; leave it edited.
    expect(within(modal).getByTestId("expert-editor-reset-text")).toBeTruthy();
    fireEvent.click(within(modal).getByTestId("expert-editor-save"));

    await waitFor(() =>
      expect(librarySaveExpert).toHaveBeenCalledWith(
        expect.objectContaining({
          lib: "zh",
          id: "academic/academic-geographer",
          name: "地理学家",
          category: "academic",
          prompt: "my better prompt",
        }),
      ),
    );
    await waitFor(() => expect(screen.queryByTestId("library-editor-modal")).toBeNull());
    expect(screen.getByTestId("library-notice").textContent).toContain("installed coworker");
  });

  it("the detail modal offers Restore original for an edited expert and Delete for a local one", async () => {
    const { libraryDeleteExpert, libraryExpertPrompt } = await import("../api");
    vi.mocked(libraryExpertPrompt).mockImplementation(async (_lib: string, id: string) =>
      id === "academic/academic-geographer"
        ? { name: "地理学家", prompt: "edited", modified: true, local: false, pack_prompt: "shipped" }
        : { name: "文案撰稿人", prompt: "p", modified: false, local: true },
    );
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);

    render(<LibraryView onStartExpertSession={vi.fn()} onStartTeamSession={vi.fn()} />);
    await screen.findByText("地理学家");
    const geoCard = screen.getByTestId("expert-card-academic/academic-geographer");
    fireEvent.click(within(geoCard).getByText("View prompt"));
    const modal = await screen.findByTestId("library-detail-modal");
    expect(await within(modal).findByTestId("expert-source-note")).toBeTruthy();
    expect(within(modal).queryByTestId("expert-delete")).toBeNull();
    fireEvent.click(within(modal).getByTestId("expert-restore"));
    await waitFor(() => expect(libraryDeleteExpert).toHaveBeenCalledWith("zh", "academic/academic-geographer"));
    await waitFor(() => expect(screen.queryByTestId("library-detail-modal")).toBeNull());
    expect(screen.getByTestId("library-notice").textContent).toContain("Original restored");

    const copyCard = screen.getByTestId("expert-card-writing/copywriter");
    fireEvent.click(within(copyCard).getByText("View prompt"));
    const modal2 = await screen.findByTestId("library-detail-modal");
    expect(within(modal2).queryByTestId("expert-restore")).toBeNull();
    fireEvent.click(await within(modal2).findByTestId("expert-delete"));
    await waitFor(() => expect(libraryDeleteExpert).toHaveBeenCalledWith("zh", "writing/copywriter"));
    confirmSpy.mockRestore();
  });

  it("an installed skill's page edits the local copy and can put the original back", async () => {
    const { libraryStatus, updateSkill, libraryInstallSkills } = await import("../api");
    vi.mocked(libraryStatus).mockResolvedValue({ experts: {}, skills: ["scanpy"] });
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);

    render(<LibraryView onStartExpertSession={vi.fn()} onStartTeamSession={vi.fn()} />);
    await screen.findByText("地理学家");
    fireEvent.click(screen.getByTestId("library-tab-skills"));
    await screen.findByTestId("skill-card-scanpy");
    fireEvent.click(screen.getByText("View description"));
    const modal = await screen.findByTestId("library-detail-modal");

    const local = await within(modal).findByTestId("skill-local-copy");
    expect(await within(local).findByText("/state/skills/scanpy")).toBeTruthy();
    fireEvent.click(within(local).getByTestId("skill-local-edit"));
    const body = within(local).getByTestId("skill-local-instructions") as HTMLTextAreaElement;
    expect(body.value).toContain("full instructions here");
    fireEvent.change(body, { target: { value: "tuned instructions" } });
    fireEvent.click(within(local).getByTestId("skill-local-save"));
    await waitFor(() =>
      expect(updateSkill).toHaveBeenCalledWith("scanpy", {
        description: "Single-cell analysis toolkit for Python.",
        instructions: "tuned instructions",
      }),
    );
    expect(await screen.findByTestId("library-notice")).toBeTruthy();

    fireEvent.click(await within(local).findByTestId("skill-local-reinstall"));
    await waitFor(() => expect(libraryInstallSkills).toHaveBeenCalledWith(["scanpy"], true));
    confirmSpy.mockRestore();
  });
});

describe("LibraryView — audit 2026-09-10 hardening", () => {
  it("remembers tab, language, search and category across a remount", async () => {
    const { unmount } = render(<LibraryView onStartExpertSession={vi.fn()} onStartTeamSession={vi.fn()} />);
    await screen.findByText("地理学家");
    fireEvent.click(screen.getByTestId("library-tab-skills"));
    await screen.findByTestId("skill-card-scanpy");
    fireEvent.change(screen.getByTestId("library-search"), { target: { value: "scan" } });
    unmount();

    render(<LibraryView onStartExpertSession={vi.fn()} onStartTeamSession={vi.fn()} />);
    // Back on Skills, with the search still typed.
    expect(await screen.findByTestId("skill-card-scanpy")).toBeTruthy();
    expect((screen.getByTestId("library-search") as HTMLInputElement).value).toBe("scan");
    expect(screen.queryByTestId("library-expert-grid")).toBeNull();
  });

  it("an installed skill's page shows the local copy's text, not the shipped one", async () => {
    const { libraryStatus, listSkills } = await import("../api");
    vi.mocked(libraryStatus).mockResolvedValue({ experts: {}, skills: ["scanpy"] });
    vi.mocked(listSkills).mockResolvedValue([
      {
        name: "scanpy",
        description: "d",
        instructions: "# scanpy (edited locally)\n\ntuned instructions",
        scope: "global",
        source: "local",
        enabled: true,
        path: "/state/skills/scanpy",
      },
    ]);
    render(<LibraryView onStartExpertSession={vi.fn()} onStartTeamSession={vi.fn()} />);
    await screen.findByText("地理学家");
    fireEvent.click(screen.getByTestId("library-tab-skills"));
    await screen.findByTestId("skill-card-scanpy");
    fireEvent.click(screen.getByText("View description"));
    const modal = await screen.findByTestId("library-detail-modal");
    expect(await within(modal).findByTestId("skill-md-source")).toBeTruthy();
    expect(within(modal).getByTestId("skill-md").textContent).toContain("tuned instructions");
    expect(within(modal).getByTestId("skill-md").textContent).not.toContain("full instructions here");
  });

  it("a request that throws lands as an error, not a button stuck on busy", async () => {
    const { librarySaveExpert } = await import("../api");
    vi.mocked(librarySaveExpert).mockRejectedValueOnce(new Error("boom"));
    render(<LibraryView onStartExpertSession={vi.fn()} onStartTeamSession={vi.fn()} />);
    await screen.findByText("地理学家");
    fireEvent.click(screen.getByTestId("library-new-expert"));
    const modal = await screen.findByTestId("library-editor-modal");
    fireEvent.change(within(modal).getByTestId("expert-editor-name"), { target: { value: "x" } });
    fireEvent.change(within(modal).getByTestId("expert-editor-prompt"), { target: { value: "p" } });
    fireEvent.click(within(modal).getByTestId("expert-editor-save"));
    expect(await within(modal).findByTestId("expert-editor-error")).toBeTruthy();
    expect((within(modal).getByTestId("expert-editor-save") as HTMLButtonElement).disabled).toBe(false);
    // The typed prompt is still there.
    expect((within(modal).getByTestId("expert-editor-prompt") as HTMLTextAreaElement).value).toBe("p");
  });
});
