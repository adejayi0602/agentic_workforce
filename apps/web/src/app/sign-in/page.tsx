"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { ErrorNotice } from "@/components/error-notice";
import { apiRequest } from "@/lib/api";
import { AUTH_MODE, authorizeUrl, challengeFor, createVerifier, oidcConfigFromEnv } from "@/lib/auth/pkce";
import { afterSignInPath } from "@/lib/invitations";
import { useSession } from "@/lib/session";
import { write } from "@/lib/storage";

export default function SignInPage() {
  const session = useSession();
  const router = useRouter();

  useEffect(() => {
    if (session.status === "ready") router.replace(afterSignInPath());
  }, [session.status, router]);

  return (
    <div className="sign-in">
      <h1>Sign in</h1>
      <p className="lede">Agentic Workforce: manifest-driven IT project delivery.</p>
      {AUTH_MODE === "oidc" ? <OidcSignIn /> : <DevSignIn />}
    </div>
  );
}

function OidcSignIn() {
  const config = oidcConfigFromEnv();
  const [error, setError] = useState<string | null>(null);

  if (!config) {
    return (
      <p className="notice notice-error" role="alert">
        Single sign-on is not configured. Set NEXT_PUBLIC_OIDC_AUTHORITY, NEXT_PUBLIC_OIDC_CLIENT_ID
        and NEXT_PUBLIC_OIDC_REDIRECT_URI.
      </p>
    );
  }

  async function start() {
    try {
      const verifier = createVerifier();
      const state = crypto.randomUUID();
      write("session", "workforce.pkce_verifier", verifier);
      write("session", "workforce.oauth_state", state);
      window.location.assign(authorizeUrl(config!, state, await challengeFor(verifier)));
    } catch {
      setError("Could not start sign-in. Please try again.");
    }
  }

  return (
    <div className="card">
      <button type="button" className="button button-primary" onClick={() => void start()}>
        Sign in with your organisation account
      </button>
      {error ? <p className="notice notice-error">{error}</p> : null}
    </div>
  );
}

function DevSignIn() {
  const session = useSession();
  const [subject, setSubject] = useState("");
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const token = await apiRequest<{ access_token: string; expires_in: number }>(
        "POST",
        "/api/v1/dev-auth/token",
        { body: { subject: subject.trim(), email: email.trim() || null, name: name.trim() || null } },
      );
      session.signIn(token.access_token, Date.now() + token.expires_in * 1000);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="card form" onSubmit={(e) => void submit(e)}>
      <p className="notice">
        <strong>Local development sign-in.</strong> Anyone can sign in as anyone here. Deployed
        environments use your organisation&apos;s single sign-on instead.
      </p>
      <label>
        Username
        <input
          required
          autoComplete="username"
          value={subject}
          onChange={(e) => setSubject(e.target.value)}
          placeholder="adetunji"
        />
      </label>
      <label>
        Email <span className="muted">(optional)</span>
        <input type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} />
      </label>
      <label>
        Display name <span className="muted">(optional)</span>
        <input autoComplete="name" value={name} onChange={(e) => setName(e.target.value)} />
      </label>
      <ErrorNotice error={error} />
      <button type="submit" className="button button-primary" disabled={busy || !subject.trim()}>
        {busy ? "Signing in…" : "Sign in"}
      </button>
    </form>
  );
}
