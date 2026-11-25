"use client";

import { useEffect, useState } from "react";

import { ApiError, apiGet, type Liveness, type Readiness } from "@/lib/api";

type State =
  | { kind: "loading" }
  | { kind: "ready"; version: string; checks: Record<string, boolean> }
  | { kind: "degraded"; version: string; checks: Record<string, boolean>; correlationId?: string }
  | { kind: "down"; message: string };

export function ApiStatus() {
  const [state, setState] = useState<State>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const live = await apiGet<Liveness>("/api/v1/health");
        try {
          const ready = await apiGet<Readiness>("/api/v1/health/ready");
          if (!cancelled) setState({ kind: "ready", version: live.version, checks: ready.checks });
        } catch (err) {
          const checks =
            err instanceof ApiError
              ? ((err.body?.details.checks as Record<string, boolean> | undefined) ?? {})
              : {};
          if (!cancelled)
            setState({
              kind: "degraded",
              version: live.version,
              checks,
              correlationId: err instanceof ApiError ? err.body?.correlation_id : undefined,
            });
        }
      } catch {
        if (!cancelled) setState({ kind: "down", message: "The API is not reachable." });
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  if (state.kind === "loading") return <p role="status">Checking the API…</p>;
  if (state.kind === "down")
    return (
      <p role="status" className="status status-down">
        {state.message}
      </p>
    );

  return (
    <div role="status">
      <p className={`status ${state.kind === "ready" ? "status-ok" : "status-warn"}`}>
        API {state.version} is {state.kind === "ready" ? "ready" : "running with problems"}
      </p>
      <ul className="checks">
        {Object.entries(state.checks).map(([name, ok]) => (
          <li key={name}>
            {name}: <strong>{ok ? "ok" : "unavailable"}</strong>
          </li>
        ))}
      </ul>
      {state.kind === "degraded" && state.correlationId ? (
        <p className="muted">Correlation ID: {state.correlationId}</p>
      ) : null}
    </div>
  );
}
