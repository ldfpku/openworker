// The price hint next to a model in the model lists (Settings ▸ Models' two checklists and
// the composer's picker), plus the "Restricted" tier check that sits beside it.
//
// Prices exist for ONE provider: the company AI Gateway. Its guard's `GET /gate/models`
// lists each model's price in USD per 1,000,000 input / output tokens as charged to the
// company account, and the server passes them through as /v1/settings `model_prices`
// ({full id → {in?, out?}}). Everything here only FORMATS what arrived: a model that is
// not in the map, or a side that is missing or malformed, shows nothing — a price is never
// estimated, defaulted or filled in from anywhere else.

/** One model's list price, USD per 1M tokens. Either side may be missing. */
export interface ModelPrice {
  in?: number | null;
  out?: number | null;
}

export type ModelPrices = Record<string, ModelPrice | null | undefined>;

/** {full id → tier}. Only "limited" is ever sent (a model opened to 总经理 / 管理员 only). */
export type ModelTiers = Record<string, string | null | undefined>;

export const isRestrictedTier = (tier: unknown): boolean => tier === "limited";

/** "$3", "$2.5", "$0.15", "$0.051" — or null when `value` is not a usable price.
 *
 * Trailing zeros are trimmed so whole dollars stay bare ("$15", not "$15.00"). A dollar
 * and up keeps at most three decimals ("$18.75", "$1.125"); below a dollar it keeps four
 * significant digits, so the small models' prices keep the digits that tell them apart
 * ("$0.051", "$0.0375"). Always positional — never "5e-7". Anything that is not a finite
 * number ≥ 0 (a string, NaN, a negative) is "no price", the same rule as the server's
 * `clean_price`. */
export function formatUsd(value: unknown): string | null {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0) return null;
  if (value === 0) return "$0";
  // Below a hundredth of a cent per million tokens the digits stop meaning anything: say
  // "less than" rather than print a row of zeros — and never round a real price to "$0".
  if (value < 0.0001) return "<$0.0001";
  const fixed = value >= 1 ? value.toFixed(3) : Number(value.toPrecision(4)).toFixed(7);
  return `$${fixed.replace(/\.?0+$/, "")}`;
}

export interface PriceHint {
  /** Row text: "$3 / $15 per 1M tokens" · "$3 / $15 每百万 token". */
  text: string;
  /** Where there is no room for the unit (the composer's picker): "$3 / $15". */
  short: string;
  /** Tooltip, spelled out: "输入 $3 · 输出 $15（美元 / 百万 token）". */
  title: string;
}

type Translate = (key: string, vars?: Record<string, string>) => string;

/** The hint for one model, or null when there is nothing to show. `t` is the i18n lookup
 * (`useTranslation().t`), so the words stay in the locale files; with only one side priced
 * the hint names that side instead of leaving a dangling slash. */
export function priceHint(price: ModelPrice | null | undefined, t: Translate): PriceHint | null {
  if (!price || typeof price !== "object") return null;
  const input = formatUsd(price.in);
  const output = formatUsd(price.out);
  if (input && output) {
    const vars = { in: input, out: output };
    return {
      text: t("models.price_both", vars),
      short: `${input} / ${output}`,
      title: t("models.price_tip_both", vars),
    };
  }
  if (input) {
    const vars = { in: input };
    return {
      text: t("models.price_in", vars),
      short: t("models.price_in_short", vars),
      title: t("models.price_tip_in", vars),
    };
  }
  if (output) {
    const vars = { out: output };
    return {
      text: t("models.price_out", vars),
      short: t("models.price_out_short", vars),
      title: t("models.price_tip_out", vars),
    };
  }
  return null;
}
