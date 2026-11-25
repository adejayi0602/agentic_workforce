"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { ErrorNotice } from "@/components/error-notice";
import { RequireSession } from "@/components/require-session";
import { apiGet, type Project, type ProjectPage } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { useSession } from "@/lib/session";

type Filter = "active" | "archived" | "all";

export default function ProjectsPage() {
  return (
    <RequireSession>
      <ProjectList />
    </RequireSession>
  );
}

function ProjectList() {
  const { token, organisationId, can } = useSession();
  const [filter, setFilter] = useState<Filter>("active");
  const [items, setItems] = useState<Project[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);

  const load = useCallback(
    async (after: string | null, signal?: AbortSignal) => {
      setLoading(true);
      try {
        const page = await apiGet<ProjectPage>("/api/v1/projects", {
          token,
          organisationId,
          signal,
          query: { limit: 25, cursor: after, status: filter === "all" ? null : filter },
        });
        setItems((current) => (after ? [...current, ...page.items] : page.items));
        setCursor(page.next_cursor ?? null);
        setError(null);
      } catch (err) {
        if (!(err instanceof DOMException && err.name === "AbortError")) setError(err);
      } finally {
        setLoading(false);
      }
    },
    [token, organisationId, filter],
  );

  useEffect(() => {
    const controller = new AbortController();
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load(null, controller.signal);
    return () => controller.abort();
  }, [load]);

  return (
    <>
      <div className="page-head">
        <h1>Projects</h1>
        {can("project.create") ? (
          <Link className="button button-primary" href="/projects/new">
            New project
          </Link>
        ) : null}
      </div>

      <div className="segmented" role="group" aria-label="Show">
        {(["active", "archived", "all"] as const).map((f) => (
          <button key={f} type="button" aria-pressed={filter === f} onClick={() => setFilter(f)}>
            {f[0].toUpperCase() + f.slice(1)}
          </button>
        ))}
      </div>

      <ErrorNotice error={error} />

      {!loading && items.length === 0 && !error ? (
        <div className="card empty">
          <p>No {filter === "all" ? "" : `${filter} `}projects yet.</p>
          {can("project.create") && filter !== "archived" ? (
            <Link href="/projects/new">Create the first one</Link>
          ) : null}
        </div>
      ) : (
        <table className="table stack">
          <thead>
            <tr>
              <th>Key</th>
              <th>Name</th>
              <th>Type</th>
              <th>Status</th>
              <th>Created</th>
            </tr>
          </thead>
          <tbody>
            {items.map((p) => (
              <tr key={p.id}>
                <td data-l="Key">
                  <code>{p.key}</code>
                </td>
                <td data-l="Name">
                  <Link href={`/projects/${p.id}`}>{p.name}</Link>
                </td>
                <td data-l="Type">{p.type}</td>
                <td data-l="Status">
                  <span className={`pill pill-${p.status}`}>{p.status}</span>
                </td>
                <td data-l="Created" className="nowrap">
                  {formatDate(p.created_at)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {loading ? <p role="status">Loading…</p> : null}
      {cursor && !loading ? (
        <button type="button" className="button" onClick={() => void load(cursor)}>
          Load more
        </button>
      ) : null}
    </>
  );
}
