import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { isRestrictedTier, priceHint, type ModelPrice } from "../modelPrice";

// The name cell of a model row in Settings ▸ Models' two checklists (a provider's own list
// and the "In the composer's picker" card): the model's name, then — for company-gateway
// models only, and only when the guard said so — a quiet "Restricted" tag and the list
// price. It renders INSIDE the row's `.mlist-main` label, after the checkbox.
//
// With neither a price nor a tier the output is exactly the bare name (+ the caller's
// badges) the rows always had: every other provider's rows, and gateway rows against a
// guard that predates the fields, are untouched down to the DOM.
//
// Otherwise two groups share one wrapping line — [name + the caller's badges] and
// [Restricted tag + price]. While the row has room they sit side by side, tag right after
// the name. When it does not (a narrower window: the card's rows also carry a provider tag
// and the default button) the second group drops under the name, aligned with it, so the
// name keeps its line instead of being squeezed to an ellipsis. Either way everything stays
// inside the flexible name cell, so whatever follows that cell never moves.
export function ModelRowLabel({
  id,
  name,
  price,
  tier,
  children,
}: {
  id: string; // full model id — the name's tooltip, and the test ids
  name: string;
  price?: ModelPrice | null; // USD per 1M input / output tokens; absent → no hint
  tier?: string | null; // "limited" → the Restricted tag; anything else → none
  children?: ReactNode; // the caller's own badges (off-catalog, Free), after the name
}) {
  const { t } = useTranslation();
  const hint = priceHint(price, t);
  const restricted = isRestrictedTier(tier);
  const ident = (
    <>
      <span className="mlist-name" title={id}>
        {name}
      </span>
      {children}
    </>
  );
  if (!hint && !restricted) return ident;
  return (
    <span className="mlist-wrap">
      <span className="mlist-ident">{ident}</span>
      <span className="mlist-extra">
        {restricted && (
          // A model the administrator opened to the 总经理 / 管理员 roles only (whoever
          // sees it in their list holds one of them).
          <span className="mlist-tag" title={t("models.restricted_tip")} data-testid={`mlist-restricted-${id}`}>
            {t("models.restricted")}
          </span>
        )}
        {hint && (
          <span className="mlist-price" title={hint.title} data-testid={`mlist-price-${id}`}>
            {hint.text}
          </span>
        )}
      </span>
    </span>
  );
}
