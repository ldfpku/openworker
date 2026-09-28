import { useEffect, useState } from "react";
import { Trans, useTranslation } from "react-i18next";
import {
  createAutomation,
  deleteAutomation,
  getAutomation,
  getAutomations,
  getConnectors,
  getRecentChannels,
  markAutomationSeen,
  announceAutomationsChanged,
  updateAutomation,
  type Automation,
  type Connector,
  type RecentChannel,
  type AutomationRun,
} from "../api";
import { BackLink } from "./BackLink";
import { Icon } from "./Icon";
import { PanelHead } from "./IntegrationsView";
import { AutomationQuickstart } from "./AutomationQuickstart";
import { ChannelPicker } from "./SubscriptionsChip";
import { TaskFolderField } from "./TaskFolderField";
import { FREQ_OPTIONS, fromCron, toCron } from "../schedule";
import { IconButton } from "./IconButton";
import { BTN_ACCENT_SM, BTN_BORDERED, BTN_BORDERED_SM, BTN_DANGER_SM } from "./buttons";

// Shared utility strings (the §28 page shell — mirrors IntegrationsView's constants).
const CARD = "rounded-xl2 border border-line bg-panel";

const fmt = (t: number | null) =>
  t ? new Date(t * 1000).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }) : "—";

// Backend enums (coworker/automation/models.py TaskRun.status / .trigger) come across the wire
// as raw tokens — map each to a translated label rather than rendering it verbatim.
function runStatusLabel(t: (key: string) => string, status?: string | null): string {
  switch (status) {
    case "ok":
      return t("automations.status_ok");
    case "running":
      return t("automations.status_running");
    case "error":
      return t("automations.status_error");
    case "skipped":
      return t("automations.status_skipped");
    case "canceled":
      return t("automations.status_canceled");
    default:
      return status || "";
  }
}

function runTriggerLabel(t: (key: string) => string, trigger?: string | null): string {
  switch (trigger) {
    case "schedule":
      return t("schedule");
    case "catchup":
      return t("catchup");
    case "manual":
      return t("manual");
    default:
      return trigger || "";
  }
}

// The §28 page shell: full-bleed main, centered ≤4xl column — same as Connectors/Activity/Inbox.
function Shell({ children }: { children: React.ReactNode }) {
  return (
    <main className="flex-1 min-w-0 flex bg-paper">
      <div className="flex-1 min-w-0 overflow-y-auto hairline-scroll">
        <div className="max-w-4xl mx-auto px-7 py-6">{children}</div>
      </div>
    </main>
  );
}

interface Props {
  // `task` gives the opened run session its context (banner + "Back to runs"; owner ask 2026-07-04).
  onOpenRun: (
    sessionId: string,
    workspace: string,
    agent: string,
    task?: { id: string; title: string },
  ) => void;
  onRunNow: (taskId: string, title?: string) => void;
  // Open directly on a task's detail (set by the run banner's "Back to runs").
  initialOpenId?: string | null;
  // F4's "先在「连接器」里连接微信" → "去连接" button: hand off to the Connectors surface.
  onOpenIntegrations: () => void;
}

export function ScheduledView({ onOpenRun, onRunNow, initialOpenId, onOpenIntegrations }: Props) {
  const { t } = useTranslation();
  const [tasks, setTasks] = useState<Automation[]>([]);
  const [openId, setOpenId] = useState<string | null>(initialOpenId ?? null);
  const [showForm, setShowForm] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);

  // The sidebar's Scheduled band can retarget an ALREADY-open Automations surface —
  // initial state alone would ignore the change (UX-023).
  useEffect(() => {
    if (initialOpenId) setOpenId(initialOpenId);
  }, [initialOpenId]);

  const refresh = () => getAutomations().then(setTasks).catch(() => setTasks([]));
  useEffect(() => {
    refresh();
    const h = setInterval(refresh, 5000);
    return () => clearInterval(h);
  }, []);

  // Create from a payload, refresh the list, and open the new task's detail. `permissions`
  // rides through for quickstart recipes (§25 write grants).
  const create = async (payload: {
    title: string;
    instructions: string;
    cron?: string;
    workspace?: string;
    permissions?: { tool: string; target: string; access: "read" | "write" }[];
  }) => {
    setBusy(payload.title);
    try {
      const res = await createAutomation(payload);
      announceAutomationsChanged(); // new entry shows in the sidebar band right away
      await refresh();
      if (res.ok && res.task) {
        setShowForm(false);
        setOpenId(res.task.id);
      } else if (res.error) {
        alert(res.error);
      }
    } finally {
      setBusy(null);
    }
  };

  if (openId) {
    return (
      <TaskDetail
        id={openId}
        onBack={() => { setOpenId(null); refresh(); }}
        onOpenRun={onOpenRun}
        onRunNow={onRunNow}
        onOpenIntegrations={onOpenIntegrations}
      />
    );
  }

  const empty = tasks.length === 0;

  return (
    <Shell>
      <div className="flex items-start gap-3">
        <div className="flex-1 min-w-0">
          <PanelHead title={t("automations.title")} sub={t("automations.sub")} />
        </div>
        <button className={BTN_BORDERED} onClick={() => setShowForm((v) => !v)}>
          {t("automations.new_btn")}
        </button>
      </div>

      <div className="text-[12px] text-faint flex gap-1.5 mb-4">
        <span aria-hidden>ⓘ</span>
        <span>{t("automations.server_hint")}</span>
      </div>

      {showForm && (
        <NewAutomationForm
          busy={busy !== null}
          onCancel={() => setShowForm(false)}
          onCreate={create}
        />
      )}

      {/* The quickstart (§29): ONE template system — role recipes + generic templates, each
          card with §27 connector dots; picking one expands the configure card. */}
      {(empty || showForm) && <AutomationQuickstart busy={busy !== null} onCreate={create} />}

      {empty ? (
        !showForm && (
          <div className={CARD + " p-4 text-[13px] text-muted"}>
            <Trans
              i18nKey="automations.empty_state"
              components={{ strong: <strong /> }}
            />
          </div>
        )
      ) : (
        <div className="flex flex-col gap-2.5">
          {tasks.map((task) => (
            <div
              className={CARD + " sched-card px-4 py-3 cursor-pointer hover:border-lineStrong transition-colors"}
              key={task.id}
              onClick={() => setOpenId(task.id)}
            >
              <div className="flex items-center justify-between gap-2.5 mb-1">
                <span className="text-[13px] font-semibold truncate">{task.title}</span>
                <IconButton
                  small
                  tone="danger"
                  icon="trash"
                  size={14}
                  className="sched-card-del"
                  label={t("automations.delete_aria", { title: task.title })}
                  onClick={async (e) => {
                    e.stopPropagation();
                    await deleteAutomation(task.id);
                    refresh();
                  }}
                />
              </div>
              <div className="flex items-center gap-1.5 text-[12px] text-muted">
                <Icon name="clock" size={13} className="text-faint shrink-0" />
                {task.enabled ? task.schedule : t("automations.paused")} · {t("automations.next", { time: fmt(task.next_run) })} · {t("automations.run_count", { count: task.run_count })}
                {task.last_status ? ` · ${t("automations.last", { status: runStatusLabel(t, task.last_status) })}` : ""}
              </div>
            </div>
          ))}
        </div>
      )}
    </Shell>
  );
}

function NewAutomationForm({
  busy,
  onCancel,
  onCreate,
}: {
  busy: boolean;
  onCancel: () => void;
  onCreate: (p: { title: string; instructions: string; cron?: string; workspace?: string }) => void;
}) {
  const { t } = useTranslation();
  const [title, setTitle] = useState("");
  const [instructions, setInstructions] = useState("");
  const [time, setTime] = useState("09:00");
  const [freq, setFreq] = useState("daily");
  const [workspace, setWorkspace] = useState("");

  const valid = title.trim() && instructions.trim();

  return (
    <div className={CARD + " tmpl-form p-4 mb-4"}>
      <div className="text-[11px] uppercase tracking-[0.05em] text-faint mb-2.5">
        {t("automations.new_automation")}
      </div>
      <input
        className="tmpl-input"
        placeholder={t("automations.title_placeholder")}
        value={title}
        onChange={(e) => setTitle(e.target.value)}
      />
      <textarea
        className="tmpl-input tmpl-textarea"
        placeholder={t("automations.instructions_placeholder")}
        value={instructions}
        onChange={(e) => setInstructions(e.target.value)}
      />
      <div className="tmpl-sched">
        <label className="tmpl-field">
          <span>{t("automations.at")}</span>
          <input
            type="time"
            className="tmpl-input tmpl-time"
            value={time}
            onChange={(e) => setTime(e.target.value)}
          />
        </label>
        <label className="tmpl-field">
          <span>{t("automations.repeat")}</span>
          <select
            className="tmpl-input tmpl-select"
            value={freq}
            onChange={(e) => setFreq(e.target.value)}
          >
            {FREQ_OPTIONS.map((o) => (
              <option key={o.key} value={o.key}>{t(o.labelKey)}</option>
            ))}
          </select>
        </label>
      </div>
      <TaskFolderField value={workspace} onChange={setWorkspace} />
      <div className="tmpl-form-actions">
        <button
          className={BTN_ACCENT_SM}
          disabled={!valid || busy}
          onClick={() =>
            onCreate({
              title: title.trim(),
              instructions: instructions.trim(),
              cron: toCron(time, freq),
              workspace,
            })
          }
        >
          {busy ? t("automations.creating") : t("automations.create_btn")}
        </button>
        <button className="link" onClick={onCancel}>{t("automations.cancel")}</button>
      </div>
    </div>
  );
}

// F4: "发送到微信" — set (or drop) this automation's WeChat recipient, whatever surface
// created it. Three states: WeChat isn't connected at all; connected with no recipient yet
// (an inline picker + the §25 consent line mints the grant); connected with one or more
// recipients already granted (each with its own 撤销).
function WeixinDeliverySection({
  task,
  onChanged,
  onOpenIntegrations,
}: {
  task: Automation;
  onChanged: () => void;
  onOpenIntegrations: () => void;
}) {
  const { t } = useTranslation();
  const [connectors, setConnectors] = useState<Connector[] | null>(null);
  const [recent, setRecent] = useState<RecentChannel[]>([]);
  const [editing, setEditing] = useState(false);
  const [target, setTarget] = useState("");
  const [consent, setConsent] = useState(false);
  const [pickedName, setPickedName] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    getConnectors().then(setConnectors).catch(() => setConnectors([]));
    getRecentChannels().then(setRecent).catch(() => setRecent([]));
  }, [task.id]);

  const connected = !!connectors?.find((c) => c.name === "weixin")?.connected;
  const grants = (task.always_allowed || []).filter(
    (r) => r.tool === "send_message" && r.target?.startsWith("weixin:"),
  );
  const nameFor = (address: string) =>
    pickedName[address] || recent.find((c) => c.channel === address)?.name || address;
  // The exact sentence Save appends below — also what Revoke looks for to remove again.
  const sentenceFor = (addr: string) => "\n\n" + t("automations.deliver_weixin_sentence", { channel: addr });

  const save = async () => {
    if (!target || !consent) return;
    setSaving(true);
    try {
      const res = await updateAutomation(task.id, {
        grant: { tool: "send_message", target, access: "write" },
        instructions: task.instructions + sentenceFor(target),
      });
      if (res?.error) {
        alert(res.error);
        return;
      }
      setEditing(false);
      setTarget("");
      setConsent(false);
      onChanged();
    } finally {
      setSaving(false);
    }
  };

  const revoke = async (entry: string, revokeTarget: string) => {
    const sentence = sentenceFor(revokeTarget);
    const changes: Record<string, any> = { revoke: entry };
    // Template-created tasks (the quickstart recipes) weave their delivery line INTO the
    // recipe's own wording (e.g. tmpl_inspection_instructions) rather than appending this
    // exact sentence, so it never matches here and the instructions survive untouched —
    // the user removes it by hand via 编辑 if they revoke a template's recipient.
    if (task.instructions.includes(sentence)) {
      changes.instructions = task.instructions.replace(sentence, "");
    }
    const res = await updateAutomation(task.id, changes);
    if (res?.error) alert(res.error);
    onChanged();
  };

  if (connectors === null) return <div className="dim">{t("automations.loading")}</div>;

  if (!connected)
    return (
      <div className="flex items-center gap-2.5 text-[13px] text-muted">
        <span>{t("automations.deliver_weixin_not_connected")}</span>
        <button className={BTN_BORDERED_SM} onClick={onOpenIntegrations}>
          {t("automations.go_connect")}
        </button>
      </div>
    );

  return (
    <div>
      {grants.length > 0 && (
        <div className="sched-grants" data-testid="deliver-weixin-grants">
          {grants.map((rule) => (
            <div className="sched-grant" key={rule.entry}>
              <span className="sched-grant-rule">{nameFor(rule.target!)}</span>
              <button
                className="link"
                title={t("automations.revoke_title")}
                onClick={() => revoke(rule.entry, rule.target!)}
              >
                {t("automations.revoke")}
              </button>
            </div>
          ))}
        </div>
      )}
      {editing ? (
        <div className="rounded-xl2 border border-line bg-paper p-3 mt-2" data-testid="deliver-weixin-editor">
          <ChannelPicker
            value={target}
            onChange={setTarget}
            recent={recent.filter((c) => c.channel.startsWith("weixin:"))}
            onPickName={(address, name) => setPickedName((m) => ({ ...m, [address]: name }))}
          />
          <p className="text-[11px] text-warnInk mt-1">{t("automations.bot_member_hint")}</p>
          <label className="flex items-start gap-2.5 mt-2.5 text-[13px] text-muted select-none">
            <input
              type="checkbox"
              className="mt-0.5"
              checked={consent}
              onChange={(e) => setConsent(e.target.checked)}
              data-testid="deliver-weixin-consent"
            />
            <span>
              {t("automations.consent_prefix")}{" "}
              <b className="text-ink" title={target || undefined}>
                {target ? nameFor(target) : t("automations.the_channel")}
              </b>{" "}
              {t("automations.consent_suffix")}
            </span>
          </label>
          <div className="flex items-center gap-3 mt-3">
            <button
              className={BTN_ACCENT_SM}
              disabled={!target || !consent || saving}
              onClick={save}
              data-testid="deliver-weixin-save"
            >
              {saving ? t("automations.saving") : t("automations.save")}
            </button>
            <button
              className="link"
              onClick={() => {
                setEditing(false);
                setTarget("");
                setConsent(false);
              }}
            >
              {t("automations.cancel")}
            </button>
          </div>
        </div>
      ) : (
        <button
          className={BTN_BORDERED_SM + (grants.length > 0 ? " mt-2" : "")}
          onClick={() => setEditing(true)}
          data-testid="deliver-weixin-set"
        >
          {t("automations.set_recipient")}
        </button>
      )}
    </div>
  );
}

function TaskDetail({
  id,
  onBack,
  onOpenRun,
  onRunNow,
  onOpenIntegrations,
}: {
  id: string;
  onBack: () => void;
  onOpenRun: (
    sessionId: string,
    workspace: string,
    agent: string,
    task?: { id: string; title: string },
  ) => void;
  onRunNow: (taskId: string, title?: string) => void;
  onOpenIntegrations: () => void;
}) {
  const { t } = useTranslation();
  const [task, setTask] = useState<Automation | null>(null);
  const [runs, setRuns] = useState<AutomationRun[]>([]);
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState("");
  const [instructions, setInstructions] = useState("");
  const [time, setTime] = useState("09:00");
  const [freq, setFreq] = useState("daily");
  const [workspace, setWorkspace] = useState("");
  // False when the stored schedule says more than the simple form can (agent-written
  // cron, once-tasks) — saving would rewrite it, so the edit form must say so.
  const [cronMatched, setCronMatched] = useState(true);
  // Only a schedule the user actually touched gets written back. An unmatched cron
  // (agent-written, once-task) must survive a title/instructions-only edit untouched —
  // otherwise fixing a typo silently turns "every 1st at 9" into "daily at 9".
  const [schedTouched, setSchedTouched] = useState(false);
  const [saving, setSaving] = useState(false);

  // The seen mark AS OF opening — the "new" pills compare against this frozen value
  // while mark-seen advances the stored one (badge clears; highlights survive).
  const [seenMark, setSeenMark] = useState<number | null>(null);

  const refresh = () =>
    getAutomation(id)
      .then((d) => {
        if (!d.task) {
          // Deleted (or a stale reopen target): "Loading…" forever is a trap —
          // fall back to the overview (owner-hit 2026-07-20).
          onBack();
          return;
        }
        setTask(d.task);
        setRuns(d.runs || []);
        setSeenMark((cur) => (cur === null ? d.task?.seen_runs_at ?? 0 : cur));
      })
      .catch(() => {});
  useEffect(() => {
    setSeenMark(null);
    refresh();
    // Opening the detail IS reading it: advance the seen mark and nudge the
    // sidebar so the badge clears immediately (UX-023).
    markAutomationSeen(id)
      .then(() => announceAutomationsChanged())
      .catch(() => {});
  }, [id]);

  if (!task)
    return (
      <Shell>
        <div className="text-[13px] text-muted">{t("automations.loading")}</div>
      </Shell>
    );

  // The workspace value the form starts from — "" for a private automation regardless of
  // what `task.workspace` itself holds, since only `workspace_private` is the display source
  // of truth (F3).
  const origWorkspace = () => (task.workspace_private ? "" : task.workspace);
  const startEdit = () => {
    setTitle(task.title);
    setInstructions(task.instructions);
    const { time: t, freq: f, matched } = fromCron(task.schedule_raw?.cron);
    setTime(t);
    setFreq(f);
    setCronMatched(matched);
    setSchedTouched(false);
    setWorkspace(origWorkspace());
    setEditing(true);
  };
  const saveEdit = async () => {
    setSaving(true);
    try {
      const res = await updateAutomation(id, {
        title: title.trim(),
        instructions: instructions.trim(),
        ...(cronMatched || schedTouched ? { cron: toCron(time, freq) } : {}),
        // Only sent when the user actually touched it — an untouched folder must survive a
        // title/instructions-only edit unchanged (same rule as the schedule above).
        ...(workspace !== origWorkspace() ? { workspace } : {}),
      });
      // A folder that vanished between picking and saving is refused server-side — keep the
      // form open with the user's edits instead of closing as if it had saved.
      if (res?.error) {
        alert(res.error);
        return;
      }
      await refresh();
      setEditing(false);
    } finally {
      setSaving(false);
    }
  };
  const toggle = async () => {
    await updateAutomation(id, { enabled: !task.enabled });
    refresh();
  };
  const remove = async () => {
    await deleteAutomation(id);
    announceAutomationsChanged(); // the sidebar band must not wait out its poll
    onBack();
  };

  // F4 carves send_message → weixin:* grants out into their own "发送到微信" section below —
  // everything else keeps living under "无需询问的允许项" (hidden entirely once it's empty).
  const otherGrants = (task.always_allowed || []).filter(
    (rule) => !(rule.tool === "send_message" && rule.target?.startsWith("weixin:")),
  );

  return (
    <Shell>
      <BackLink className="mb-3" onClick={onBack}>
        {t("automations.back_to_automations")}
      </BackLink>
      <div className="sched-detail">
        <div className="sched-detail-head">
          {editing ? (
            <input
              className="tmpl-input sched-edit-title"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder={t("automations.title_label")}
            />
          ) : (
            <h2 className="text-[20px] font-semibold tracking-tight">{task.title}</h2>
          )}
          <div className="sched-actions">
            {editing ? (
              <>
                <button className={BTN_ACCENT_SM} disabled={saving || !title.trim() || !instructions.trim()} onClick={saveEdit}>
                  {saving ? t("automations.saving") : t("automations.save")}
                </button>
                <button className="link" onClick={() => setEditing(false)}>{t("automations.cancel")}</button>
              </>
            ) : (
              <>
                <button className={BTN_ACCENT_SM} onClick={() => onRunNow(id, task.title)}>
                  {t("automations.run_now")}
                </button>
                <button className={BTN_BORDERED_SM} onClick={startEdit}>{t("automations.edit")}</button>
                <button className={BTN_DANGER_SM + " inline-flex items-center gap-1.5"} onClick={remove}>
                  <Icon name="trash" size={14} /> {t("automations.delete")}
                </button>
              </>
            )}
          </div>
        </div>

        {editing ? (
          <>
            <div className="tmpl-sched sched-edit-sched">
              <label className="tmpl-field">
                <span>{t("automations.at")}</span>
                <input
                  type="time"
                  className="tmpl-input tmpl-time"
                  value={time}
                  onChange={(e) => {
                    setTime(e.target.value);
                    setSchedTouched(true);
                  }}
                />
              </label>
              <label className="tmpl-field">
                <span>{t("automations.repeat")}</span>
                <select
                  className="tmpl-input tmpl-select"
                  value={freq}
                  onChange={(e) => {
                    setFreq(e.target.value);
                    setSchedTouched(true);
                  }}
                >
                  {FREQ_OPTIONS.map((o) => (
                    <option key={o.key} value={o.key}>{t(o.labelKey)}</option>
                  ))}
                </select>
              </label>
            </div>
            {!cronMatched && (
              <p className="text-[12px] text-warnInk mt-1" data-testid="cron-rewrite-warning">
                {t("automations.cron_rewrite_warning", {
                  schedule: task.schedule_raw?.cron || task.schedule,
                })}
              </p>
            )}
          </>
        ) : (
          <div className="conn-meta">
            <label className="switch">
              <input type="checkbox" checked={task.enabled} onChange={toggle} />
              <span className="slider" />
            </label>{" "}
            {task.enabled ? t("automations.active_next", { time: fmt(task.next_run) }) : t("automations.paused")} · {task.schedule}
          </div>
        )}

        <div className="sa-sub">{t("automations.folder_label")}</div>
        {editing ? (
          <TaskFolderField value={workspace} onChange={setWorkspace} />
        ) : (
          <div
            className="dim"
            style={{ marginBottom: 8, fontSize: 12.5 }}
            title={task.workspace_private ? undefined : task.workspace}
          >
            {task.workspace_private ? t("automations.folder_private") : task.workspace}
          </div>
        )}

        <div className="sa-sub">{t("automations.instructions_label")}</div>
        {editing ? (
          <textarea
            className="tmpl-input tmpl-textarea sched-edit-instr"
            value={instructions}
            onChange={(e) => setInstructions(e.target.value)}
          />
        ) : (
          <div className="sched-instructions">{task.instructions}</div>
        )}

        {/* F4 gives send_message → weixin:* grants their own "发送到微信" section below —
            listing them here too would say the same thing twice. */}
        {otherGrants.length > 0 && (
          <>
            <div className="sa-sub">{t("automations.allowed_without_asking")}</div>
            <div className="dim" style={{ marginBottom: 8, fontSize: 12.5 }}>
              {t("automations.allowed_desc")}
            </div>
            <div className="sched-grants" data-testid="task-grants">
              {otherGrants.map((rule) => (
                <div className="sched-grant" key={rule.entry}>
                  <span className="sched-grant-rule">
                    <code>{rule.tool}</code>
                    {rule.target && <span className="sched-grant-target"> → {rule.target}</span>}
                  </span>
                  <button
                    className="link"
                    title={t("automations.revoke_title")}
                    onClick={async () => {
                      await updateAutomation(id, { revoke: rule.entry });
                      refresh();
                    }}
                  >
                    {t("automations.revoke")}
                  </button>
                </div>
              ))}
            </div>
          </>
        )}

        <div className="sa-sub">{t("automations.deliver_weixin_title")}</div>
        <WeixinDeliverySection task={task} onChanged={refresh} onOpenIntegrations={onOpenIntegrations} />

        <div className="sa-sub">{t("automations.runs_label")}</div>
        <div className="dim" style={{ marginBottom: 8, fontSize: 12.5 }}>
          {t("automations.runs_desc")}
        </div>
        {runs.length === 0 && <div className="dim">{t("automations.no_runs")}</div>}
        {runs.map((r) => (
          <div
            className="sched-run open"
            key={r.run_id}
            onClick={() =>
              r.session_id &&
              onOpenRun(r.session_id, task.workspace, task.agent, {
                id: task.id,
                title: task.title,
              })
            }
            title={t("automations.open_run")}
          >
            <div className="sched-run-row">
              <span>
                {seenMark !== null && r.started_at > seenMark && (
                  <span className="run-new-pill" data-testid="run-new">{t("automations.new_pill")}</span>
                )}
                {fmt(r.started_at)} · <span className={"run-" + r.status}>{runStatusLabel(t, r.status)}</span> · {runTriggerLabel(t, r.trigger)}
                {r.artifacts.length > 0 && <span className="dim"> · {t("automations.file_count", { count: r.artifacts.length })}</span>}
              </span>
              <span className="sched-run-go" aria-hidden>
                {t("automations.open_go")}
              </span>
            </div>
            {r.result_text && <div className="sched-run-peek">{r.result_text}</div>}
            {r.error && <div className="mcp-error">{r.error}</div>}
          </div>
        ))}
      </div>
    </Shell>
  );
}
