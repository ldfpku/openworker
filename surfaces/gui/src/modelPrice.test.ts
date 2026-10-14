// The model lists' price hint. Prices come from one place only — the company gateway's
// guard, via /v1/settings `model_prices` — and this module only formats them: whatever is
// missing or malformed must come out as "nothing", never as a made-up or zeroed price.
import { createInstance } from "i18next";
import { beforeAll, describe, expect, it } from "vitest";
import en from "./locales/en.json";
import zh from "./locales/zh.json";
import { formatUsd, isRestrictedTier, priceHint, type ModelPrice } from "./modelPrice";

type T = (key: string, vars?: Record<string, string>) => string;

// The real locale files, resolved the way the app resolves them (dotted keys, no escaping).
async function translator(lng: "en" | "zh"): Promise<T> {
  const instance = createInstance();
  await instance.init({
    resources: { en: { translation: en }, zh: { translation: zh } },
    lng,
    fallbackLng: false,
    interpolation: { escapeValue: false },
  });
  return (key, vars) => instance.t(key, vars ?? {});
}

let tEn: T;
let tZh: T;
beforeAll(async () => {
  tEn = await translator("en");
  tZh = await translator("zh");
});

describe("formatUsd", () => {
  it.each([
    [3, "$3"],
    [15, "$15"],
    [15.0, "$15"],
    [2.5, "$2.5"],
    [1.25, "$1.25"],
    [18.75, "$18.75"],
    [1.125, "$1.125"],
    [75, "$75"],
    [100, "$100"],
    [1050, "$1050"],
    [0.15, "$0.15"],
    [0.6, "$0.6"],
    [0.051, "$0.051"],
    [0.0375, "$0.0375"],
    [0.075, "$0.075"],
    [0.1 + 0.2, "$0.3"], // float noise is not a price digit
    [0, "$0"],
  ])("formats %s as %s", (value, expected) => {
    expect(formatUsd(value)).toBe(expected);
  });

  it("keeps four significant digits below a dollar and three decimals above", () => {
    expect(formatUsd(0.123456)).toBe("$0.1235");
    expect(formatUsd(0.00051234)).toBe("$0.0005123");
    expect(formatUsd(12.34567)).toBe("$12.346");
    expect(formatUsd(0.99996)).toBe("$1");
  });

  it("never prints exponent notation or rounds a real price down to $0", () => {
    expect(formatUsd(0.0001)).toBe("$0.0001");
    expect(formatUsd(0.0000005)).toBe("<$0.0001");
    expect(formatUsd(5e-7)).not.toContain("e");
  });

  it.each([
    ["a missing value", undefined],
    ["null", null],
    ["a numeric string", "3"],
    ["a negative", -1],
    ["NaN", Number.NaN],
    ["Infinity", Number.POSITIVE_INFINITY],
    ["a boolean", true],
    ["an object", { usd: 3 }],
  ])("returns null for %s", (_label, value) => {
    expect(formatUsd(value)).toBeNull();
  });
});

describe("priceHint", () => {
  it("shows input / output per million tokens, in both languages", () => {
    const price = { in: 3, out: 15 };
    expect(priceHint(price, tEn)).toEqual({
      text: "$3 / $15 per 1M tokens",
      short: "$3 / $15",
      title: "Input $3 · output $15 (USD per 1M tokens)",
    });
    expect(priceHint(price, tZh)).toEqual({
      text: "$3 / $15 每百万 token",
      short: "$3 / $15",
      title: "输入 $3 · 输出 $15（美元 / 百万 token）",
    });
  });

  it("keeps small prices readable", () => {
    expect(priceHint({ in: 0.051, out: 0.15 }, tZh)?.text).toBe("$0.051 / $0.15 每百万 token");
    expect(priceHint({ in: 0.051, out: 0.15 }, tEn)?.short).toBe("$0.051 / $0.15");
    expect(priceHint({ in: 3.0, out: 15.0 }, tEn)?.text).toBe("$3 / $15 per 1M tokens");
  });

  it("names the one side that is known instead of leaving a dangling slash", () => {
    expect(priceHint({ in: 3 }, tEn)).toEqual({
      text: "Input $3 per 1M tokens",
      short: "Input $3",
      title: "Input $3 (USD per 1M tokens)",
    });
    expect(priceHint({ in: 3, out: null }, tZh)).toEqual({
      text: "输入 $3 每百万 token",
      short: "输入 $3",
      title: "输入 $3（美元 / 百万 token）",
    });
    expect(priceHint({ out: 15 }, tEn)).toEqual({
      text: "Output $15 per 1M tokens",
      short: "Output $15",
      title: "Output $15 (USD per 1M tokens)",
    });
    expect(priceHint({ in: null, out: 15 }, tZh)).toEqual({
      text: "输出 $15 每百万 token",
      short: "输出 $15",
      title: "输出 $15（美元 / 百万 token）",
    });
  });

  it("drops a malformed side rather than showing it", () => {
    const junk = { in: "3", out: 15 } as unknown as ModelPrice;
    expect(priceHint(junk, tEn)?.text).toBe("Output $15 per 1M tokens");
    expect(priceHint({ in: -3, out: Number.NaN }, tEn)).toBeNull();
  });

  it("shows a zero price as a price", () => {
    expect(priceHint({ in: 0, out: 0 }, tEn)?.short).toBe("$0 / $0");
  });

  it.each([
    ["no entry", undefined],
    ["null", null],
    ["an empty entry", {}],
    ["both sides null", { in: null, out: null }],
    ["a bare number", 3 as unknown as ModelPrice],
    ["a string", "$3 / $15" as unknown as ModelPrice],
  ])("returns null for %s — nothing is ever invented", (_label, price) => {
    expect(priceHint(price, tEn)).toBeNull();
    expect(priceHint(price, tZh)).toBeNull();
  });
});

describe("isRestrictedTier", () => {
  it("is true only for the guard's \"limited\"", () => {
    expect(isRestrictedTier("limited")).toBe(true);
    for (const other of ["all", "LIMITED", "", undefined, null, true, 1]) {
      expect(isRestrictedTier(other)).toBe(false);
    }
  });
});
