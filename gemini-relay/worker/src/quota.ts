/**
 * Per-person request and token limits — the counting gate.
 *
 * Everyone now pays with their own Gemini key (index.ts forwards it untouched), so this is
 * not about protecting a shared wallet. It is about the two things a relay is uniquely
 * placed to do: stop a runaway agent loop before it has burned a colleague's quota for the
 * day, and give the administrator one dial per person that does not require touching
 * anybody's Google account.
 *
 * Counters live in D1 rather than KV because KV has no atomic increment and its writes are
 * eventually consistent across colos — two requests from different edges would both read
 * the same stale count and each write "1". D1 has a single primary, so `INSERT ... ON
 * CONFLICT DO UPDATE SET requests = requests + 1` is actually a counter.
 *
 * Known imprecision, by design: a request is counted when it is admitted, not when it
 * finishes, and its TOKENS are only added once the response body has been parsed. So a pile
 * of long streaming requests started in the same second can all pass the gate before any of
 * them has been counted, and the token ceiling always trips one request late. Both are
 * acceptable for a ceiling whose job is "notice the loop", not "meter the cent".
 */

import type { Env } from "./env";

/**
 * One set of ceilings. The three sentinels are shared by all of them:
 *   -1  unlimited (skips the D1 read entirely)
 *    0  suspended — every request refused, without removing anyone from the roster
 *   >0  the actual ceiling
 */
export interface Limits {
  /** Requests per clock minute. Catches a runaway tool loop within seconds. */
  rpm: number;
  /** Requests per day. */
  rpd: number;
  /** Total tokens (prompt + output, as the upstream reports them) per day. */
  tpd: number;
}

// Used when neither the roster entry nor the Worker vars say otherwise. Sized for a person
// driving an agent by hand: one agentic turn with tool calls is easily 10-20 requests, so
// the per-minute ceiling has to sit well above "one message". A loop that has stopped asking
// permission does hundreds a minute and trips instantly.
const FALLBACK: Limits = { rpm: 30, rpd: 1200, tpd: 5_000_000 };

const UNLIMITED = -1;

/** Asia/Shanghai. Fixed offset — China has had no DST since 1991 — so a plain millisecond
 *  shift is exact, and the "day" in "requests per day" is the workday people actually have. */
const TZ_OFFSET_MS = 8 * 3600_000;

const PRUNE_AFTER_DAYS = 3;

// ---------------------------------------------------------------------------------------
// Limit resolution
// ---------------------------------------------------------------------------------------

/** A stored/configured limit → a number, or `fallback` when absent or unparseable. */
function parseLimit(raw: unknown, fallback: number): number {
  const n = typeof raw === "number" ? raw : typeof raw === "string" ? Number(raw.trim()) : NaN;
  if (!Number.isFinite(n)) return fallback;
  const i = Math.trunc(n);
  return i < 0 ? UNLIMITED : i;
}

/**
 * Ceilings for one person: their roster entry wins, the Worker vars are the house default.
 * Per-person overrides exist so the two administrators and the general managers are not
 * throttled by a number chosen for everyone else.
 */
export function limitsFor(env: Env, rec: Record<string, unknown>): Limits {
  return {
    rpm: parseLimit(rec.rpm, parseLimit(env.QUOTA_RPM, FALLBACK.rpm)),
    rpd: parseLimit(rec.rpd, parseLimit(env.QUOTA_RPD, FALLBACK.rpd)),
    tpd: parseLimit(rec.tpd, parseLimit(env.QUOTA_TPD, FALLBACK.tpd)),
  };
}

/** True when this person can never be gated, so the hot path can skip D1 altogether. */
export function unlimited(limits: Limits): boolean {
  return limits.rpm === UNLIMITED && limits.rpd === UNLIMITED && limits.tpd === UNLIMITED;
}

// ---------------------------------------------------------------------------------------
// Buckets
// ---------------------------------------------------------------------------------------

interface Buckets {
  minute: string;
  day: string;
}

/** The two counter rows this instant falls into. The `m|` / `d|` prefixes keep them apart in
 *  one table, and both sort chronologically, which is what the pruning DELETE relies on. */
function bucketsAt(now: number): Buckets {
  const local = new Date(now + TZ_OFFSET_MS).toISOString();
  return { minute: "m|" + local.slice(0, 16), day: "d|" + local.slice(0, 10) };
}

/** Seconds until the minute bucket rolls over (whole-minute offset, so TZ is irrelevant). */
function toNextMinute(now: number): number {
  return Math.max(1, 60 - Math.floor((now / 1000) % 60));
}

/** Seconds until local midnight — when the daily buckets reset. */
function toNextDay(now: number): number {
  const intoDay = (now + TZ_OFFSET_MS) % 86_400_000;
  return Math.max(1, Math.ceil((86_400_000 - intoDay) / 1000));
}

// ---------------------------------------------------------------------------------------
// Reads
// ---------------------------------------------------------------------------------------

export interface Counters {
  minuteRequests: number;
  dayRequests: number;
  dayTokens: number;
}

function zero(): Counters {
  return { minuteRequests: 0, dayRequests: 0, dayTokens: 0 };
}

async function readCounters(env: Env, email: string, at: Buckets): Promise<Counters> {
  const out = zero();
  try {
    const rows = await env.USAGE_DB.prepare(
      "SELECT bucket, requests, tokens FROM quota WHERE email = ? AND bucket IN (?, ?)"
    )
      .bind(email, at.minute, at.day)
      .all<{ bucket: string; requests: number; tokens: number }>();
    for (const row of rows.results || []) {
      if (row.bucket === at.minute) {
        out.minuteRequests = row.requests || 0;
      } else if (row.bucket === at.day) {
        out.dayRequests = row.requests || 0;
        out.dayTokens = row.tokens || 0;
      }
    }
  } catch (err) {
    // Fail OPEN. This gate is governance, not security — the roster is what keeps strangers
    // out. Turning a D1 blip into a company-wide outage would be the worse failure.
    console.error("gemini-relay: quota read failed (allowing):", err);
  }
  return out;
}

// ---------------------------------------------------------------------------------------
// The gate
// ---------------------------------------------------------------------------------------

export type QuotaScope = "suspended" | "rpm" | "rpd" | "tpd";

export interface QuotaVerdict {
  ok: boolean;
  /** Which ceiling refused, when `ok` is false. */
  scope?: QuotaScope;
  limit?: number;
  used?: number;
  /** Seconds until the refusing bucket resets — becomes the `Retry-After` header. */
  retryAfter?: number;
}

export async function checkQuota(
  env: Env,
  email: string,
  limits: Limits,
  now: number
): Promise<QuotaVerdict> {
  if (unlimited(limits)) return { ok: true };
  // A zero is an explicit suspension, and it should not cost a database round trip.
  if (limits.rpm === 0 || limits.rpd === 0 || limits.tpd === 0) {
    return { ok: false, scope: "suspended", limit: 0, used: 0, retryAfter: toNextDay(now) };
  }

  const counters = await readCounters(env, email, bucketsAt(now));

  if (limits.rpm > 0 && counters.minuteRequests >= limits.rpm) {
    return {
      ok: false,
      scope: "rpm",
      limit: limits.rpm,
      used: counters.minuteRequests,
      retryAfter: toNextMinute(now),
    };
  }
  if (limits.rpd > 0 && counters.dayRequests >= limits.rpd) {
    return {
      ok: false,
      scope: "rpd",
      limit: limits.rpd,
      used: counters.dayRequests,
      retryAfter: toNextDay(now),
    };
  }
  if (limits.tpd > 0 && counters.dayTokens >= limits.tpd) {
    return {
      ok: false,
      scope: "tpd",
      limit: limits.tpd,
      used: counters.dayTokens,
      retryAfter: toNextDay(now),
    };
  }
  return { ok: true };
}

/** What the app shows in its sign-in card: today's usage against today's ceilings. */
export async function snapshot(
  env: Env,
  email: string,
  limits: Limits,
  now: number
): Promise<{ limits: Limits; used: Counters; resets_in: number }> {
  const used = unlimited(limits) ? zero() : await readCounters(env, email, bucketsAt(now));
  return { limits, used, resets_in: toNextDay(now) };
}

// ---------------------------------------------------------------------------------------
// Writes — returned as statements so callers can fold them into one D1 batch
// ---------------------------------------------------------------------------------------

const UPSERT = `INSERT INTO quota (email, bucket, requests, tokens, updated) VALUES (?, ?, ?, ?, ?)
   ON CONFLICT(email, bucket) DO UPDATE SET
     requests = requests + excluded.requests,
     tokens   = tokens   + excluded.tokens,
     updated  = excluded.updated`;

function upserts(
  env: Env,
  email: string,
  now: number,
  requests: number,
  tokens: number
): D1PreparedStatement[] {
  const at = bucketsAt(now);
  const stamp = new Date(now).toISOString();
  const stmt = env.USAGE_DB.prepare(UPSERT);
  return [
    stmt.bind(email, at.minute, requests, 0, stamp), // minute rows only ever gate requests
    stmt.bind(email, at.day, requests, tokens, stamp),
  ];
}

/** Count one admitted request. Runs off the critical path, but before the response body is
 *  read — a request that is still streaming already occupies its slot. */
export function countRequest(
  env: Env,
  email: string,
  limits: Limits,
  now: number
): D1PreparedStatement[] {
  if (unlimited(limits)) return [];
  return upserts(env, email, now, 1, 0);
}

/** Add the tokens a finished request actually consumed. The request itself was counted at
 *  admission, so this adds zero requests. */
export function countTokens(
  env: Env,
  email: string,
  limits: Limits,
  now: number,
  tokens: number
): D1PreparedStatement[] {
  if (unlimited(limits) || tokens <= 0) return [];
  return upserts(env, email, now, 0, tokens);
}

/** Drop buckets nobody can still be inside. Called from the Worker's cron trigger — without
 *  it the minute rows alone would add up to 1,440 per person per day, forever. */
export async function pruneQuota(env: Env, now: number): Promise<number> {
  const cutoff = new Date(now - PRUNE_AFTER_DAYS * 86_400_000).toISOString();
  const result = await env.USAGE_DB.prepare("DELETE FROM quota WHERE updated < ?")
    .bind(cutoff)
    .run();
  return result.meta?.changes ?? 0;
}
