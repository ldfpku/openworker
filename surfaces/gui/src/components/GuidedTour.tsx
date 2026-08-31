import { useLayoutEffect, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

// First-run guided tour (owner ask 2026-08-27): anchored step cards in the FreeToken style —
// a category badge, progress dots, title + one-paragraph description, and Skip/Next buttons —
// spotlighting the five things a new operator must know (new session, composer, model pick,
// coworker/folder setup, account menu). Auto-opens once per device; replayable from the
// account menu. A step whose anchor isn't in the DOM (collapsed nav, no setup row) is
// skipped silently, so the tour degrades instead of pointing at nothing.

// Per-device "seen it" flag — same naming family as the rail/nav prefs.
export const TOUR_DONE_KEY = "coworker:tour-done:v1";

type TourStep = {
  badge: string;
  title: string;
  body: string;
  // First selector that matches wins; none matching skips the step.
  selectors: string[];
};

const SPOT_PAD = 6; // px of breathing room between the anchor and the spotlight ring

export function GuidedTour(props: { onDone: () => void }) {
  const { t } = useTranslation();

  const steps: TourStep[] = [
    {
      badge: t("Session"),
      title: t("Start here"),
      body: t(
        "Click to open a new session. Describe the job in one sentence — big tasks get broken into steps automatically.",
      ),
      selectors: ['[data-tour="new-session"]'],
    },
    {
      badge: t("Composer"),
      title: t("Hand over the work"),
      body: t(
        "Type your task here. Drag files straight in, or type / to call an installed skill by name.",
      ),
      selectors: ['[data-tour="composer"]'],
    },
    {
      badge: t("Model"),
      title: t("Pick a model"),
      body: t(
        "Gemini 3.7 Flash is the fast default for daily work. Switch to Gemini 3.1 Pro when you need deeper reasoning — slower and pricier.",
      ),
      selectors: ['[data-tour="model"]'],
    },
    {
      badge: t("Setup"),
      title: t("Coworker and folder"),
      body: t(
        "Pick which coworker leads this session and which folder it may work in — it never touches folders you haven't granted.",
      ),
      selectors: ['[data-testid="setup-row"]'],
    },
    {
      badge: t("Expert library"),
      title: t("Experts, skills and settings"),
      body: t(
        "The account menu lives here: Help is the full manual, the Expert library offers 270+ experts and 160+ research skills, and Settings ▸ Models is where you sign in and paste your key on first use.",
      ),
      selectors: ['[data-testid="account-row"]'],
    },
  ];

  const [idx, setIdx] = useState(0);
  const [rect, setRect] = useState<DOMRect | null>(null);
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);
  const cardRef = useRef<HTMLDivElement | null>(null);

  const findEl = (i: number): HTMLElement | null => {
    for (const sel of steps[i].selectors) {
      const el = document.querySelector(sel);
      if (el instanceof HTMLElement) return el;
    }
    return null;
  };

  // Resolve the current step's anchor; fast-forward past missing ones; track its rect
  // through resizes and any ancestor scroll. All-missing ends the tour outright.
  useEffect(() => {
    let i = idx;
    while (i < steps.length && !findEl(i)) i++;
    if (i >= steps.length) {
      props.onDone();
      return;
    }
    if (i !== idx) {
      setIdx(i);
      return;
    }
    const el = findEl(i)!;
    el.scrollIntoView?.({ block: "nearest", inline: "nearest" });
    const measure = () => setRect(el.getBoundingClientRect());
    measure();
    window.addEventListener("resize", measure);
    window.addEventListener("scroll", measure, true);
    return () => {
      window.removeEventListener("resize", measure);
      window.removeEventListener("scroll", measure, true);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [idx]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && props.onDone();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Place the card once its real size is known: beside a narrow anchor (sidebar rows) when
  // there's room to the right, else below, else above, else centered. Runs every render;
  // the equality guard keeps it from looping.
  useLayoutEffect(() => {
    if (!rect || !cardRef.current) return;
    const c = cardRef.current.getBoundingClientRect();
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const GAP = 14;
    const PAD = 12;
    const clampX = (x: number) => Math.min(Math.max(x, PAD), Math.max(PAD, vw - c.width - PAD));
    const clampY = (y: number) => Math.min(Math.max(y, PAD), Math.max(PAD, vh - c.height - PAD));
    let top: number;
    let left: number;
    if (rect.width < 300 && vw - rect.right >= c.width + GAP + PAD) {
      left = rect.right + GAP + SPOT_PAD;
      top = clampY(rect.top);
    } else if (vh - rect.bottom >= c.height + GAP + PAD) {
      top = rect.bottom + GAP + SPOT_PAD;
      left = clampX(rect.left);
    } else if (rect.top >= c.height + GAP + PAD) {
      top = rect.top - c.height - GAP - SPOT_PAD;
      left = clampX(rect.left);
    } else {
      top = clampY((vh - c.height) / 2);
      left = clampX((vw - c.width) / 2);
    }
    setPos((p) => (p && p.top === top && p.left === left ? p : { top, left }));
  });

  if (!rect) return null;
  const step = steps[idx];
  // Whether any LATER step has a live anchor decides the primary button's label; if none
  // do, this is the last visible step and the button finishes the tour.
  const hasNext = steps.slice(idx + 1).some((_, k) => findEl(idx + 1 + k));

  return (
    <div role="dialog" aria-modal="true" aria-label={t("Guided tour")}>
      <div className="tour-blocker" />
      <div
        className="tour-spot"
        style={{
          top: rect.top - SPOT_PAD,
          left: rect.left - SPOT_PAD,
          width: rect.width + SPOT_PAD * 2,
          height: rect.height + SPOT_PAD * 2,
        }}
      />
      <div
        ref={cardRef}
        className="tour-card"
        data-testid="tour-card"
        style={pos ? { top: pos.top, left: pos.left } : { top: 0, left: 0, visibility: "hidden" }}
      >
        <div className="tour-head">
          <span className="tour-badge">{step.badge}</span>
          <span
            className="tour-dots"
            role="img"
            aria-label={t("Step {{n}} of {{total}}", { n: idx + 1, total: steps.length })}
          >
            {steps.map((_, i) => (
              <i key={i} className={i === idx ? "on" : ""} />
            ))}
          </span>
        </div>
        <div className="tour-title">{step.title}</div>
        <div className="tour-body">{step.body}</div>
        <div className="tour-foot">
          <button className="tour-skip" data-testid="tour-skip" onClick={props.onDone}>
            {t("Skip tour")}
          </button>
          <button
            className="tour-next"
            data-testid="tour-next"
            onClick={() => (hasNext ? setIdx(idx + 1) : props.onDone())}
          >
            {hasNext ? t("Next") : t("Done")}
          </button>
        </div>
      </div>
    </div>
  );
}
