/**
 * OAuth 2.0 authorization code flow with PKCE (RFC 7636), for a public browser client.
 * Works with Amazon Cognito's hosted UI or any standards-compliant OIDC provider (ADR-0008).
 */

export interface OidcConfig {
  /** Base URL of the provider's OAuth endpoints, e.g. https://<domain>.auth.<region>.amazoncognito.com */
  authority: string;
  clientId: string;
  redirectUri: string;
  scope: string;
}

export interface TokenSet {
  accessToken: string;
  expiresAt: number;
}

const UNRESERVED = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~";

export function base64UrlEncode(bytes: Uint8Array): string {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

/** A 64-character verifier from the unreserved set, using a CSPRNG. */
export function createVerifier(length = 64): string {
  const random = crypto.getRandomValues(new Uint8Array(length));
  return Array.from(random, (b) => UNRESERVED[b % UNRESERVED.length]).join("");
}

export async function challengeFor(verifier: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier));
  return base64UrlEncode(new Uint8Array(digest));
}

export function authorizeUrl(config: OidcConfig, state: string, challenge: string): string {
  const url = new URL(`${config.authority.replace(/\/$/, "")}/oauth2/authorize`);
  url.search = new URLSearchParams({
    response_type: "code",
    client_id: config.clientId,
    redirect_uri: config.redirectUri,
    scope: config.scope,
    state,
    code_challenge: challenge,
    code_challenge_method: "S256",
  }).toString();
  return url.toString();
}

export async function exchangeCode(
  config: OidcConfig,
  code: string,
  verifier: string,
  fetcher: typeof fetch = fetch,
): Promise<TokenSet> {
  const response = await fetcher(`${config.authority.replace(/\/$/, "")}/oauth2/token`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "authorization_code",
      client_id: config.clientId,
      redirect_uri: config.redirectUri,
      code,
      code_verifier: verifier,
    }).toString(),
  });
  if (!response.ok) throw new Error(`Token exchange failed (${response.status}).`);
  const body = (await response.json()) as { access_token?: unknown; expires_in?: unknown };
  if (typeof body.access_token !== "string") throw new Error("The provider returned no access token.");
  const ttl = typeof body.expires_in === "number" ? body.expires_in : 3600;
  return { accessToken: body.access_token, expiresAt: Date.now() + ttl * 1000 };
}

export function oidcConfigFromEnv(): OidcConfig | null {
  const authority = process.env.NEXT_PUBLIC_OIDC_AUTHORITY;
  const clientId = process.env.NEXT_PUBLIC_OIDC_CLIENT_ID;
  const redirectUri = process.env.NEXT_PUBLIC_OIDC_REDIRECT_URI;
  if (!authority || !clientId || !redirectUri) return null;
  return {
    authority,
    clientId,
    redirectUri,
    scope: process.env.NEXT_PUBLIC_OIDC_SCOPE ?? "openid email profile",
  };
}

export const AUTH_MODE: "dev" | "oidc" =
  process.env.NEXT_PUBLIC_AUTH_MODE === "oidc" ? "oidc" : "dev";
