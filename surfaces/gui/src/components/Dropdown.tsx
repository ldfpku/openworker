import { useState } from "react";
import { Icon } from "./Icon";

export interface Option {
  value: string;
  label: string;
  description?: string;
  /** Quiet pill after the label (e.g. "Free" on models that cost nothing per token). */
  badge?: string;
  /** Tooltip for the badge — say what "free" actually means rather than overclaiming. */
  badgeTitle?: string;
  /** Quiet outlined tag right after the label: a plain fact about the row ("Restricted"),
   * not a perk — so it does not compete for the badge pill. */
  tag?: string;
  tagTitle?: string;
  /** Short muted note at the row's right edge (a model's price: "$3 / $15"); `metaTitle`
   * spells it out. Keep it to a few characters — the menu is as wide as its widest row. */
  meta?: string;
  metaTitle?: string;
}

interface Props {
  prefix?: string;
  value: string;
  options: Option[];
  onChange: (value: string) => void;
  align?: "left" | "right";
  // Extra classes appended to the trigger pill (e.g. "chip" for a bordered composer-head chip).
  className?: string;
  // Mount already open — the composer passes this when the user clicked the "Loading models…"
  // placeholder before the list arrived, so the click they already made is honoured instead
  // of silently dropped (owner-hit 2026-09-03: "first click does nothing, second opens").
  defaultOpen?: boolean;
}

export function Dropdown({ prefix, value, options, onChange, align = "left", className, defaultOpen }: Props) {
  const [open, setOpen] = useState(!!defaultOpen);
  const current = options.find((o) => o.value === value);
  const label = (prefix ? `${prefix}: ` : "") + (current?.label || value);
  // With a right-edge note on any row, every row keeps the ✓'s width free — otherwise the
  // selected row's note would sit a check-mark to the left of all the others.
  const hasMeta = options.some((o) => o.meta);
  return (
    <div className="dd">
      <button
        type="button"
        className={"pill" + (className ? " " + className : "")}
        onClick={() => setOpen((v) => !v)}
        title={label}
      >
        <span className="pill-label">{label}</span>
        <Icon name="chevronDown" size={13} className="caret" />
      </button>
      {open && (
        <>
          <div className="dd-backdrop" onClick={() => setOpen(false)} />
          <div className={"dd-menu " + align + (hasMeta ? " has-meta" : "")}>
            {options.map((o) => (
              <div
                key={o.value}
                className={"dd-item" + (o.value === value ? " sel" : "")}
                onClick={() => {
                  onChange(o.value);
                  setOpen(false);
                }}
              >
                <div className="dd-label">
                  {o.label}
                  {o.tag && (
                    <span className="dd-tag" title={o.tagTitle}>
                      {o.tag}
                    </span>
                  )}
                  {o.badge && (
                    <span className="dd-badge" title={o.badgeTitle}>
                      {o.badge}
                    </span>
                  )}
                  {o.meta && (
                    <span className="dd-meta" title={o.metaTitle}>
                      {o.meta}
                    </span>
                  )}
                  {o.value === value ? (
                    <span className="chk">✓</span>
                  ) : (
                    hasMeta && <span className="chk-space" aria-hidden="true" />
                  )}
                </div>
                {o.description && <div className="dd-desc">{o.description}</div>}
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
