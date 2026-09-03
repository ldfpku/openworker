import type { ButtonHTMLAttributes } from "react";
import { Icon, type IconName } from "./Icon";

// The one icon-only button. Every site used to pick its own class (.topbar-icon-btn,
// .artifact-icon-btn, .icon-btn, `btn icon-only`, ad-hoc Tailwind) and decide on its own
// whether to add a tooltip — so half the glyphs in the app were mute (owner report
// 2026-09-03: Skills row had a tooltip on edit but not on delete). `label` is required and
// feeds BOTH the native tooltip and the accessible name, so an icon button cannot ship
// without one. Visual variants stay in styles.css under `.icon-btn`.
type Props = Omit<ButtonHTMLAttributes<HTMLButtonElement>, "children" | "title" | "aria-label"> & {
  /** Tooltip + accessible name. What the button does, as a verb phrase. */
  label: string;
  icon: IconName;
  /** Glyph size in px (the hit area is fixed at 30×30, or 26×26 for `small`). */
  size?: number;
  /** `ghost` (default) is borderless; `bordered` matches `.btn` for rows of mixed buttons;
   *  `inline` has no box at all — the glyph sits in running text or a chip (the "×" family). */
  variant?: "ghost" | "bordered" | "inline";
  /** `danger` turns the glyph red on hover — delete / remove / sign-out. */
  tone?: "default" | "danger";
  /** Pressed look (menu open, filter on). Also sets aria-pressed. */
  active?: boolean;
  /** 26×26 hit area — dense rows (rail section headers, memory rows). */
  small?: boolean;
  /** 20×20 hit area — affordances that live inside a list row (sidebar). */
  tiny?: boolean;
};

export function IconButton({
  label,
  icon,
  size = 16,
  variant = "ghost",
  tone = "default",
  active,
  small,
  tiny,
  className,
  ...rest
}: Props) {
  const cls = [
    "icon-btn",
    variant !== "ghost" && variant,
    tone === "danger" && "danger",
    active && "active",
    small && "sm",
    tiny && "xs",
    className,
  ]
    .filter(Boolean)
    .join(" ");
  return (
    <button
      type="button"
      className={cls}
      title={label}
      aria-label={label}
      aria-pressed={active === undefined ? undefined : active}
      {...rest}
    >
      <Icon name={icon} size={size} />
    </button>
  );
}
