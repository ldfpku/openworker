import type { ButtonHTMLAttributes } from "react";
import { Icon } from "./Icon";

// The one "go back to the parent view" control for every drill-in page: provider setup,
// connector detail, automation detail, gallery card, persona page, source connect/channels.
//
// Before this each site hand-rolled a muted 13px text button with a "‹" or "←" glyph baked
// into the i18n string — low contrast, no hit area, no icon, easy to miss (owner report
// 2026-09-03: users did not notice "‹ All providers"). The arrow is drawn here, so labels
// are plain nouns ("All providers"); the accent color + hover wash make it read as a control.
export function BackLink({ children, className, ...rest }: ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button type="button" className={"back-link" + (className ? " " + className : "")} {...rest}>
      <Icon name="arrowLeft" size={14} />
      <span>{children}</span>
    </button>
  );
}
