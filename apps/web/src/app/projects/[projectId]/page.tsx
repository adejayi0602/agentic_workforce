"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { AuditTable } from "@/components/audit-table";
import { DocumentsPanel } from "@/components/documents-panel";
import { ErrorNotice } from "@/components/error-notice";
import { RequireSession } from "@/components/require-session";
import { ApiError, apiGet, apiRequest, type AuditPage, type Project, type ProjectUpdate } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { useSession } from "@/lib/session";

export default function ProjectPage() {
  return (
    <RequireSession>
      <ProjectDetail />
    </RequireSession>
  );
}

function ProjectDetail() {
  const { projectId } = useParams<{ projectId: string }>();
  const { token, organisationId, can } = useSession();
  const [project, setProject] = useState<Project | null>(null);
  const [audit, setAudit] = useState<AuditPage | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [notFound, setNotFound] = useState(false);
  const [editing, setEditing] = useState(false);

  const load = useCallback(async () => {
    try {
      const p = await apiGet<Project>(`/api/v1/projects/${projectId}`, { token, organisationId });
      setProject(p);
      if (can("audit.read")) {
        setAudit(
          await apiGet<AuditPage>(`/api/v1/projects/${projectId}/audit-events`, {
            token,
            organisationId,
            query: { limit: 20 },
          }),
        );
      }
      setError(null);
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) setNotFound(true);
      else setError(err);
    }
  }, [projectId, token, organisationId, can]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  async function update(changes: ProjectUpdate) {
    try {
      setProject(
        await apiRequest<Project>("PATCH", `/api/v1/projects/${projectId}`, {
          token,
          organisationId,
          body: changes,
        }),
      );
      setEditing(false);
      setError(null);
      await load();
    } catch (err) {
      setError(err);
    }
  }

  if (notFound) {
    return (
      <div className="card">
        <h1>Project not found</h1>
        <p>It may belong to another organisation, or the link may be wrong.</p>
        <Link href="/projects">Back to projects</Link>
      </div>
    );
  }
  if (!project) return error ? <ErrorNotice error={error} /> : <p role="status">Loading…</p>;

  return (
    <>
      <p className="small">
        <Link href="/projects">← Projects</Link>
      </p>
      <div className="page-head">
        <h1>
          {project.name} <code className="muted">{project.key}</code>
        </h1>
        <span className={`pill pill-${project.status}`}>{project.status}</span>
      </div>

      <ErrorNotice error={error} />

      {editing ? (
        <EditForm project={project} onCancel={() => setEditing(false)} onSave={update} />
      ) : (
        <section className="card">
          <dl className="facts">
            <dt>Type</dt>
            <dd>{project.type}</dd>
            <dt>Description</dt>
            <dd>{project.description || <span className="muted">None</span>}</dd>
            <dt>Created</dt>
            <dd>{formatDate(project.created_at)}</dd>
            <dt>Last updated</dt>
            <dd>{formatDate(project.updated_at)}</dd>
          </dl>
          <div className="actions">
            {can("project.update") ? (
              <button type="button" className="button" onClick={() => setEditing(true)}>
                Edit
              </button>
            ) : null}
            {can("project.archive") ? (
              <button
                type="button"
                className="button"
                onClick={() => void update({ status: project.status === "active" ? "archived" : "active" })}
              >
                {project.status === "active" ? "Archive" : "Restore"}
              </button>
            ) : null}
          </div>
        </section>
      )}

      <DocumentsPanel projectId={project.id} archived={project.status !== "active"} />

      {audit ? (
        <section className="card" aria-labelledby="history">
          <h2 id="history">History</h2>
          <AuditTable events={audit.items} />
        </section>
      ) : null}
    </>
  );
}

function EditForm({
  project,
  onCancel,
  onSave,
}: {
  project: Project;
  onCancel: () => void;
  onSave: (changes: ProjectUpdate) => Promise<void>;
}) {
  const [name, setName] = useState(project.name);
  const [description, setDescription] = useState(project.description ?? "");
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    const changes: ProjectUpdate = {};
    if (name.trim() !== project.name) changes.name = name.trim();
    if ((description.trim() || null) !== project.description) changes.description = description.trim() || null;
    await onSave(changes);
    setBusy(false);
  }

  return (
    <form className="card form" onSubmit={(e) => void submit(e)}>
      <label>
        Name
        <input required maxLength={200} value={name} onChange={(e) => setName(e.target.value)} />
      </label>
      <label>
        Description
        <textarea rows={4} maxLength={5000} value={description} onChange={(e) => setDescription(e.target.value)} />
      </label>
      <div className="actions">
        <button type="submit" className="button button-primary" disabled={busy}>
          {busy ? "Saving…" : "Save"}
        </button>
        <button type="button" className="button" onClick={onCancel} disabled={busy}>
          Cancel
        </button>
      </div>
    </form>
  );
}
