"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { DocumentUpload } from "@/components/document-upload";
import { ErrorNotice } from "@/components/error-notice";
import { RequireSession } from "@/components/require-session";
import { StatusPill } from "@/components/status-pill";
import { ApiError, apiGet, apiRequest, type DocumentDetail, type DocumentVersion } from "@/lib/api";
import { categoryLabel, explainVersion, formatBytes, isInProgress } from "@/lib/documents";
import { formatDate } from "@/lib/format";
import { useSession } from "@/lib/session";

const RETRYABLE = new Set(["uploaded", "scan_failed", "clean", "processing_failed"]);

export default function DocumentPage() {
  return (
    <RequireSession>
      <DocumentView />
    </RequireSession>
  );
}

function DocumentView() {
  const { projectId, documentId } = useParams<{ projectId: string; documentId: string }>();
  const { token, organisationId, can } = useSession();
  const [doc, setDoc] = useState<DocumentDetail | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [notFound, setNotFound] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const base = `/api/v1/projects/${projectId}/documents/${documentId}`;

  const load = useCallback(async () => {
    try {
      setDoc(await apiGet<DocumentDetail>(base, { token, organisationId }));
      setError(null);
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) setNotFound(true);
      else setError(err);
    }
  }, [base, token, organisationId]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  const moving = doc?.versions.some((v) => isInProgress(v.status)) ?? false;
  useEffect(() => {
    if (!moving) return;
    const timer = setInterval(() => void load(), 3000);
    return () => clearInterval(timer);
  }, [moving, load]);

  async function retry(version: DocumentVersion) {
    try {
      const result = await apiRequest<{ started: boolean }>("POST", `${base}/versions/${version.id}/process`, {
        token,
        organisationId,
      });
      setNotice(
        result.started
          ? `Processing of version ${version.version} has restarted.`
          : "The request was recorded, but processing couldn't start right now. Try again shortly.",
      );
      await load();
    } catch (err) {
      setError(err);
    }
  }

  if (notFound) {
    return (
      <div className="card">
        <h1>Document not found</h1>
        <Link href={`/projects/${projectId}`}>Back to the project</Link>
      </div>
    );
  }
  if (!doc) return error ? <ErrorNotice error={error} /> : <p role="status">Loading…</p>;

  const latest = doc.latest_version;
  return (
    <>
      <p className="small">
        <Link href={`/projects/${projectId}`}>← Project</Link>
      </p>
      <div className="page-head">
        <h1>{doc.title}</h1>
        {latest ? <StatusPill status={latest.status} /> : null}
      </div>
      <p className="lede">{categoryLabel(doc.category)}</p>

      <ErrorNotice error={error} />
      {notice ? (
        <p className="notice" role="status">
          {notice}
        </p>
      ) : null}

      {latest?.status === "ready" || latest?.status === "needs_ocr" ? (
        <p>
          <Link className="button button-primary" href={`/projects/${projectId}/documents/${documentId}/versions/${latest.id}`}>
            Review extracted content
          </Link>
        </p>
      ) : null}

      <section className="card" aria-labelledby="versions">
        <h2 id="versions">Versions</h2>
        <ol className="versions">
          {doc.versions.map((v) => {
            const explanation = explainVersion(v);
            return (
              <li key={v.id} className="version">
                <div className="version-head">
                  <strong>v{v.version}</strong>
                  <span>{v.filename}</span>
                  <StatusPill status={v.status} />
                </div>
                <p className="small muted">
                  {formatBytes(v.size_bytes)} · added {formatDate(v.created_at)}
                  {v.last_run?.parser_name ? ` · read with ${v.last_run.parser_name} ${v.last_run.parser_version ?? ""}` : ""}
                </p>
                {explanation ? <p className="small">{explanation}</p> : null}
                {v.last_run?.stats && Array.isArray((v.last_run.stats as { warnings?: unknown }).warnings) &&
                (v.last_run.stats as { warnings: string[] }).warnings.length ? (
                  <p className="small muted">
                    Notes: {(v.last_run.stats as { warnings: string[] }).warnings.map((w) => w.replace(/_/g, " ")).join(", ")}
                  </p>
                ) : null}
                <div className="actions">
                  {v.status === "ready" || v.status === "needs_ocr" ? (
                    <Link href={`/projects/${projectId}/documents/${documentId}/versions/${v.id}`}>Review</Link>
                  ) : null}
                  {can("document.process") && RETRYABLE.has(v.status) && !isInProgress(v.status) ? (
                    <button type="button" className="button" onClick={() => void retry(v)}>
                      Retry processing
                    </button>
                  ) : null}
                </div>
              </li>
            );
          })}
        </ol>
      </section>

      {can("document.upload") ? (
        <section className="card" aria-labelledby="new-version">
          <h2 id="new-version">Upload a new version</h2>
          <p className="small muted">Earlier versions are kept exactly as they are.</p>
          <DocumentUpload projectId={projectId} documentId={documentId} onUploaded={() => void load()} />
        </section>
      ) : null}
    </>
  );
}
