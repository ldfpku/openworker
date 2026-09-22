import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { formatElapsed } from "../relTime";

// Shown while a turn is running but has produced nothing to render yet (no stream, no
// reasoning trace, not compacting). A 2026-09-18 stall sat in exactly this state for a long
// time with no on-screen signal that anything was wrong — once the wait crosses this
// threshold the label grows an elapsed-time suffix so a stuck wait looks different from a
// slow one. The first ELAPSED_THRESHOLD_MS look identical to before this change.
const ELAPSED_THRESHOLD_MS = 10_000;

export function WaitingForAgent({ label }: { label?: string }) {
  const { t } = useTranslation();
  // Mount-time anchor, not an accumulating counter — elapsed is recomputed from Date.now() on
  // every tick, so it can't drift even if a timer fires late.
  const startedAt = useRef(Date.now());
  const [, tick] = useState(0);

  useEffect(() => {
    // The compacting label is static copy with no elapsed suffix — skip the ticking entirely.
    if (label) return;
    const id = setInterval(() => tick((n) => n + 1), 1000);
    return () => clearInterval(id);
  }, [label]);

  const elapsed = Date.now() - startedAt.current;
  const text =
    label ||
    (elapsed >= ELAPSED_THRESHOLD_MS
      ? t("app.waiting_for_agent_elapsed", { duration: formatElapsed(elapsed, t) })
      : t("app.waiting_for_agent"));

  return (
    <div className="waiting-transcript">
      <div className="waiting-row" aria-live="polite">
        <span className="waiting-spinner" />
        <span>{text}</span>
      </div>
    </div>
  );
}
