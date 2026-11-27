"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { ErrorNotice } from "@/components/error-notice";
import { RequireSession } from "@/components/require-session";
import { ApiError, apiGet, type ExtractedBlock, type Extraction } from "@/lib/api";
import { describeLocation } from "@/lib/documents";
import { useSession } from "@/lib/session";

export default function ReviewPage() {
  return (
    <RequireSession>
      <Review />
    </RequireSession>
  );
}

const WARNINGS: Record<string, string> = {
  macros_ignored: "The file contains macros. They were ignored and never run.",
  embedded_objects_ignored: "The file contains embedded objects. They were ignored.",
  needs_ocr: "This looks like a scanned PDF without a text layer, so little or no text could be extracted.",
  content_truncated: "The document is very long; only the first part was extracted.",
  long_text_truncated: "Some very long passages were shortened.",
  table_truncated: "Some very large tables were shortened.",
  pages_truncated: "Only the first 500 pages were read.",
  slides_truncated: "Only the first 300 slides were read.",
  cells_truncated: "Only the first part of the spreadsheet was read.",
};

function Review() {
  const { projectId, documentId, versionId } = useParams<{
    projectId: string;
    documentId: string;
    versionId: string;
  }>();
  const { token, organisationId } = useSession();
  const [data, setData] = useState<Extraction | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [query, setQuery] = useState("");

  useEffect(() => {
    apiGet<Extraction>(`/api/v1/projects/${projectId}/documents/${documentId}/versions/${versionId}/extraction`, {
      token,
      organisationId,
    })
      .then(setData)
      .catch(setError);
  }, [projectId, documentId, versionId, token, organisationId]);

  const blocks = useMemo(() => data?.document.blocks ?? [], [data]);
  const outline = useMemo(() => blocks.filter((b) => b.kind === "heading" || b.kind === "slide_title"), [blocks]);
  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return blocks;
    return blocks.filter(
      (b) => b.text.toLowerCase().includes(q) || (b.rows ?? []).some((row) => row.some((c) => c.toLowerCase().includes(q))),
    );
  }, [blocks, query]);

  if (error) {
    return (
      <>
        <p className="small">
          <Link href={`/projects/${projectId}/documents/${documentId}`}>← Document</Link>
        </p>
        {error instanceof ApiError && error.status === 404 ? (
          <div className="card">
            <h1>Not ready yet</h1>
            <p>This version hasn&apos;t been processed. Check its status on the document page.</p>
          </div>
        ) : (
          <ErrorNotice error={error} />
        )}
      </>
    );
  }
  if (!data) return <p role="status">Loading…</p>;

  const { document: doc, run } = data;
  const stats = doc.stats;
  return (
    <>
      <p className="small">
        <Link href={`/projects/${projectId}/documents/${documentId}`}>← Document</Link>
      </p>
      <h1>{doc.source.filename}</h1>
      <p className="lede">
        {[
          count(stats.blocks, "block"),
          count(stats.headings, "heading"),
          count(stats.tables, "table"),
          stats.pages != null ? count(stats.pages, "page") : null,
          stats.slides != null ? count(stats.slides, "slide") : null,
          stats.sheets != null ? count(stats.sheets, "sheet") : null,
          `read with ${run.parser_name} ${run.parser_version ?? ""}`,
        ]
          .filter(Boolean)
          .join(" · ")}
      </p>

      {(doc.warnings ?? []).map((w) => (
        <p key={w} className="notice">
          {WARNINGS[w] ?? w.replace(/_/g, " ")}
        </p>
      ))}

      <div className="review">
        {outline.length ? (
          <nav className="card outline" aria-label="Outline">
            <h2>Outline</h2>
            <ol>
              {outline.map((h) => (
                <li key={h.id} style={{ paddingInlineStart: `${Math.max(0, (h.level ?? 1) - 1) * 12}px` }}>
                  <a href={`#${h.id}`}>{h.text}</a>
                </li>
              ))}
            </ol>
          </nav>
        ) : null}

        <div className="review-body">
          <label className="search">
            <span className="small muted">Search this document</span>
            <input type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="e.g. REQ-PAY-014" />
          </label>
          {query && visible.length === 0 ? <p className="muted">No matches.</p> : null}
          <ol className="blocks">
            {visible.map((b) => (
              <BlockView key={b.id} block={b} />
            ))}
          </ol>
        </div>
      </div>
    </>
  );
}

function count(n: number | undefined, noun: string): string {
  const value = n ?? 0;
  return `${value} ${noun}${value === 1 ? "" : "s"}`;
}

function BlockView({ block }: { block: ExtractedBlock }) {
  const where = describeLocation(block.location);
  if (block.kind === "heading" || block.kind === "slide_title") {
    const Tag = (block.level ?? 1) <= 1 ? "h2" : "h3";
    return (
      <li id={block.id} className="block block-heading">
        <Tag>{block.text}</Tag>
        {block.location.slide != null ? <span className="where">slide {block.location.slide}</span> : null}
      </li>
    );
  }
  return (
    <li id={block.id} className={`block block-${block.kind}`}>
      {block.kind === "table" && block.rows ? (
        <div className="scroll">
          <table className="table">
            <tbody>
              {block.rows.map((row, i) => (
                <tr key={i}>
                  {row.map((cell, j) =>
                    i === 0 ? <th key={j}>{cell}</th> : <td key={j}>{cell}</td>,
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p>
          {block.kind === "list_item" ? "• " : ""}
          {block.kind === "note" ? <span className="muted">Speaker note: </span> : null}
          {block.text}
        </p>
      )}
      <span className="where">{where}</span>
    </li>
  );
}
