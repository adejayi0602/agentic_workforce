"use client";

import { useId, useRef, useState } from "react";

import { ErrorNotice } from "@/components/error-notice";
import { ApiError, apiRequest, type DocumentVersion, type UploadStarted } from "@/lib/api";
import { ACCEPT_ATTRIBUTE, CATEGORIES, checkFile, formatBytes, putWithProgress, sha256Hex } from "@/lib/documents";
import { useSession } from "@/lib/session";

type Stage = "idle" | "hashing" | "uploading" | "confirming" | "done";

const STAGE_LABEL: Record<Stage, string> = {
  idle: "",
  hashing: "Checking the file…",
  uploading: "Uploading…",
  confirming: "Confirming…",
  done: "Uploaded. Scanning and processing have started.",
};

/**
 * Uploads a new document, or (with documentId) a new version of one.
 * The file goes straight to storage; the API never sees the bytes.
 */
export function DocumentUpload({
  projectId,
  documentId,
  onUploaded,
}: {
  projectId: string;
  documentId?: string;
  onUploaded: (version: DocumentVersion) => void;
}) {
  const { token, organisationId } = useSession();
  const fileRef = useRef<HTMLInputElement>(null);
  const hintId = useId();
  const [file, setFile] = useState<File | null>(null);
  const [category, setCategory] = useState<string>("srs");
  const [title, setTitle] = useState("");
  const [stage, setStage] = useState<Stage>("idle");
  const [progress, setProgress] = useState(0);
  const [problem, setProblem] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const busy = stage === "hashing" || stage === "uploading" || stage === "confirming";

  function choose(chosen: File | null) {
    setFile(chosen);
    setError(null);
    setProgress(0);
    setStage("idle");
    setProblem(chosen ? checkFile(chosen) : null);
  }

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file || checkFile(file)) return;
    setError(null);
    setProblem(null);
    try {
      setStage("hashing");
      const bytes = await file.arrayBuffer();
      const declaration = { filename: file.name, size_bytes: file.size, sha256: await sha256Hex(bytes) };
      const base = `/api/v1/projects/${projectId}/documents`;
      const started = await apiRequest<UploadStarted>("POST", documentId ? `${base}/${documentId}/versions` : base, {
        token,
        organisationId,
        body: documentId ? declaration : { ...declaration, category, title: title.trim() || null },
      });

      setStage("uploading");
      setProgress(0);
      await putWithProgress(started.upload.url, started.upload.headers, bytes, setProgress);

      setStage("confirming");
      const version = await apiRequest<DocumentVersion>(
        "POST",
        `${base}/${started.document.id}/versions/${started.version.id}/complete`,
        { token, organisationId },
      );
      setStage("done");
      setFile(null);
      setTitle("");
      if (fileRef.current) fileRef.current.value = "";
      onUploaded(version);
    } catch (err) {
      setStage("idle");
      // API errors carry a correlation ID worth showing; storage and network errors are sentences.
      if (err instanceof ApiError) setError(err);
      else setProblem(err instanceof Error ? err.message : "The upload failed. Please try again.");
    }
  }

  return (
    <form className="form upload" onSubmit={(e) => void submit(e)}>
      <label>
        {documentId ? "New version" : "File"}
        <input
          ref={fileRef}
          type="file"
          accept={ACCEPT_ATTRIBUTE}
          aria-describedby={hintId}
          onChange={(e) => choose(e.target.files?.[0] ?? null)}
          disabled={busy}
        />
      </label>
      <p id={hintId} className="hint small muted">
        Word, PowerPoint, Excel, PDF, Markdown or text, up to 15 MB.
      </p>

      {!documentId ? (
        <div className="row">
          <label>
            Category
            <select value={category} onChange={(e) => setCategory(e.target.value)} disabled={busy}>
              {CATEGORIES.map((c) => (
                <option key={c.value} value={c.value}>
                  {c.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            Title <span className="muted">(optional)</span>
            <input value={title} maxLength={200} onChange={(e) => setTitle(e.target.value)} disabled={busy} />
          </label>
        </div>
      ) : null}

      {problem ? (
        <p className="notice notice-error" role="alert">
          {problem}
        </p>
      ) : null}
      <ErrorNotice error={error} />

      {stage !== "idle" ? (
        <div className="upload-status" role="status">
          <span>{STAGE_LABEL[stage]}</span>
          {stage === "uploading" ? (
            <span className="meter" aria-hidden="true">
              <span style={{ width: `${Math.round(progress * 100)}%` }} />
            </span>
          ) : null}
        </div>
      ) : null}

      <button type="submit" className="button button-primary" disabled={!file || !!checkFile(file) || busy}>
        {busy ? "Uploading…" : file ? `Upload ${file.name} (${formatBytes(file.size)})` : "Upload"}
      </button>
    </form>
  );
}
