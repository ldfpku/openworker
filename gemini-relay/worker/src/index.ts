/**
 * Gemini API relay v2 — reverse proxy + per-user roster + usage accounting.
 *
 * openworker's google-genai SDK points GOOGLE_GEMINI_BASE_URL at this host;
 * every /v1beta/... request is forwarded verbatim to generativelanguage.googleapis.com
 * with the response body streamed back untouched (SSE included).
 *
 * Identity comes from a KV roster (sha256(api_key) -> email), never from anything the
 * client claims — see gemini-relay design doc. The roster doubles as admission control:
 * an unregistered key gets 403. Every terminal outcome (401 no-key, 403 unregistered,
 * proxied) is recorded to D1 via ctx.waitUntil so accounting never delays or risks the
 * response already sent to the client.
 */

export interface Env {
  ROSTER: KVNamespace;
  USAGE_DB: D1Database;
}

const UPSTREAM = "https://generativelanguage.googleapis.com";

// The google-genai SDK only ever calls /v1beta/... (api_version default); /upload covers the
// Files API in case it is used later. Everything else (scanners, typos) gets a 404.
const ALLOWED_PATH = /^\/(upload\/)?(v1|v1beta|v1alpha)\//;

// Hop-by-hop headers plus everything that would leak client/edge details upstream.
const STRIP_REQUEST_HEADERS = [
  "host",
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

async function sha256Hex(input: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(input));
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
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

async function insertUsageRow(env: Env, row: UsageRow): Promise<void> {
  try {
    await env.USAGE_DB.prepare(
      `INSERT INTO usage
        (ts, email, model, kind, status, key_hash, model_version, response_id,
         prompt_tokens, output_tokens, total_tokens, cached_tokens, thoughts_tokens,
         tool_prompt_tokens, latency_ms, duration_ms, error)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
    )
      .bind(
        new Date().toISOString(),
        row.email,
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
      )
      .run();
  } catch (err) {
    // Accounting must never affect a response that has already gone out to the client.
    console.error("gemini-relay: usage insert failed:", err);
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
  error: string
): Promise<void> {
  await insertUsageRow(env, {
    email,
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

async function recordUsage(
  env: Env,
  body: ReadableStream<Uint8Array>,
  contentType: string,
  meta: { email: string; model: string; kind: Kind; status: number; keyHash: string; latencyMs: number; t0: number }
): Promise<void> {
  try {
    const usage = emptyUsage();
    if (contentType.includes("text/event-stream")) {
      await parseSSE(body, meta.kind, usage);
    } else {
      await parseNonStream(body, meta.kind, usage);
    }
    await insertUsageRow(env, {
      email: meta.email,
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
    });
  } catch (err) {
    // Stream-level failure (e.g. connection reset mid-body) rather than a per-event parse
    // miss — those are already swallowed inside parseSSE/parseNonStream. Still record the
    // request itself so it isn't silently missing from the ledger; tokens stay at zero.
    console.error("gemini-relay: recordUsage failed:", err);
    await insertUsageRow(env, {
      email: meta.email,
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

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const t0 = Date.now();
    const url = new URL(request.url);

    if (url.pathname === "/" || url.pathname === "/healthz") {
      return new Response("ok\n", { headers: { "content-type": "text/plain" } });
    }

    if (!ALLOWED_PATH.test(url.pathname)) {
      return new Response("not found\n", { status: 404 });
    }

    const { kind, model } = classify(url.pathname);

    // The Gemini API authenticates via this header; refusing keyless requests keeps
    // the relay useless to random scanners without revealing what sits upstream.
    // Header only — the ?key= query form is rejected because full URLs (query
    // string included) land in wrangler tail / zone logs, unlike headers.
    const apiKey = request.headers.get("x-goog-api-key");
    if (!apiKey) {
      const latencyMs = Date.now() - t0;
      ctx.waitUntil(recordRejected(env, "(no-key)", model, kind, 401, "", latencyMs, "no-key"));
      return new Response("missing api key\n", { status: 401 });
    }

    // Identity is Worker-side, not client-claimed: hash the key and look it up in the
    // roster (sha256(key) -> email). The roster is also admission control — miss = 403.
    const fullHash = await sha256Hex(apiKey);
    const keyHash12 = fullHash.slice(0, 12);
    // cacheTtl keeps roster lookups at the edge (~ms) instead of hitting KV's central
    // store per request; the cost is that a revoked key stays usable for up to 5 minutes.
    const email = await env.ROSTER.get("k:" + fullHash, { cacheTtl: 300 });
    if (!email) {
      const latencyMs = Date.now() - t0;
      ctx.waitUntil(recordRejected(env, "(unregistered)", model, kind, 403, keyHash12, latencyMs, "unregistered"));
      return new Response("unregistered key\n", { status: 403 });
    }

    const headers = new Headers(request.headers);
    for (const name of STRIP_REQUEST_HEADERS) headers.delete(name);
    // cf-* edge headers are stripped too (cf-connecting-ip, cf-ipcountry, cf-ray, ...).
    for (const name of [...headers.keys()]) {
      if (name.startsWith("cf-")) headers.delete(name);
    }

    const upstream = await fetch(UPSTREAM + url.pathname + url.search, {
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
          email,
          model,
          kind,
          status: upstream.status,
          keyHash: keyHash12,
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
      recordUsage(env, recordBody, contentType, { email, model, kind, status: upstream.status, keyHash: keyHash12, latencyMs, t0 })
    );

    return new Response(clientBody, {
      status: upstream.status,
      statusText: upstream.statusText,
      headers: respHeaders,
    });
  },
} satisfies ExportedHandler<Env>;
