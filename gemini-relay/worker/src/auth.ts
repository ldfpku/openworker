/**
 * Login, roster, and relay-token issuance.
 *
 * v3 replaces v2's "sha256(Gemini API key) -> email" roster with an actual login. Identity
 * now comes from a Cloudflare Access One-time PIN sign-in: the colleague proves they own an
 * allow-listed mailbox, and the relay issues them a token that is only good for this relay.
 *
 * The token answers "who is this", nothing else. It is NOT a Gemini credential: everyone
 * pays with their own Google key, which travels separately in `x-goog-api-key` and is
 * forwarded upstream untouched (index.ts). Splitting the two is what makes the counting
 * gate possible — the relay can attribute and cap usage by verified mailbox while never
 * holding a credential that could bill anybody.
 *
 * The browser leg and the app leg are joined by OAuth 2.0's authorization-code + PKCE shape,
 * which is also what RFC 8252 prescribes for native apps:
 *
 *   1. app  -> POST /auth/session {callback, challenge}      (public)  -> {sid, login_url}
 *   2. app  -> opens the system browser at /login/<sid>      (Access-protected)
 *      Access does the One-time PIN dance and only then invokes this Worker.
 *   3. edge -> 302 <callback>?code=...&state=<sid>           (loopback, so it stays on-device)
 *   4. app  -> POST /auth/token {code, verifier}             (public)  -> {token, identity}
 *
 * Why the parameters travel in a server-side session keyed by an opaque `sid` in the PATH
 * rather than as query parameters: Access excludes query strings from application path
 * matching and may strip or rewrite them across the login redirect, so nothing load-bearing
 * can ride the query string through the Access gate.
 *
 * Why PKCE when the callback is already loopback-only: any local process can race to bind
 * the loopback port. Binding the code to sha256(verifier) means only the app instance that
 * started the login can redeem it.
 */

import { AccessError, verifyAccessJwt } from "./access";
import { FAVICON_DATA_URI, LOGO_DARK_DATA_URI, LOGO_LIGHT_DATA_URI } from "./brand";
import type { Env } from "./env";
import { type Limits, limitsFor, snapshot } from "./quota";

/** Relay tokens are prefixed so they are never mistaken for a Google `AIza...` key — in a
 *  log, in a support screenshot, or by the upstream-injection guard in `index.ts`. */
export const TOKEN_PREFIX = "owr_";

const TOKEN_TTL_SECONDS = 30 * 24 * 3600; // 30 days, then the app prompts a fresh login
const SESSION_TTL_SECONDS = 600; // browser leg: 10 min to finish the OTP
const CODE_TTL_SECONDS = 300; // loopback leg: 5 min to redeem, single use

// Roster reads sit on the hot path of every relayed request, so they are edge-cached. The
// cost is the revocation lag: removing someone takes up to 5 minutes to bite everywhere.
const ROSTER_CACHE_TTL = 300;

// ---------------------------------------------------------------------------------------
// Small crypto/encoding helpers
// ---------------------------------------------------------------------------------------

export async function sha256Hex(input: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(input));
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

function b64url(bytes: Uint8Array): string {
  let bin = "";
  for (const b of bytes) bin += String.fromCharCode(b);
  return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

async function sha256B64url(input: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(input));
  return b64url(new Uint8Array(digest));
}

function randomB64url(byteLength: number): string {
  return b64url(crypto.getRandomValues(new Uint8Array(byteLength)));
}

/** Length-independent equality for secret comparison — no early exit on the first mismatch. */
function timingSafeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

// ---------------------------------------------------------------------------------------
// Roster
// ---------------------------------------------------------------------------------------

export interface RosterUser {
  email: string;
  name: string;
  dept: string;
  /** `admin` | `gm` | `lead` | `staff`. Informational today — reporting and audit only. */
  role: string;
  /** Resolved ceilings: this person's overrides on top of the house defaults (quota.ts). */
  limits: Limits;
}

/**
 * The allow list, as the relay sees it. The Access policy is the gate on the *login* page;
 * this KV roster is the gate on the *relay* and is what `roster.ps1` maintains. Keeping the
 * relay-side check means deleting one KV entry cuts someone off within `ROSTER_CACHE_TTL`
 * even if the Access policy has not been updated yet.
 */
export async function lookupUser(env: Env, email: string): Promise<RosterUser | null> {
  const normalized = email.trim().toLowerCase();
  if (!normalized) return null;
  const raw = await env.ROSTER.get("u:" + normalized, { cacheTtl: ROSTER_CACHE_TTL });
  if (!raw) return null;
  try {
    const rec = JSON.parse(raw) as Record<string, unknown>;
    return {
      email: normalized,
      name: typeof rec.name === "string" ? rec.name : "",
      dept: typeof rec.dept === "string" ? rec.dept : "",
      role: typeof rec.role === "string" ? rec.role : "staff",
      limits: limitsFor(env, rec),
    };
  } catch {
    // A hand-edited entry that isn't JSON still means "this person is allowed" — the value
    // predates the JSON shape or someone used the dashboard. Admit them, unnamed, on the
    // house limits.
    return { email: normalized, name: "", dept: "", role: "staff", limits: limitsFor(env, {}) };
  }
}

// ---------------------------------------------------------------------------------------
// Relay tokens
// ---------------------------------------------------------------------------------------

/**
 * Where the relay token rides: `Authorization: Bearer`, and nowhere else.
 *
 * It used to also be read out of `x-goog-api-key`, because the app stored it in the slot the
 * google-genai SDK calls `api_key`. That slot now belongs to the caller's own Google key, so
 * reading a token from it would be ambiguous at best. The app sets this header explicitly
 * (`HttpOptions.headers`); `index.ts` strips it before the request goes upstream, so Google
 * never sees it.
 */
export function extractRelayToken(request: Request): string {
  const authz = request.headers.get("authorization") || "";
  if (!/^bearer\s+/i.test(authz)) return "";
  return authz.replace(/^bearer\s+/i, "").trim();
}

/** Token -> the person it was issued to, or null if unknown, expired, or since revoked. */
export async function resolveRelayToken(env: Env, token: string): Promise<RosterUser | null> {
  if (!token.startsWith(TOKEN_PREFIX)) return null;
  const email = await env.ROSTER.get("t:" + (await sha256Hex(token)), {
    cacheTtl: ROSTER_CACHE_TTL,
  });
  if (!email) return null;
  // Second hop on purpose: the token record only stores the email, so removing the roster
  // entry revokes every token that person holds without having to enumerate them.
  return lookupUser(env, email);
}

// ---------------------------------------------------------------------------------------
// Audit trail
// ---------------------------------------------------------------------------------------

async function audit(
  env: Env,
  email: string,
  event: string,
  detail = "",
  country = ""
): Promise<void> {
  try {
    await env.USAGE_DB.prepare(
      "INSERT INTO auth_events (ts, email, event, detail, country) VALUES (?, ?, ?, ?, ?)"
    )
      .bind(new Date().toISOString(), email, event, detail, country)
      .run();
  } catch (err) {
    // Same rule as the usage ledger: bookkeeping never breaks the response.
    console.error("gemini-relay: auth audit insert failed:", err);
  }
}

// ---------------------------------------------------------------------------------------
// Browser-facing pages (only errors are ever seen — success is a 302 to the loopback)
// ---------------------------------------------------------------------------------------

const HTML_ESCAPES: Record<string, string> = {
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;",
  "'": "&#39;",
};

function escapeHtml(text: string): string {
  return text.replace(/[&<>"']/g, (c) => HTML_ESCAPES[c]);
}

function page(title: string, detail: string, status: number): Response {
  const body =
    "<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'>" +
    "<meta name='viewport' content='width=device-width,initial-scale=1'>" +
    "<link rel='icon' type='image/webp' href='" + FAVICON_DATA_URI + "'>" +
    "<title>" + escapeHtml(title) + " — SMJAR</title><style>" +
    // Brand palette from surfaces/gui/src/brand/README.md (品牌绿 / 浅绿 / 墨黑).
    ":root{--paper:#f6f5f2;--panel:#fff;--line:#e4e2dc;--ink:#111214;--muted:#6f6e68;--accent:#1F7A3C}" +
    "@media(prefers-color-scheme:dark){:root{--paper:#191918;--panel:#232322;--line:#373633;" +
    "--ink:#e8e6e1;--muted:#9d9b94;--accent:#58B96C}}" +
    "body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;" +
    "background:var(--paper);color:var(--ink);padding:24px;" +
    "font:14px/1.7 -apple-system,BlinkMacSystemFont,'Segoe UI','Microsoft YaHei',sans-serif}" +
    ".card{background:var(--panel);border:1px solid var(--line);border-radius:16px;" +
    "padding:32px;max-width:380px;width:100%;box-sizing:border-box;" +
    "border-top:3px solid var(--accent);box-shadow:0 10px 30px rgba(0,0,0,.06)}" +
    ".mark{margin-bottom:20px}" +
    ".mark img{height:26px;width:auto}" +
    // Both variants ship in the DOM and CSS picks one. A <picture> with a media source
    // only re-evaluates on load, so flipping the OS theme with the page already open left
    // the white-text wordmark on a now-white card — invisible.
    ".mark .dk{display:none}" +
    "@media(prefers-color-scheme:dark){.mark .lt{display:none}.mark .dk{display:block}}" +
    "h1{font-size:17px;font-weight:650;margin:0 0 8px}" +
    "p{font-size:13px;color:var(--muted);margin:0}" +
    "</style></head><body><div class='card'>" +
    // Inline data URIs, not /brand/... URLs: the page has to render even when whatever went
    // wrong is exactly the thing that would keep a second request from succeeding.
    "<div class='mark'>" +
    "<img class='lt' src='" + LOGO_LIGHT_DATA_URI + "' alt='SMJAR'>" +
    "<img class='dk' src='" + LOGO_DARK_DATA_URI + "' alt=''>" +
    "</div>" +
    "<h1>" + escapeHtml(title) + "</h1><p>" + escapeHtml(detail) + "</p></div></body></html>";
  return new Response(body, {
    status,
    headers: { "content-type": "text/html; charset=utf-8", "cache-control": "no-store" },
  });
}

function json(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" },
  });
}

// ---------------------------------------------------------------------------------------
// Callback validation
// ---------------------------------------------------------------------------------------

const CALLBACK_PATH = "/relay/callback";
const LOOPBACK_HOSTS = new Set(["127.0.0.1", "localhost", "[::1]"]);

/**
 * Only ever redirect to the OpenWorker sidecar on this machine. The port is whatever the
 * packaged app happened to bind (it picks a free one at startup), which is why the host is
 * pinned but the port is not — RFC 8252 §7.3. Anything else would make the relay an open
 * redirector that hands out authorization codes.
 */
function validateCallback(raw: string): string | null {
  let parsed: URL;
  try {
    parsed = new URL(raw);
  } catch {
    return null;
  }
  if (parsed.protocol !== "http:") return null;
  if (!LOOPBACK_HOSTS.has(parsed.hostname)) return null;
  if (parsed.pathname !== CALLBACK_PATH) return null;
  if (parsed.search || parsed.hash || parsed.username || parsed.password) return null;
  return parsed.origin + CALLBACK_PATH;
}

// PKCE S256 challenge: base64url of a SHA-256 digest, so exactly 43 unpadded characters.
const CHALLENGE_RE = /^[A-Za-z0-9_-]{43}$/;

// ---------------------------------------------------------------------------------------
// Routes
// ---------------------------------------------------------------------------------------

/**
 * Handle the login surface. Returns `null` when the path belongs to someone else, so
 * `index.ts` can fall through to the relay proxy.
 */
export async function handleAuthRoutes(
  request: Request,
  env: Env,
  url: URL
): Promise<Response | null> {
  const path = url.pathname;

  if (path === "/auth/session" && request.method === "POST") return startSession(request, env);
  if (path === "/auth/token" && request.method === "POST") return redeemCode(request, env);
  if (path === "/auth/whoami" && request.method === "GET") return whoami(request, env);
  if (path === "/auth/logout" && request.method === "POST") return logout(request, env);
  if (path === "/login" || path.startsWith("/login/")) return completeLogin(request, env, url);
  return null;
}

/** Step 1 (public): the app reserves a login session and gets the URL to open. */
async function startSession(request: Request, env: Env): Promise<Response> {
  let body: { callback?: unknown; challenge?: unknown };
  try {
    body = (await request.json()) as typeof body;
  } catch {
    return json({ error: "invalid json" }, 400);
  }

  const callback = validateCallback(typeof body.callback === "string" ? body.callback : "");
  if (!callback) {
    return json({ error: "callback must be http://127.0.0.1:<port>" + CALLBACK_PATH }, 400);
  }
  const challenge = typeof body.challenge === "string" ? body.challenge : "";
  if (!CHALLENGE_RE.test(challenge)) {
    return json({ error: "challenge must be a base64url SHA-256 digest (PKCE S256)" }, 400);
  }

  const sid = randomB64url(32);
  await env.ROSTER.put("s:" + (await sha256Hex(sid)), JSON.stringify({ callback, challenge }), {
    expirationTtl: SESSION_TTL_SECONDS,
  });

  const origin = new URL(request.url).origin;
  return json({ sid, login_url: origin + "/login/" + sid, expires_in: SESSION_TTL_SECONDS });
}

/** Step 2 (behind Access): the OTP has succeeded — mint a code and bounce to the loopback. */
async function completeLogin(request: Request, env: Env, url: URL): Promise<Response> {
  const sid = url.pathname.startsWith("/login/") ? url.pathname.slice("/login/".length) : "";
  if (!sid) {
    return page(
      "请从 OpenWorker 里发起登录",
      "这个页面不能直接打开。回到 OpenWorker，在「设置 ▸ 模型」里点「登录」，会自动打开带会话的登录链接。",
      400
    );
  }

  let identity;
  try {
    identity = await verifyAccessJwt(request, env.ACCESS_TEAM_DOMAIN, env.ACCESS_AUD);
  } catch (err) {
    const reason = err instanceof AccessError ? err.message : String(err);
    console.error("gemini-relay: Access verification failed:", reason);
    return page(
      "身份校验没通过",
      "没有拿到有效的 Cloudflare Access 登录凭证。请关掉这个标签页，回 OpenWorker 重新登录一次。",
      403
    );
  }

  const sessionKey = "s:" + (await sha256Hex(sid));
  const rawSession = await env.ROSTER.get(sessionKey);
  if (!rawSession) {
    return page(
      "登录会话已过期",
      "从发起登录到收到验证码超过了 10 分钟，或者这个链接已经用过一次。回 OpenWorker 重新点一次「登录」。",
      400
    );
  }
  const session = JSON.parse(rawSession) as { callback: string; challenge: string };
  // One shot per session: consume it before doing anything else so a re-opened tab or a
  // mail scanner prefetching the link can't mint a second code.
  await env.ROSTER.delete(sessionKey);

  const user = await lookupUser(env, identity.email);
  if (!user) {
    await audit(env, identity.email, "login-denied", "not in roster", identity.country);
    return page(
      "这个邮箱不在允许名单里",
      identity.email +
        " 通过了邮箱验证，但还没有被加进 OpenWorker 中转的名单。请联系管理员登记后再试。",
      403
    );
  }

  const code = randomB64url(32);
  await env.ROSTER.put(
    "c:" + (await sha256Hex(code)),
    JSON.stringify({ email: user.email, challenge: session.challenge }),
    { expirationTtl: CODE_TTL_SECONDS }
  );
  await audit(env, user.email, "login-ok", "", identity.country);

  const target = new URL(session.callback);
  target.searchParams.set("code", code);
  target.searchParams.set("state", sid);
  return Response.redirect(target.toString(), 302);
}

/** Step 3 (public): the app redeems its one-time code for a relay token. */
async function redeemCode(request: Request, env: Env): Promise<Response> {
  let body: { code?: unknown; verifier?: unknown };
  try {
    body = (await request.json()) as typeof body;
  } catch {
    return json({ error: "invalid json" }, 400);
  }
  const code = typeof body.code === "string" ? body.code : "";
  const verifier = typeof body.verifier === "string" ? body.verifier : "";
  if (!code || !verifier) return json({ error: "code and verifier are required" }, 400);

  const codeKey = "c:" + (await sha256Hex(code));
  const rawCode = await env.ROSTER.get(codeKey);
  if (!rawCode) return json({ error: "code is unknown, already used, or expired" }, 400);
  // Single use, whatever happens next.
  await env.ROSTER.delete(codeKey);

  const record = JSON.parse(rawCode) as { email: string; challenge: string };
  if (!timingSafeEqual(await sha256B64url(verifier), record.challenge)) {
    await audit(env, record.email, "token-denied", "pkce mismatch");
    return json({ error: "verifier does not match the challenge" }, 400);
  }

  // Re-read the roster: the code is valid for 5 minutes and someone could have been
  // removed inside that window.
  const user = await lookupUser(env, record.email);
  if (!user) {
    await audit(env, record.email, "token-denied", "not in roster");
    return json({ error: "not in roster" }, 403);
  }

  const token = TOKEN_PREFIX + randomB64url(32);
  await env.ROSTER.put("t:" + (await sha256Hex(token)), user.email, {
    expirationTtl: TOKEN_TTL_SECONDS,
  });
  await audit(env, user.email, "token-issued");

  return json({
    token,
    email: user.email,
    name: user.name,
    dept: user.dept,
    role: user.role,
    expires_in: TOKEN_TTL_SECONDS,
    expires_at: new Date(Date.now() + TOKEN_TTL_SECONDS * 1000).toISOString(),
  });
}

/**
 * Who does this token belong to — used by the app to render the signed-in state.
 *
 * Also returns today's counters against today's ceilings. People should be able to see the
 * gate before they hit it; a 429 that arrives with no warning reads as "the relay is broken".
 */
async function whoami(request: Request, env: Env): Promise<Response> {
  const user = await resolveRelayToken(env, extractRelayToken(request));
  if (!user) return json({ error: "not signed in" }, 401);
  return json({
    email: user.email,
    name: user.name,
    dept: user.dept,
    role: user.role,
    quota: await snapshot(env, user.email, user.limits, Date.now()),
  });
}

/** Drop one token. Other devices the same person signed in on keep working. */
async function logout(request: Request, env: Env): Promise<Response> {
  const token = extractRelayToken(request);
  if (token.startsWith(TOKEN_PREFIX)) {
    const key = "t:" + (await sha256Hex(token));
    const email = await env.ROSTER.get(key);
    await env.ROSTER.delete(key);
    if (email) await audit(env, email, "logout");
  }
  // Idempotent by design: signing out an already-dead token is a success, not an error.
  return json({ ok: true });
}
