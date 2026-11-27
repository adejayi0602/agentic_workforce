"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { DocumentUpload } from "@/components/document-upload";
import { ErrorNotice } from "@/components/error-notice";
import { StatusPill } from "@/components/status-pill";
import { apiGet, type DocumentSummary } from "@/lib/api";
import { categoryLabel, isInProgress } from "@/lib/documents";
import { formatDate } from "@/lib/format";
import { useSession } from "@/lib/session";

const POLL_MS = 3000;

export function DocumentsPanel({ projectId, archived }: { projectId: string; archived: boolean }) {
  const { token, organisationId, can } = useSession();
  const [documents, setDocuments] = useState<DocumentSummary[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [showUpload, setShowUpload] = useState(false);

  const load = useCallback(async () => {
    try {
      setDocuments(await apiGet<DocumentSummary[]>(`/api/v1/projects/${projectId}/documents`, { token, organisationId }));
      setError(null);
    } catch (err) {
      setError(err);
    }
  }, [projectId, token, organisationId]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  // Keep checking while anything is still moving through scanning and processing.
  const moving = documents?.some((d) => d.latest_version && isInProgress(d.latest_version.status)) ?? false;
  useEffect(() => {
    if (!moving) return;
    const timer = setInterval(() => void load(), POLL_MS);
    return () => clearInterval(timer);
  }, [moving, load]);

  const canUpload = can("document.upload") && !archived;

  return (
    <section className="card" aria-labelledby="documents">
      <div className="page-head">
        <h2 id="documents">Documents</h2>
        {canUpload && !showUpload ? (
          <button type="button" className="button" onClick={() => setShowUpload(true)}>
            Upload a document
          </button>
        ) : null}
      </div>

      {showUpload ? (
        <DocumentUpload
          projectId={projectId}
          onUploaded={() => {
            setShowUpload(false);
            void load();
          }}
        />
      ) : null}

      <ErrorNotice error={error} />

      {documents === null ? (
        <p role="status">Loading…</p>
      ) : documents.length === 0 ? (
        <p className="muted">
          No documents yet.{canUpload ? " Upload the SRS or a brief to get started." : ""}
        </p>
      ) : (
        <table className="table stack">
          <thead>
            <tr>
              <th>Document</th>
              <th>Category</th>
              <th>Version</th>
              <th>Status</th>
              <th>Added</th>
            </tr>
          </thead>
          <tbody>
            {documents.map((d) => (
              <tr key={d.id}>
                <td data-l="Document">
                  <Link href={`/projects/${projectId}/documents/${d.id}`}>{d.title}</Link>
                </td>
                <td data-l="Category">{categoryLabel(d.category)}</td>
                <td data-l="Version">{d.latest_version ? `v${d.latest_version.version}` : "—"}</td>
                <td data-l="Status">{d.latest_version ? <StatusPill status={d.latest_version.status} /> : null}</td>
                <td data-l="Added" className="nowrap">
                  {formatDate(d.created_at)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
