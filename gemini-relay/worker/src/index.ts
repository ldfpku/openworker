/**
 * Gemini API relay v3 — reverse proxy + login-backed identity + per-person quota.
 *
 * openworker's google-genai SDK points at this host; every /v1beta/... request is forwarded
 * verbatim to generativelanguage.googleapis.com with the response body streamed back
 * untouched (SSE included).
 *
 * Two separate credentials ride every request, and keeping them separate is the whole
 * design:
 *
 *   Authorization: Bearer owr_...   who you are.   Minted by this Worker after a Cloudflare
 *                                   Access One-time PIN login (auth.ts). Consumed here and
 *                                   stripped — Google never sees it.
 *   x-goog-api-key: AIza...         who pays.      The caller's own Gemini key — one per
 *                                   person, issued by the administrator from the company
 *                                   Google account and named after them. Forwarded
 *                                   untouched; the relay stores none of them and holds no
 *                                   key of its own.
 *
 * Identity being Worker-verified rather than client-claimed is what makes the counting gate
 * (quota.ts) mean anything: limits are keyed on a mailbox somebody proved they own, so
 * nobody can reset their own counter by rotating a key.
 *
 * Every terminal outcome (401 no-token, 403 revoked, 400 no key, 429 over quota, proxied)
 * is recorded to D1 via ctx.waitUntil so accounting never delays or risks the response
 * already sent to the client.
 */

import {
  extractRelayToken,
  handleAuthRoutes,
  resolveRelayToken,
  sha256Hex,
  TOKEN_PREFIX,
} from "./auth";
import { handleBrandRoutes } from "./brand";
import type { Env } from "./env";
import {
  checkQuota,
  countRequest,
  countTokens,
  type Limits,
  pruneQuota,
  type QuotaVerdict,
} from "./quota";

const UPSTREAM = "https://generativelanguage.googleapis.com";

// Every Gemini Developer API key starts with this. The key slot attracts OTHER Google
// credentials — a Vertex express "AQ." console token is the live example (owner-hit
// 2026-08-25) — and Google answers those with an English ACCESS_TOKEN_TYPE_UNSUPPORTED
// 401 that reads as "login broken". Kept in sync with gemini_provider.GOOGLE_KEY_PREFIX.
const GOOGLE_KEY_PREFIX = "AIza";

// The google-genai SDK only ever calls /v1beta/... (api_version default); /upload covers the
// Files API in case it is used later. Everything else (scanners, typos) gets a 404.
const ALLOWED_PATH = /^\/(upload\/)?(v1|v1beta|v1alpha)\//;

// Hop-by-hop headers plus everything that would leak client/edge details upstream.
const STRIP_REQUEST_HEADERS = [
  "host",
  // The relay token is ours to consume, not Google's to see. x-goog-api-key is deliberately
  // NOT in this list: it carries the caller's own key and is the one thing that must survive
  // the hop (the fetch handler re-sets it, to normalize the ?key= form into the header).
  "authorization",
  "cookie",
  "connection",
  "keep-alive",
  "transfer-encoding",
  "upgrade",
  "proxy-authorization",
  "te",
  "trailer",
  "x-forwarded-for",
  "x-forwarded-host",
  "x-forwarded-proto",
  "x-real-ip",
  "true-client-ip",
];

// ---------------------------------------------------------------------------------------
// Request classification (drives the `kind`/`model` usage columns)
// ---------------------------------------------------------------------------------------

type Kind = "generate" | "stream" | "embed" | "count" | "models" | "files" | "other";

// Path shapes seen in practice: /v1beta/models/{model}:{method}, /v1beta/models (list),
// /v1beta/files/{id}, /upload/v1beta/files (upload). Anything else falls through to "other"
// with no model — cachedContents, tunedModels, corpora, etc. are rare enough not to special-case.
function classify(pathname: string): { kind: Kind; model: string } {
  if (pathname.startsWith("/upload/") || pathname.includes("/files")) {
    return { kind: "files", model: "" };
  }
  const m = pathname.match(/\/models\/([^/:]+):([^/]+)$/);
  if (m) {
    const model = m[1];
    const method = m[2];
    if (method === "streamGenerateContent") return { kind: "stream", model };
    if (method === "generateContent") return { kind: "generate", model };
    if (method === "embedContent" || method === "batchEmbedContents") return { kind: "embed", model };
    if (method === "countTokens") return { kind: "count", model };
    return { kind: "other", model };
  }
  if (/\/models\/?$/.test(pathname)) return { kind: "models", model: "" };
  return { kind: "other", model: "" };
}

// ---------------------------------------------------------------------------------------
// Usage parsing — never throws past its caller; a parse miss just leaves fields at zero.
// ---------------------------------------------------------------------------------------

interface Usage {
  promptTokens: number;
  outputTokens: number;
  totalTokens: number;
  cachedTokens: number;
  thoughtsTokens: number;
  toolPromptTokens: number;
  modelVersion: string;
  responseId: string;
}

function emptyUsage(): Usage {
  return {
    promptTokens: 0,
    outputTokens: 0,
    totalTokens: 0,
    cachedTokens: 0,
    thoughtsTokens: 0,
    toolPromptTokens: 0,
    modelVersion: "",
    responseId: "",
  };
}

// Gemini's usageMetadata is a per-chunk cumulative snapshot (no [DONE] terminator on the
// stream), so the last object seen — whole-field overwrite, not a merge — is the total.
// countTokens is the one shape with no usageMetadata at all: totalTokens sits at the top level.
function fillFromObject(obj: any, kind: Kind, usage: Usage): void {
  if (typeof obj?.modelVersion === "string") usage.modelVersion = obj.modelVersion;
  if (typeof obj?.responseId === "string") usage.responseId = obj.responseId;
  if (kind === "count") {
    if (typeof obj?.totalTokens === "number") usage.totalTokens = obj.totalTokens;
    return;
  }
  const um = obj?.usageMetadata;
  if (!um || typeof um !== "object") return;
  if (typeof um.promptTokenCount === "number") usage.promptTokens = um.promptTokenCount;
  if (typeof um.candidatesTokenCount === "number") usage.outputTokens = um.candidatesTokenCount;
  if (typeof um.totalTokenCount === "number") usage.totalTokens = um.totalTokenCount;
  if (typeof um.cachedContentTokenCount === "number") usage.cachedTokens = um.cachedContentTokenCount;
  if (typeof um.thoughtsTokenCount === "number") usage.thoughtsTokens = um.thoughtsTokenCount;
  if (typeof um.toolUsePromptTokenCount === "number") usage.toolPromptTokens = um.toolUsePromptTokenCount;
}

// Generic brace-balancer used for tail-extracting a JSON object out of a larger body
// without parsing the whole thing. Skips over string contents so braces inside quoted
// values don't throw the depth count off.
function extractBalancedObject(text: string, fromIndex: number): string | null {
  const start = text.indexOf("{", fromIndex);
  if (start === -1) return null;
  let depth = 0;
  let inString = false;
  let escaped = false;
  for (let i = start; i < text.length; i++) {
    const ch = text[i];
    if (inString) {
      if (escaped) escaped = false;
      else if (ch === "\\") escaped = true;
      else if (ch === '"') inString = false;
      continue;
    }
    if (ch === '"') inString = true;
    else if (ch === "{") depth++;
    else if (ch === "}") {
      depth--;
      if (depth === 0) return text.slice(start, i + 1);
    }
  }
  return null; // unbalanced — truncated body, bail out
}

const MAX_INLINE_PARSE = 1_000_000; // full JSON.parse only below this
const MAX_SSE_EVENT = 4_000_000; // skip parsing a single SSE event beyond this

function processSSEEvent(eventText: string, kind: Kind, usage: Usage): void {
  const dataLines = eventText
    .split("\n")
    .filter((l) => l.startsWith("data:"))
    .map((l) => l.slice(5).trimStart());
  if (dataLines.length === 0) return;
  const payload = dataLines.join("\n");
  if (!payload.includes("usageMetadata") || payload.length > MAX_SSE_EVENT) return;
  try {
    fillFromObject(JSON.parse(payload), kind, usage);
  } catch {
    // malformed/partial event — skip it, keep whatever usage was already captured
  }
}

async function parseSSE(stream: ReadableStream<Uint8Array>, kind: Kind, usage: Usage): Promise<void> {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (value) buffer += decoder.decode(value, { stream: true });
      // SSE allows LF or CRLF line endings — Google's frontends emit CRLF, so a
      // bare "\n\n" search would never split and the whole stream would collapse
      // into one unparseable "event" at the end.
      let sep: RegExpMatchArray | null;
      while ((sep = buffer.match(/\r?\n\r?\n/)) !== null) {
        processSSEEvent(buffer.slice(0, sep.index!), kind, usage);
        buffer = buffer.slice(sep.index! + sep[0].length);
      }
      if (done) {
        buffer += decoder.decode();
        if (buffer.trim()) processSSEEvent(buffer, kind, usage);
        break;
      }
    }
  } finally {
    reader.releaseLock();
  }
}

async function parseNonStream(stream: ReadableStream<Uint8Array>, kind: Kind, usage: Usage): Promise<void> {
  // Always drain fully first — this is the tee()'d branch, and leaving it unread can
  // backpressure-stall the client branch sharing the same underlying stream.
  const text = await new Response(stream).text();
  if (kind === "files" || kind === "models" || text.length === 0) return;

  if (text.length < MAX_INLINE_PARSE) {
    try {
      fillFromObject(JSON.parse(text), kind, usage);
    } catch {
      // non-JSON or malformed body (e.g. an upstream HTML error page) — leave usage at zeros
    }
    return;
  }

  // Large body (inline image/audio bytes in the response, etc.) — a full JSON.parse risks
  // the CPU limit, so tail-extract just the usageMetadata object via brace balancing.
  const idx = text.lastIndexOf("usageMetadata");
  if (idx === -1) return;
  const extracted = extractBalancedObject(text, idx);
  if (!extracted) return;
  try {
    fillFromObject({ usageMetadata: JSON.parse(extracted) }, kind, usage);
  } catch {
    // extraction landed on invalid JSON — skip
  }
}

// ---------------------------------------------------------------------------------------
// D1 write
// ---------------------------------------------------------------------------------------

interface UsageRow {
  email: string;
  name: string;
  dept: string;
  model: string;
  kind: Kind;
  status: number;
  keyHash: string;
  modelVersion: string;
  responseId: string;
  promptTokens: number;
  outputTokens: number;
  totalTokens: number;
  cachedTokens: number;
  thoughtsTokens: number;
  toolPromptTokens: number;
  latencyMs: number;
  durationMs: number;
  error: string;
}

/**
 * One ledger row, plus any quota counter updates that belong with it.
 *
 * `extra` rides the same D1 batch (one implicit transaction) rather than a second round
 * trip: the ledger and the counters should not be able to disagree about whether a request
 * happened.
 */
async function insertUsageRow(
  env: Env,
  row: UsageRow,
  extra: D1PreparedStatement[] = []
): Promise<void> {
  try {
    const statement = env.USAGE_DB.prepare(
      `INSERT INTO usage
        (ts, email, name, dept, model, kind, status, key_hash, model_version, response_id,
         prompt_tokens, output_tokens, total_tokens, cached_tokens, thoughts_tokens,
         tool_prompt_tokens, latency_ms, duration_ms, error)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
    )
      .bind(
        new Date().toISOString(),
        row.email,
        row.name,
        row.dept,
        row.model,
        row.kind,
        row.status,
        row.keyHash,
        row.modelVersion,
        row.responseId,
        row.promptTokens,
        row.outputTokens,
        row.totalTokens,
        row.cachedTokens,
        row.thoughtsTokens,
        row.toolPromptTokens,
        row.latencyMs,
        row.durationMs,
        row.error
      );
    if (extra.length) await env.USAGE_DB.batch([statement, ...extra]);
    else await statement.run();
  } catch (err) {
    // Accounting must never affect a response that has already gone out to the client.
    console.error("gemini-relay: usage insert failed:", err);
  }
}

/** Fire quota counter statements on their own, for the admission-time bump that has no
 *  ledger row to ride along with. Same rule: never let bookkeeping surface to the client. */
async function runCounters(env: Env, statements: D1PreparedStatement[]): Promise<void> {
  if (!statements.length) return;
  try {
    await env.USAGE_DB.batch(statements);
  } catch (err) {
    console.error("gemini-relay: quota counter update failed:", err);
  }
}

async function recordRejected(
  env: Env,
  email: string,
  model: string,
  kind: Kind,
  status: number,
  keyHash: string,
  latencyMs: number,
  error: string,
  // Known only when the rejection happened after the token resolved (e.g. a missing
  // upstream key); for anonymous rejections `email` carries a "(no-token)" placeholder.
  name = "",
  dept = ""
): Promise<void> {
  await insertUsageRow(env, {
    email,
    name,
    dept,
    model,
    kind,
    status,
    keyHash,
    modelVersion: "",
    responseId: "",
    promptTokens: 0,
    outputTokens: 0,
    totalTokens: 0,
    cachedTokens: 0,
    thoughtsTokens: 0,
    toolPromptTokens: 0,
    latencyMs,
    durationMs: latencyMs,
    error,
  });
}

interface RecordMeta {
  email: string;
  name: string;
  dept: string;
  model: string;
  kind: Kind;
  status: number;
  keyHash: string;
  latencyMs: number;
  t0: number;
  /** This person's ceilings — needed to know whether the token counter is worth writing. */
  limits: Limits;
}

/** What the daily token ceiling counts. `totalTokenCount` is the upstream's own total
 *  (prompt + candidates + thoughts + tool use); the sum is only a fallback for shapes that
 *  report the parts but not the total. */
function billableTokens(usage: Usage): number {
  return usage.totalTokens > 0 ? usage.totalTokens : usage.promptTokens + usage.outputTokens;
}

async function recordUsage(
  env: Env,
  body: ReadableStream<Uint8Array>,
  contentType: string,
  meta: RecordMeta
): Promise<void> {
  try {
    const usage = emptyUsage();
    if (contentType.includes("text/event-stream")) {
      await parseSSE(body, meta.kind, usage);
    } else {
      await parseNonStream(body, meta.kind, usage);
    }
    await insertUsageRow(
      env,
      {
        email: meta.email,
        name: meta.name,
        dept: meta.dept,
        model: meta.model,
        kind: meta.kind,
        status: meta.status,
        keyHash: meta.keyHash,
        modelVersion: usage.modelVersion,
        responseId: usage.responseId,
        promptTokens: usage.promptTokens,
        outputTokens: usage.outputTokens,
        totalTokens: usage.totalTokens,
        cachedTokens: usage.cachedTokens,
        thoughtsTokens: usage.thoughtsTokens,
        toolPromptTokens: usage.toolPromptTokens,
        latencyMs: meta.latencyMs,
        durationMs: Date.now() - meta.t0,
        error: "",
      },
      // The request was counted at admission; this is the token half, known only now.
      countTokens(env, meta.email, meta.limits, meta.t0, billableTokens(usage))
    );
  } catch (err) {
    // Stream-level failure (e.g. connection reset mid-body) rather than a per-event parse
    // miss — those are already swallowed inside parseSSE/parseNonStream. Still record the
    // request itself so it isn't silently missing from the ledger; tokens stay at zero.
    console.error("gemini-relay: recordUsage failed:", err);
    await insertUsageRow(env, {
      email: meta.email,
      name: meta.name,
      dept: meta.dept,
      model: meta.model,
      kind: meta.kind,
      status: meta.status,
      keyHash: meta.keyHash,
      modelVersion: "",
      responseId: "",
      promptTokens: 0,
      outputTokens: 0,
      totalTokens: 0,
      cachedTokens: 0,
      thoughtsTokens: 0,
      toolPromptTokens: 0,
      latencyMs: meta.latencyMs,
      durationMs: Date.now() - meta.t0,
      error: "parse-fail",
    });
  }
}

// ---------------------------------------------------------------------------------------
// Refusals the relay generates itself
// ---------------------------------------------------------------------------------------

/**
 * Google's own error envelope, not a plain text body.
 *
 * The client is the google-genai SDK, which parses `{"error": {...}}` and puts `message`
 * into the exception it raises. A bare text body surfaces to the person as a stack trace
 * with no explanation, and these refusals — no key, over quota — are exactly the ones they
 * need to read. Messages are in Chinese and name the relay, so nobody spends an afternoon
 * arguing with Google about a limit Google did not set.
 */
function apiError(
  status: number,
  googleStatus: string,
  message: string,
  extraHeaders: Record<string, string> = {}
): Response {
  return new Response(
    JSON.stringify({ error: { code: status, message, status: googleStatus } }),
    {
      status,
      headers: {
        "content-type": "application/json; charset=utf-8",
        "cache-control": "no-store",
        ...extraHeaders,
      },
    }
  );
}

/**
 * The caller's own Google key. Header first — that is what the SDK sends — falling back to
 * the `?key=` form Google also accepts, so a hand-written curl still works. Either way it
 * leaves here as a header, keeping the credential out of the upstream URL.
 */
function extractUpstreamKey(request: Request, url: URL): string {
  const header = (request.headers.get("x-goog-api-key") || "").trim();
  if (header) return header;
  return (url.searchParams.get("key") || "").trim();
}

function quotaMessage(verdict: QuotaVerdict): string {
  const day = "北京时间次日 00:00 重置";
  switch (verdict.scope) {
    case "suspended":
      return "OpenWorker 中转：你的账号已被管理员暂停（限额为 0），请联系管理员。";
    case "rpm":
      return `OpenWorker 中转：每分钟最多 ${verdict.limit} 次请求，已经用满。${verdict.retryAfter} 秒后自动恢复；如果这是自动循环跑飞了，请先停下来看一眼。`;
    case "rpd":
      return `OpenWorker 中转：今天最多 ${verdict.limit} 次请求，已经用满。${day}；需要更高额度请联系管理员。`;
    default:
      return `OpenWorker 中转：今天最多 ${verdict.limit} tokens，已经用了 ${verdict.used}。${day}；需要更高额度请联系管理员。`;
  }
}

// ---------------------------------------------------------------------------------------

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const t0 = Date.now();
    const url = new URL(request.url);

    if (url.pathname === "/" || url.pathname === "/healthz") {
      return new Response("ok\n", { headers: { "content-type": "text/plain" } });
    }

    // Public brand marks. Cloudflare Access's custom branding wants a logo URL rather than
    // an upload, and this host is the one guaranteed to be reachable from the login page.
    const brandResponse = handleBrandRoutes(url);
    if (brandResponse) return brandResponse;

    // The login surface: /login/... is fronted by Cloudflare Access (One-time PIN), while
    // /auth/... is public and secured by the one-time code + PKCE exchange. Both are handled
    // before ALLOWED_PATH, which only ever describes upstream Gemini paths.
    const authResponse = await handleAuthRoutes(request, env, url);
    if (authResponse) return authResponse;

    if (!ALLOWED_PATH.test(url.pathname)) {
      return new Response("not found\n", { status: 404 });
    }

    const { kind, model } = classify(url.pathname);

    // Identity is Worker-side, not client-claimed: the caller presents a relay token this
    // Worker minted after a verified Access login. Refusing tokenless requests also keeps
    // the relay useless to random scanners without revealing what sits upstream.
    const relayToken = extractRelayToken(request);
    if (!relayToken) {
      const latencyMs = Date.now() - t0;
      ctx.waitUntil(recordRejected(env, "(no-token)", model, kind, 401, "", latencyMs, "no-token"));
      return apiError(
        401,
        "UNAUTHENTICATED",
        "OpenWorker 中转：还没有登录。在「设置 ▸ 模型 ▸ Gemini」里用工作邮箱收验证码登录一次。"
      );
    }

    // Recorded instead of the v2 key hash: same 12-hex shape, so the usage table's key_hash
    // column keeps working as a "which credential was this" discriminator without storing one.
    const tokenHash12 = (await sha256Hex(relayToken)).slice(0, 12);
    const user = await resolveRelayToken(env, relayToken);
    if (!user) {
      const latencyMs = Date.now() - t0;
      ctx.waitUntil(
        recordRejected(env, "(revoked)", model, kind, 403, tokenHash12, latencyMs, "bad-token")
      );
      return apiError(
        403,
        "PERMISSION_DENIED",
        "OpenWorker 中转：登录已失效（过期、被吊销，或已不在允许名单里），请重新登录。"
      );
    }

    // Who pays. Checked after identity so the ledger can attribute the mistake to a person,
    // and so an outsider probing the relay learns nothing about what it wants.
    const upstreamKey = extractUpstreamKey(request, url);
    if (!upstreamKey) {
      const latencyMs = Date.now() - t0;
      ctx.waitUntil(
        recordRejected(
          env, user.email, model, kind, 400, tokenHash12, latencyMs, "no-upstream-key",
          user.name, user.dept
        )
      );
      return apiError(
        400,
        "INVALID_ARGUMENT",
        "OpenWorker 中转：登录成功，但还没有填 Gemini API key。" +
          "找管理员要一把（每人一把、以你的名字命名），填进「设置 ▸ 模型 ▸ Gemini」的 API key 里。"
      );
    }
    if (upstreamKey.startsWith(TOKEN_PREFIX)) {
      // A pre-quota client put the relay token in the api_key slot. Forwarding it would earn
      // an opaque 400 from Google that reads as "your login is broken".
      const latencyMs = Date.now() - t0;
      ctx.waitUntil(
        recordRejected(
          env, user.email, model, kind, 400, tokenHash12, latencyMs, "token-as-key",
          user.name, user.dept
        )
      );
      return apiError(
        400,
        "INVALID_ARGUMENT",
        "OpenWorker 中转：客户端版本过旧——它把登录令牌当成 API key 发了过来。请升级 OpenWorker。"
      );
    }
    if (!upstreamKey.startsWith(GOOGLE_KEY_PREFIX)) {
      // A different Google credential in the key slot. Distinct from the owr_ case above:
      // that is OUR token misplaced by an old client (fix: upgrade), this is the wrong
      // thing copied out of a Google console (fix: issue a real AI Studio key).
      const latencyMs = Date.now() - t0;
      ctx.waitUntil(
        recordRejected(
          env, user.email, model, kind, 400, tokenHash12, latencyMs, "wrong-key-kind",
          user.name, user.dept
        )
      );
      return apiError(
        400,
        "INVALID_ARGUMENT",
        "OpenWorker 中转：填的不是 AI Studio 的 Gemini API key——那种一定以「AIza」开头，" +
          `现在这把以「${upstreamKey.slice(0, 6)}…」开头（像是 Google Cloud / Vertex 侧的令牌）。` +
          "请找管理员在 aistudio.google.com/apikey 重新签发，填进「设置 ▸ 模型 ▸ Gemini」。"
      );
    }

    // The counting gate. Keyed on the verified mailbox, so rotating a Google key does not
    // reset anyone's counter. Deliberately last: a client that is merely misconfigured
    // should hear about that first, and should not burn a slot doing so.
    const verdict = await checkQuota(env, user.email, user.limits, t0);
    if (!verdict.ok) {
      const latencyMs = Date.now() - t0;
      ctx.waitUntil(
        recordRejected(
          env, user.email, model, kind, 429, tokenHash12, latencyMs, "quota-" + verdict.scope,
          user.name, user.dept
        )
      );
      return apiError(429, "RESOURCE_EXHAUSTED", quotaMessage(verdict), {
        "retry-after": String(verdict.retryAfter ?? 60),
      });
    }
    // Admitted — count it now rather than at completion, so a burst of long streaming
    // requests cannot all slip under the per-minute ceiling while none of them has finished.
    ctx.waitUntil(runCounters(env, countRequest(env, user.email, user.limits, t0)));

    const headers = new Headers(request.headers);
    for (const name of STRIP_REQUEST_HEADERS) headers.delete(name);
    // cf-* edge headers are stripped too (cf-connecting-ip, cf-ipcountry, cf-ray, ...).
    for (const name of [...headers.keys()]) {
      if (name.startsWith("cf-")) headers.delete(name);
    }
    // Set rather than pass through, so the ?key= form arrives upstream as a header too.
    headers.set("x-goog-api-key", upstreamKey);

    // ...and drop the query copy, so the credential is not sitting in a URL any more.
    const upstreamUrl = new URL(UPSTREAM + url.pathname + url.search);
    upstreamUrl.searchParams.delete("key");

    const upstream = await fetch(upstreamUrl.toString(), {
      method: request.method,
      headers,
      body: request.body,
      redirect: "manual",
    });
    const latencyMs = Date.now() - t0;

    const respHeaders = new Headers(upstream.headers);
    // Workers' fetch decompresses the upstream body; keeping the original
    // content-encoding/content-length on the passthrough would mislabel the
    // stream (classic proxy-worker corruption bug). Cloudflare re-compresses
    // toward the client on its own based on the client's Accept-Encoding.
    respHeaders.delete("content-encoding");
    respHeaders.delete("content-length");
    // no-transform stops Cloudflare's edge from re-compressing the response —
    // edge compression can buffer a streamed body whole, which would turn the
    // SSE stream into one all-at-once burst instead of incremental chunks.
    respHeaders.set("cache-control", "no-transform");

    const upstreamBody = upstream.body;
    if (!upstreamBody) {
      ctx.waitUntil(
        insertUsageRow(env, {
          email: user.email,
          name: user.name,
          dept: user.dept,
          model,
          kind,
          status: upstream.status,
          keyHash: tokenHash12,
          modelVersion: "",
          responseId: "",
          promptTokens: 0,
          outputTokens: 0,
          totalTokens: 0,
          cachedTokens: 0,
          thoughtsTokens: 0,
          toolPromptTokens: 0,
          latencyMs,
          durationMs: latencyMs,
          error: "",
        })
      );
      return new Response(null, { status: upstream.status, statusText: upstream.statusText, headers: respHeaders });
    }

    // Split the upstream body: the client gets its branch back immediately (untouched,
    // streamed), the other branch is consumed off the critical path to parse usage.
    const [clientBody, recordBody] = upstreamBody.tee();
    const contentType = upstream.headers.get("content-type") || "";
    ctx.waitUntil(
      recordUsage(env, recordBody, contentType, {
        email: user.email,
        name: user.name,
        dept: user.dept,
        model,
        kind,
        status: upstream.status,
        keyHash: tokenHash12,
        latencyMs,
        t0,
        limits: user.limits,
      })
    );

    return new Response(clientBody, {
      status: upstream.status,
      statusText: upstream.statusText,
      headers: respHeaders,
    });
  },

  /**
   * Nightly housekeeping (cron in wrangler.jsonc).
   *
   * Only the quota table is pruned. Minute buckets alone accumulate at up to 1,440 rows per
   * person per day and are meaningless the moment their minute passes. The `usage` ledger
   * and `auth_events` are kept forever on purpose — one is the billing record, the other is
   * security evidence.
   */
  async scheduled(_event: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    ctx.waitUntil(
      pruneQuota(env, Date.now())
        .then((rows) => console.log(`gemini-relay: pruned ${rows} quota rows`))
        .catch((err) => console.error("gemini-relay: quota prune failed:", err))
    );
  },
} satisfies ExportedHandler<Env>;
