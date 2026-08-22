/**
 * Cloudflare Access (Zero Trust) application-token verification.
 *
 * `/login/...` is fronted by a self-hosted Access application whose only login method is
 * One-time PIN: Access authenticates the visitor at the edge — before this Worker runs —
 * and hands us a signed assertion in the `cf-access-jwt-assertion` header.
 *
 * We verify that assertion anyway. Cloudflare's own guidance is that the presence of the
 * header is not sufficient proof; checking the RS256 signature against the team's rotating
 * JWKS plus `iss`/`aud` is what makes the `email` claim trustworthy rather than merely
 * present. It also fails closed if the Access application is ever deleted or its path scope
 * drifts off `/login` — without verification, either accident would quietly turn the login
 * endpoint into an open "claim any email" form.
 */

import { createRemoteJWKSet, jwtVerify } from "jose";

export interface AccessIdentity {
  /** Verified, lowercased email from the Access token's `email` claim. */
  email: string;
  /** Access's stable per-user id — recorded in the audit trail, never used for authz. */
  sub: string;
  /** Country Access saw the login from; audit only. */
  country: string;
}

export class AccessError extends Error {}

// createRemoteJWKSet keeps the fetched key set in the isolate and refetches when it meets
// an unknown `kid`, which is exactly the behaviour Cloudflare's periodic key rotation needs
// (pinning a public key would break at the next rotation). Memoized per team domain so a
// config change during a deploy doesn't keep serving the old team's keys.
let cachedJwks: ReturnType<typeof createRemoteJWKSet> | null = null;
let cachedJwksDomain = "";

function jwksFor(teamDomain: string): ReturnType<typeof createRemoteJWKSet> {
  if (!cachedJwks || cachedJwksDomain !== teamDomain) {
    cachedJwks = createRemoteJWKSet(new URL(teamDomain + "/cdn-cgi/access/certs"));
    cachedJwksDomain = teamDomain;
  }
  return cachedJwks;
}

/** Pull the Access token out of the header, falling back to the cookie Access also sets. */
function readToken(request: Request): string {
  const header = request.headers.get("cf-access-jwt-assertion");
  if (header) return header.trim();
  const cookie = request.headers.get("cookie") || "";
  for (const part of cookie.split(";")) {
    const eq = part.indexOf("=");
    if (eq === -1) continue;
    if (part.slice(0, eq).trim() === "CF_Authorization") return part.slice(eq + 1).trim();
  }
  return "";
}

/**
 * Verify the Access assertion on an inbound request and return the authenticated identity.
 * Throws `AccessError` when the request did not come through a correctly configured Access
 * application — the caller turns that into a 403, never into a login.
 */
export async function verifyAccessJwt(
  request: Request,
  teamDomain: string,
  aud: string
): Promise<AccessIdentity> {
  if (!teamDomain || !aud) {
    throw new AccessError("relay misconfigured: ACCESS_TEAM_DOMAIN / ACCESS_AUD unset");
  }
  const token = readToken(request);
  if (!token) {
    throw new AccessError("no Access assertion on the request");
  }

  let payload: Record<string, unknown>;
  try {
    // jose enforces exp/nbf itself; issuer and audience are checked against our config.
    ({ payload } = await jwtVerify(token, jwksFor(teamDomain), {
      issuer: teamDomain,
      audience: aud,
    }));
  } catch (err) {
    throw new AccessError("Access assertion rejected: " + (err instanceof Error ? err.message : String(err)));
  }

  const email = typeof payload.email === "string" ? payload.email.trim().toLowerCase() : "";
  if (!email) {
    // Service-token identities authenticate without an email claim. This application is
    // people-only, so treat that as a refusal rather than inventing an identity.
    throw new AccessError("Access assertion carries no email claim");
  }
  return {
    email,
    sub: typeof payload.sub === "string" ? payload.sub : "",
    country: typeof payload.country === "string" ? payload.country : "",
  };
}
