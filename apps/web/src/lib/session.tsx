"use client";

/**
 * Session state: the bearer token, the signed-in user, and the organisation being worked in.
 *
 * The token lives in sessionStorage, so it ends with the tab. The selected organisation lives
 * in localStorage, so it is remembered between visits. Both are browser-only, so the provider
 * uses `use(browser())` and must sit inside a Suspense boundary (Next.js 16 / React 19.3).
 */

import { createContext, use, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { browser } from "react-dom";

import { ApiError, apiGet, type Me, type Membership, type Organisation } from "@/lib/api";
import { read, write } from "@/lib/storage";

const TOKEN_KEY = "workforce.token";
const TOKEN_EXPIRY_KEY = "workforce.token_expires_at";
const ORG_KEY = "workforce.organisation_id";

type Status = "signed-out" | "loading" | "ready" | "error";

interface SessionValue {
  status: Status;
  token: string | null;
  me: Me | null;
  organisationId: string | null;
  membership: Membership | null;
  organisation: Organisation | null;
  error: ApiError | null;
  signIn: (token: string, expiresAt?: number) => void;
  signOut: () => void;
  selectOrganisation: (organisationId: string) => void;
  refresh: () => Promise<void>;
  can: (permission: string) => boolean;
}

const SessionContext = createContext<SessionValue | null>(null);

function storedToken(): string | null {
  const token = read("session", TOKEN_KEY);
  const expiresAt = Number(read("session", TOKEN_EXPIRY_KEY) ?? 0);
  if (!token || (expiresAt && Date.now() > expiresAt)) return null;
  return token;
}

export function SessionProvider({ children }: { children: React.ReactNode }) {
  use(browser("The sign-in token is kept in sessionStorage."));

  const [token, setToken] = useState<string | null>(storedToken);
  const [organisationId, setOrganisationId] = useState<string | null>(() => read("local", ORG_KEY));
  const [me, setMe] = useState<Me | null>(null);
  const [organisation, setOrganisation] = useState<Organisation | null>(null);
  const [status, setStatus] = useState<Status>(token ? "loading" : "signed-out");
  const [error, setError] = useState<ApiError | null>(null);

  const signOut = useCallback(() => {
    write("session", TOKEN_KEY, null);
    write("session", TOKEN_EXPIRY_KEY, null);
    setToken(null);
    setMe(null);
    setOrganisation(null);
    setStatus("signed-out");
  }, []);

  const signIn = useCallback((newToken: string, expiresAt?: number) => {
    write("session", TOKEN_KEY, newToken);
    write("session", TOKEN_EXPIRY_KEY, expiresAt ? String(expiresAt) : null);
    setToken(newToken);
    setStatus("loading");
  }, []);

  const selectOrganisation = useCallback((id: string) => {
    write("local", ORG_KEY, id);
    setOrganisationId(id);
  }, []);

  const load = useCallback(
    async (signal?: AbortSignal) => {
      if (!token) return;
      try {
        const profile = await apiGet<Me>("/api/v1/me", { token, signal });
        setMe(profile);
        const chosen =
          profile.memberships.find((m) => m.organisation_id === organisationId) ??
          profile.memberships[0] ??
          null;
        if (chosen && chosen.organisation_id !== organisationId) {
          write("local", ORG_KEY, chosen.organisation_id);
          setOrganisationId(chosen.organisation_id);
        }
        setOrganisation(
          chosen
            ? await apiGet<Organisation>("/api/v1/organisations/current", {
                token,
                organisationId: chosen.organisation_id,
                signal,
              })
            : null,
        );
        setError(null);
        setStatus("ready");
      } catch (err) {
        if (err instanceof DOMException && err.name === "AbortError") return;
        if (err instanceof ApiError && err.status === 401) {
          signOut();
          return;
        }
        setError(err instanceof ApiError ? err : new ApiError(0, null));
        setStatus("error");
      }
    },
    [token, organisationId, signOut],
  );

  useEffect(() => {
    const controller = new AbortController();
    // Loading on token or organisation change is the point of this effect.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  const value = useMemo<SessionValue>(() => {
    const membership = me?.memberships.find((m) => m.organisation_id === organisationId) ?? null;
    const permissions = new Set(organisation?.your_permissions ?? []);
    return {
      status,
      token,
      me,
      organisationId: membership ? organisationId : null,
      membership,
      organisation,
      error,
      signIn,
      signOut,
      selectOrganisation,
      refresh: () => load(),
      can: (permission) => permissions.has(permission),
    };
  }, [status, token, me, organisationId, organisation, error, signIn, signOut, selectOrganisation, load]);

  return <SessionContext value={value}>{children}</SessionContext>;
}

export function useSession(): SessionValue {
  const value = useContext(SessionContext);
  if (!value) throw new Error("useSession must be used inside <SessionProvider>.");
  return value;
}
