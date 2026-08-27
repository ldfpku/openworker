import { isComposing } from "../ime";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  getPersonasIndex,
  getSessions,
  installPersona,
  updatePersona,
  type Persona,
  type PersonaConsent,
} from "../api";
import { chooseFolder } from "../tauri";
import type { SessionInfo } from "../types";
import { Icon } from "./Icon";
import { Toggle } from "./Toggle";

// Personas management (UX-035): grouped General/Security lists with ONE toggle per row
// (enable implies picker); in-picker nuance, set-default, export and delete live on the
// per-coworker detail page. Unshipped coworkers (ships:false) and the installer are quiet
// text disclosures at the bottom; Folder/Zip install through native pickers.
const CARD = "rounded-xl2 border border-line bg-panel";
const SELECT = "px-2.5 py-2 rounded-lg border border-line bg-paper text-[13px] text-ink shrink-0";
const INPUT =
  "flex-1 min-w-0 px-3 py-2 rounded-lg border border-line bg-paper text-[13px] text-ink outline-none focus:border-accent";
const BTN_ACCENT = "text-[12.5px] px-3 py-2 rounded-lg bg-accent text-white shrink-0 disabled:opacity-40";
const BTN_BORDERED =
  "text-[12.5px] px-2.5 py-1.5 rounded-lg border border-line bg-paper hover:border-lineStrong shrink-0 disabled:opacity-40 disabled:hover:border-line";

const QUIET_ROW =
  "w-full flex items-center gap-2 px-4 pt-2 mt-6 text-[12.5px] text-muted select-none";

export function PersonasTab({ onOpenPersona }: { onOpenPersona?: (id: string) => void }) {
  const { t } = useTranslation();
  const [personas, setPersonas] = useState<Persona[]>([]);
  const [internal, setInternal] = useState(false);
  const [mode, setMode] = useState<"git" | "dir" | "zip">("git");
  const [src, setSrc] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [consent, setConsent] = useState<PersonaConsent[] | null>(null);
  const [showUnshipped, setShowUnshipped] = useState(false);
  const [showInstall, setShowInstall] = useState(false);
  // Disabling archives the persona's conversations (server-side), so when there are any we
  // arm an inline confirm (same two-step idiom as delete) instead of flipping immediately.
  const [confirmOff, setConfirmOff] = useState<string | null>(null);
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  // The picker's "Import coworker…" door lands here and asks us to put the Add section
  // front and center (sharing v1).
  const addRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const focus = () => {
      setShowInstall(true); // the installer is a collapsed disclosure — open it first
      setTimeout(
        () => addRef.current?.scrollIntoView({ behavior: "smooth", block: "center" }),
        0,
      );
    };
    window.addEventListener("ocw-focus-import", focus);
    return () => window.removeEventListener("ocw-focus-import", focus);
  }, []);

  const reload = () =>
    getPersonasIndex()
      .then((r) => {
        setPersonas(r.personas);
        setInternal(r.internal);
      })
      .catch(() => {});
  const reloadSessions = () => getSessions().then(setSessions).catch(() => {});
  useEffect(() => {
    reload();
    reloadSessions();
  }, []);

  // Real conversations the disable would archive (unarchived; run sessions are server-hidden).
  const liveCount = (id: string) =>
    sessions.filter((s) => s.agent === id && !s.archived).length;

  const toggle = async (
    id: string,
    body: { enabled?: boolean; surfaced?: boolean; default?: boolean },
  ) => {
    const r = await updatePersona(id, body);
    if (r.personas) setPersonas(r.personas);
    else reload();
    if (body.enabled === false) reloadSessions(); // counts just changed
  };

  const requestDisable = (p: Persona) => {
    if (liveCount(p.id) > 0) setConfirmOff(p.id);
    else toggle(p.id, { enabled: false });
  };

  const finishInstall = (r: Awaited<ReturnType<typeof installPersona>>) => {
    setBusy(false);
    if (!r.ok) {
      setMsg(r.error || t("install failed"));
      return;
    }
    setConsent(r.consent || []);
    if (r.personas) setPersonas(r.personas);
    setMsg(
      t("Installed {{count}} coworker(s) — review and enable below.", {
        count: (r.consent || []).length,
      }),
    );
    setSrc("");
  };

  // Folder installs go through the native picker — no path typing (owner, 2026-08-21).
  const installDir = async () => {
    const dir = await chooseFolder();
    if (!dir) return;
    setBusy(true);
    setMsg(null);
    setConsent(null);
    finishInstall(await installPersona({ dir }));
  };

  const installZip = async (file: File) => {
    setBusy(true);
    setMsg(null);
    setConsent(null);
    const buf = new Uint8Array(await file.arrayBuffer());
    let bin = "";
    for (let i = 0; i < buf.length; i += 0x8000)
      bin += String.fromCharCode(...buf.subarray(i, i + 0x8000));
    finishInstall(await installPersona({ zip_b64: btoa(bin), filename: file.name }));
  };

  const install = async () => {
    if (!src.trim()) return;
    setBusy(true);
    setMsg(null);
    setConsent(null);
    const r = await installPersona({ git_url: src.trim() });
    setBusy(false);
    if (!r.ok) {
      setMsg(r.error || t("install failed"));
      return;
    }
    setConsent(r.consent || []);
    if (r.personas) setPersonas(r.personas);
    setMsg(
      t("Installed {{count}} coworker(s) — review and enable below.", {
        count: (r.consent || []).length,
      }),
    );
    setSrc("");
  };

  const unshipped = personas.filter((p) => p.ships === false);

  const group = (title: string | null, list: Persona[]) => {
    if (list.length === 0) return null;
    return (
      <div className={title ? "mt-7" : "mt-1.5"}>
        {title && (
          <div className="text-[12px] font-semibold text-muted px-4 mb-1.5">{title}</div>
        )}
        <div className={CARD + " divide-y divide-line"}>
          {list.map((p) => (
            <div key={p.id} className="px-[18px] py-4">
              <div className="flex items-center gap-3">
                <div className="min-w-0 flex-1">
                  <div className="text-[14px] font-medium truncate">{t(p.name)}</div>
                  <div className="text-[12px] text-faint truncate mt-0.5">{p.tagline && t(p.tagline)}</div>
                </div>
                {p.default ? (
                  /* The default coworker cannot be disabled or hidden — no toggle, no
                     configure; a quiet tag says why (owner 2026-08-21). It regains its
                     controls the moment another coworker is made default. */
                  <span
                    className="text-[11px] font-medium px-2 py-0.5 rounded-full bg-paper border border-lineStrong text-muted shrink-0"
                    title={t("Default for new sessions")}
                    data-testid="persona-default-tag"
                  >
                    {t("Default")}
                  </span>
                ) : (
                  <>
                    <Toggle
                      checked={p.enabled}
                      onChange={(next) =>
                        next ? toggle(p.id, { enabled: true }) : requestDisable(p)
                      }
                      title={p.enabled ? t("Disable this coworker") : t("Enable this coworker")}
                    />
                    {onOpenPersona && (
                      <button
                        className="text-faint hover:text-ink shrink-0 p-1"
                        title={t("Configure {{name}}", { name: t(p.name) })}
                        aria-label={t("Configure {{name}}", { name: t(p.name) })}
                        data-testid={`persona-configure-${p.id}`}
                        onClick={() => onOpenPersona(p.id)}
                      >
                        <Icon name="sliders" size={15} />
                      </button>
                    )}
                  </>
                )}
              </div>
              {confirmOff === p.id && (
                <div
                  className="mt-2 flex items-center gap-2.5 text-[12px] text-muted"
                  data-testid={`persona-disable-warning-${p.id}`}
                >
                  <span className="min-w-0">
                    {liveCount(p.id) === 1
                      ? t(
                          "Disabling archives its 1 conversation — they stay available under “Show archived”.",
                        )
                      : t(
                          "Disabling archives its {{count}} conversations — they stay available under “Show archived”.",
                          { count: liveCount(p.id) },
                        )}
                  </span>
                  <button
                    className="text-[12px] px-2.5 py-1.5 rounded-lg bg-accent text-white shrink-0"
                    data-testid={`persona-disable-confirm-${p.id}`}
                    onClick={() => {
                      setConfirmOff(null);
                      toggle(p.id, { enabled: false });
                    }}
                  >
                    {t("Disable")}
                  </button>
                  <button className={BTN_BORDERED} onClick={() => setConfirmOff(null)}>
                    {t("Keep enabled")}
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    );
  };

  return (
    <div>
      {/* One toggle per row (enable implies picker); ★ marks the default. Everything
          else — in-picker nuance, default, export, delete — lives on the detail page. */}
      {group(t("General"), personas.filter((p) => p.ships !== false && p.group !== "security"))}
      {group(t("Security"), personas.filter((p) => p.ships !== false && p.group === "security"))}

      {unshipped.length > 0 && (
        <>
          <button
            className={QUIET_ROW}
            data-testid="unshipped-disclosure"
            onClick={() => setShowUnshipped((v) => !v)}
          >
            <Icon
              name="chevronRight"
              size={12}
              className={"transition-transform" + (showUnshipped ? " rotate-90" : "")}
            />
            <span>
              {t("Not in this release · {{count}} coworkers", { count: unshipped.length })}
            </span>
            <span className="ml-auto text-faint text-[12px]">
              {internal ? t("internal build") : t("not in this release")}
            </span>
          </button>
          {showUnshipped && group(null, unshipped)}
        </>
      )}

      <button
        ref={addRef as any}
        className={QUIET_ROW}
        data-testid="install-disclosure"
        onClick={() => setShowInstall((v) => !v)}
      >
        <Icon
          name="chevronRight"
          size={12}
          className={"transition-transform" + (showInstall ? " rotate-90" : "")}
        />
        <span>{t("Install a coworker")}</span>
        <span className="ml-auto text-faint text-[12px]">{t("GitHub · folder · .zip")}</span>
      </button>
      {showInstall && (
        <div className={CARD + " mt-1.5 p-4"}>
          <div className="flex items-center gap-2">
            <select
              className={SELECT}
              value={mode}
              onChange={(e) => setMode(e.target.value as "git" | "dir" | "zip")}
            >
              <option value="git">{t("GitHub URL")}</option>
              <option value="dir">{t("Local folder")}</option>
              <option value="zip">{t("Bundle zip")}</option>
            </select>
            {mode === "git" ? (
              <>
                <input
                  className={INPUT}
                  placeholder="https://github.com/acme/ops-coworker"
                  value={src}
                  onChange={(e) => setSrc(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && !isComposing(e) && install()}
                />
                <button className={BTN_ACCENT} disabled={busy || !src.trim()} onClick={install}>
                  {busy ? t("Installing…") : t("Install")}
                </button>
              </>
            ) : mode === "dir" ? (
              <>
                <button
                  className={BTN_BORDERED}
                  disabled={busy}
                  data-testid="persona-dir-choose"
                  onClick={() => void installDir()}
                >
                  {busy ? t("Installing…") : t("Choose folder…")}
                </button>
                <span className="text-[12px] text-faint">
                  {t("Opens the system folder picker; installs on selection.")}
                </span>
              </>
            ) : (
              <label className={BTN_BORDERED + " cursor-pointer"}>
                {busy ? t("Installing…") : t("Choose a .zip bundle…")}
                <input
                  type="file"
                  accept=".zip"
                  className="hidden"
                  data-testid="persona-zip-input"
                  disabled={busy}
                  onChange={(e) => {
                    const f = e.target.files?.[0];
                    if (f) void installZip(f);
                    e.target.value = "";
                  }}
                />
              </label>
            )}
          </div>
          <div className="flex items-start gap-2 mt-3 text-[12px] text-muted leading-relaxed">
            <span className="text-warnInk shrink-0">⚠</span>
            <span>
              {t(
                "Only install coworkers from sources you trust and can hold accountable — a coworker runs with access to your system. Files are snapshotted into a managed area; no third-party code runs, but the instructions steer the coworker. Best used by teams whose lead builds and distributes coworkers through official channels.",
              )}
            </span>
          </div>
        </div>
      )}
      {msg && <div className="text-[12.5px] text-muted mt-2.5">{msg}</div>}

      {consent && consent.length > 0 && (
        <div className="mt-4 space-y-2" data-testid="consent-review">
          {/* Trust first (owner design, 2026-08-11): the source warning leads; capabilities
              are a one-line summary with the exact tools under a collapsed chevron. A
              coworker runs no third-party code, so this list is complete — but a prompt
              still steers an agent, so who it came from genuinely matters. */}
          <div className="flex items-start gap-2.5 rounded-xl border border-warnInk/30 bg-warnSoft px-3.5 py-2.5 text-[12.5px] text-warnInk">
            <Icon name="shield" size={15} className="shrink-0 mt-0.5" />
            <span>
              {t(
                "Only enable coworkers from someone you trust. Nothing here runs third-party code — but its instructions will guide the coworker's behavior.",
              )}
            </span>
          </div>
          {consent.map((c) => (
            <ConsentCard
              key={c.id}
              c={c}
              enabled={personas.find((p) => p.id === c.id)?.enabled ?? false}
              onEnable={async () => {
                await toggle(c.id, { enabled: true, surfaced: true });
              }}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// One phrase per risk class — the plain-language capability summary the consent card leads
// with; unknown classes fall back to their raw id so nothing is silently omitted. Exported
// for LibraryView's compact expert-install consent modal, which mirrors this same wording.
export const RISK_PHRASE: Record<string, string> = {
  read: "read files",
  write_local: "create & edit files",
  exec: "run shell commands",
  network: "access the network",
  write_remote: "act on connected services",
};

function ConsentCard({
  c,
  enabled,
  onEnable,
}: {
  c: PersonaConsent;
  enabled: boolean;
  onEnable: () => Promise<void>;
}) {
  const { t } = useTranslation();
  const [showTools, setShowTools] = useState(false);
  const [busy, setBusy] = useState(false);
  const phrases = (c.risk.length ? c.risk : ["read"]).map((r) => t(RISK_PHRASE[r] || r));
  const summary = phrases.join(", ").replace(/, ([^,]*)$/, `${t(" and ")}$1`);
  const recommends = c.recommends || [];
  return (
    <div className={CARD + " p-3.5"} data-testid={`consent-${c.id}`}>
      <div className="text-[13.5px] font-medium flex items-center gap-2">
        <span>{c.name}</span>
        {c.version && <span className="text-[11px] text-faint font-normal">v{c.version}</span>}
      </div>
      {c.description && <div className="text-[12px] text-muted mt-0.5">{c.description}</div>}
      {c.replaces && (
        <div className="text-[12px] text-muted mt-1.5" data-testid="replaces-note">
          {t("Replaces {{name}}", { name: c.name })}
          {c.replaces.version ? ` v${c.replaces.version}` : ""}
          {c.replaces.installed_at
            ? ` (${t("installed {{date}}", { date: c.replaces.installed_at })})`
            : ""}
          {"."}{" "}
          {c.replaces.capabilities_grew
            ? t(
                "This update asks for MORE capabilities than the copy it replaces — review below before re-enabling.",
              )
            : t("Same capabilities as before — it stays enabled.")}
        </div>
      )}
      <div className="text-[12.5px] text-ink mt-2">
        {t("Can {{summary}}", { summary })}
        {c.connectors === "all"
          ? t(" · use ALL your connected services")
          : c.connectors.length
            ? t(" · use connectors: {{list}}", { list: c.connectors.join(", ") })
            : ""}
        {c.messaging ? t(" · send messages") : ""}
        {c.mcp.length ? t(" · use MCP: {{list}}", { list: c.mcp.join(", ") }) : ""}
        <button
          className="ml-2 text-accent text-[12px] hover:underline"
          data-testid="consent-tools-toggle"
          onClick={() => setShowTools((v) => !v)}
        >
          {showTools ? t("Hide tools") : t("Exact tools ({{count}})", { count: c.tools.length })}
        </button>
      </div>
      {showTools && (
        <div className="text-[12px] text-muted mt-1 font-mono">{c.tools.join(" · ") || "—"}</div>
      )}
      {recommends.length > 0 && (
        <div className="mt-2 space-y-0.5">
          {recommends.map((r) => (
            <div key={r.kind + r.ref} className="text-[12px] text-muted">
              <span className="text-ink">{r.ref}</span>{" "}
              {r.tier === "core" ? t("(recommended)") : t("(optional)")} — {r.reason}
            </div>
          ))}
        </div>
      )}
      <div className="flex items-center gap-3 mt-2.5">
        {/* Enable right here (owner ask 2026-08-11) — the old "enable it above" copy
            sent the user hunting back up the list. */}
        {enabled ? (
          <span className="text-[12.5px] text-muted" data-testid="consent-enabled">
            ✓ {t("Enabled — it's in your coworker picker.")}
          </span>
        ) : (
          <button
            className={BTN_ACCENT}
            data-testid={`consent-enable-${c.id}`}
            disabled={busy}
            onClick={() => {
              setBusy(true);
              void onEnable().finally(() => setBusy(false));
            }}
          >
            {busy ? t("Enabling…") : t("Enable this coworker")}
          </button>
        )}
        <span className="text-[12px] text-faint">
          {t("Recommended mode: {{mode}}.", { mode: c.recommended_mode })}
        </span>
      </div>
    </div>
  );
}
