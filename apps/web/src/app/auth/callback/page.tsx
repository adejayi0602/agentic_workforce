"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { exchangeCode, oidcConfigFromEnv } from "@/lib/auth/pkce";
import { useSession } from "@/lib/session";
import { read, write } from "@/lib/storage";

/** Completes the OIDC authorization-code + PKCE flow started on /sign-in. */
export default function AuthCallbackPage() {
  const session = useSession();
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return; // React may run effects twice in development.
    started.current = true;

    async function complete() {
      const params = new URLSearchParams(window.location.search);
      const config = oidcConfigFromEnv();
      const verifier = read("session", "workforce.pkce_verifier");
      const expectedState = read("session", "workforce.oauth_state");
      write("session", "workforce.pkce_verifier", null);
      write("session", "workforce.oauth_state", null);

      if (params.get("error")) throw new Error(params.get("error_description") ?? "Sign-in was cancelled.");
      const code = params.get("code");
      if (!config || !code || !verifier) throw new Error("This sign-in link is incomplete or expired.");
      if (!expectedState || params.get("state") !== expectedState) {
        throw new Error("This sign-in response doesn't match the request. Please start again.");
      }
      const tokens = await exchangeCode(config, code, verifier);
      session.signIn(tokens.accessToken, tokens.expiresAt);
      router.replace("/");
    }

    complete().catch((err: unknown) => setError(err instanceof Error ? err.message : "Sign-in failed."));
  }, [session, router]);

  return (
    <div className="sign-in">
      <h1>Signing you in…</h1>
      {error ? (
        <>
          <p className="notice notice-error" role="alert">
            {error}
          </p>
          <Link className="button" href="/sign-in">
            Back to sign-in
          </Link>
        </>
      ) : (
        <p role="status">Completing sign-in with your organisation.</p>
      )}
    </div>
  );
}
