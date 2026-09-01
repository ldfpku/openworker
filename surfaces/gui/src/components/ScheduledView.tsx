import { useEffect, useState } from "react";
import { Trans, useTranslation } from "react-i18next";
import {
  createAutomation,
  deleteAutomation,
  getAutomation,
  getAutomations,
  markAutomationSeen,
  announceAutomationsChanged,
  updateAutomation,
  type Automation,
  type AutomationRun,
} from "../api";
import { Icon } from "./Icon";
import { PanelHead } from "./IntegrationsView";
import { AutomationQuickstart } from "./AutomationQuickstart";
import { FREQ_OPTIONS, fromCron, toCron } from "../schedule";

// Shared utility strings (the §28 page shell — mirrors IntegrationsView's constants).
const CARD = "rounded-xl2 border border-line bg-panel";

const fmt = (t: number | null) =>
  t ? new Date(t * 1000).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }) : "—";

// Backend enums (coworker/automation/models.py TaskRun.status / .trigger) come across the wire
// as raw tokens — map each to a translated label rather than rendering it verbatim.
function runStatusLabel(t: (key: string) => string, status?: string | null): string {
  switch (status) {
    case "ok":
      return t("ok");
    case "running":
      return t("running");
    case "error":
      return t("error");
    case "skipped":
      return t("skipped");
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
}

export function ScheduledView({ onOpenRun, onRunNow, initialOpenId }: Props) {
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
        <button
          className="text-[13px] px-3 py-1.5 rounded-lg border border-lineStrong bg-panel hover:border-accent hover:text-accent shrink-0"
          onClick={() => setShowForm((v) => !v)}
        >
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
                <button
                  className="sched-card-del"
                  title={t("automations.delete_title")}
                  aria-label={t("automations.delete_aria", { title: task.title })}
                  onClick={async (e) => {
                    e.stopPropagation();
                    await deleteAutomation(task.id);
                    refresh();
                  }}
                >
                  <Icon name="trash" size={14} />
                </button>
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
  onCreate: (p: { title: string; instructions: string; cron?: string }) => void;
}) {
  const { t } = useTranslation();
  const [title, setTitle] = useState("");
  const [instructions, setInstructions] = useState("");
  const [time, setTime] = useState("09:00");
  const [freq, setFreq] = useState("daily");

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
      <div className="tmpl-form-actions">
        <button
          className="btn-primary sm"
          disabled={!valid || busy}
          onClick={() =>
            onCreate({
              title: title.trim(),
              instructions: instructions.trim(),
              cron: toCron(time, freq),
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

function TaskDetail({
  id,
  onBack,
  onOpenRun,
  onRunNow,
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
}) {
  const { t } = useTranslation();
  const [task, setTask] = useState<Automation | null>(null);
  const [runs, setRuns] = useState<AutomationRun[]>([]);
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState("");
  const [instructions, setInstructions] = useState("");
  const [time, setTime] = useState("09:00");
  const [freq, setFreq] = useState("daily");
  // False when the stored schedule says more than the simple form can (agent-written
  // cron, once-tasks) — saving would rewrite it, so the edit form must say so.
  const [cronMatched, setCronMatched] = useState(true);
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

  const startEdit = () => {
    setTitle(task.title);
    setInstructions(task.instructions);
    const { time: t, freq: f, matched } = fromCron(task.schedule_raw?.cron);
    setTime(t);
    setFreq(f);
    setCronMatched(matched);
    setEditing(true);
  };
  const saveEdit = async () => {
    setSaving(true);
    try {
      await updateAutomation(id, {
        title: title.trim(),
        instructions: instructions.trim(),
        cron: toCron(time, freq),
      });
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

  return (
    <Shell>
      <button className="text-[13px] text-muted hover:text-ink mb-3" onClick={onBack}>
        {t("automations.back_to_automations")}
      </button>
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
                <button className="btn-primary sm" disabled={saving || !title.trim() || !instructions.trim()} onClick={saveEdit}>
                  {saving ? t("automations.saving") : t("automations.save")}
                </button>
                <button className="link" onClick={() => setEditing(false)}>{t("automations.cancel")}</button>
              </>
            ) : (
              <>
                <button className="btn-primary sm" onClick={() => onRunNow(id, task.title)}>
                  {t("automations.run_now")}
                </button>
                <button className="btn sm" onClick={startEdit}>{t("automations.edit")}</button>
                <button className="btn sm danger-btn" onClick={remove}>
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
                <input type="time" className="tmpl-input tmpl-time" value={time} onChange={(e) => setTime(e.target.value)} />
              </label>
              <label className="tmpl-field">
                <span>{t("automations.repeat")}</span>
                <select className="tmpl-input tmpl-select" value={freq} onChange={(e) => setFreq(e.target.value)}>
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

        {(task.always_allowed || []).length > 0 && (
          <>
            <div className="sa-sub">{t("automations.allowed_without_asking")}</div>
            <div className="dim" style={{ marginBottom: 8, fontSize: 12.5 }}>
              {t("automations.allowed_desc")}
            </div>
            <div className="sched-grants" data-testid="task-grants">
              {(task.always_allowed || []).map((rule) => (
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
