import { describe, expect, it, vi } from "vitest";

import { authorizeUrl, base64UrlEncode, challengeFor, createVerifier, exchangeCode, type OidcConfig } from "./pkce";

const config: OidcConfig = {
  authority: "https://example.auth.eu-west-1.amazoncognito.com/",
  clientId: "client-123",
  redirectUri: "http://localhost:3000/auth/callback",
  scope: "openid email profile",
};

describe("PKCE", () => {
  it("matches the RFC 7636 appendix B example", async () => {
    const verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk";
    expect(await challengeFor(verifier)).toBe("E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM");
  });

  it("creates long, unreserved-character verifiers that differ each time", () => {
    const a = createVerifier();
    const b = createVerifier();
    expect(a).toHaveLength(64);
    expect(a).toMatch(/^[A-Za-z0-9\-._~]+$/);
    expect(a).not.toBe(b);
  });

  it("base64url-encodes without padding or unsafe characters", () => {
    expect(base64UrlEncode(new Uint8Array([251, 255, 191]))).toBe("-_-_");
  });
});

describe("authorizeUrl", () => {
  it("requests a code with an S256 challenge and the state", () => {
    const url = new URL(authorizeUrl(config, "state-1", "challenge-1"));
    expect(url.origin + url.pathname).toBe("https://example.auth.eu-west-1.amazoncognito.com/oauth2/authorize");
    expect(Object.fromEntries(url.searchParams)).toEqual({
      response_type: "code",
      client_id: "client-123",
      redirect_uri: "http://localhost:3000/auth/callback",
      scope: "openid email profile",
      state: "state-1",
      code_challenge: "challenge-1",
      code_challenge_method: "S256",
    });
  });
});

describe("exchangeCode", () => {
  it("posts the code and verifier and returns the access token", async () => {
    const fetcher = vi.fn(async () =>
      new Response(JSON.stringify({ access_token: "tok", expires_in: 60 }), { status: 200 }),
    );
    const before = Date.now();
    const tokens = await exchangeCode(config, "code-1", "verifier-1", fetcher as unknown as typeof fetch);
    expect(tokens.accessToken).toBe("tok");
    expect(tokens.expiresAt).toBeGreaterThanOrEqual(before + 60_000);

    const [url, init] = fetcher.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("https://example.auth.eu-west-1.amazoncognito.com/oauth2/token");
    const body = new URLSearchParams(String(init.body));
    expect(body.get("grant_type")).toBe("authorization_code");
    expect(body.get("code")).toBe("code-1");
    expect(body.get("code_verifier")).toBe("verifier-1");
    expect(body.has("client_secret")).toBe(false);
  });

  it("fails when the provider refuses", async () => {
    const fetcher = vi.fn(async () => new Response("{}", { status: 400 }));
    await expect(exchangeCode(config, "c", "v", fetcher as unknown as typeof fetch)).rejects.toThrow("400");
  });

  it("fails when no access token comes back", async () => {
    const fetcher = vi.fn(async () => new Response(JSON.stringify({ id_token: "x" }), { status: 200 }));
    await expect(exchangeCode(config, "c", "v", fetcher as unknown as typeof fetch)).rejects.toThrow("no access token");
  });
});
