/**
 * Document intake helpers (ADR-0012). The server is the authority on every rule here; checking
 * in the browser first just gives people an instant, clear answer.
 */

import type { BlockLocation, DocumentVersion } from "@/lib/api";

export const MAX_BYTES = 15 * 1024 * 1024;

export const ACCEPTED: Record<string, string> = {
  ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
  ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  ".pdf": "application/pdf",
  ".md": "text/markdown",
  ".txt": "text/plain",
};

const LEGACY: Record<string, string> = {
  ".doc": ".docx",
  ".ppt": ".pptx",
  ".xls": ".xlsx",
  ".docm": ".docx",
  ".pptm": ".pptx",
  ".xlsm": ".xlsx",
};

/** For the file picker's accept attribute. */
export const ACCEPT_ATTRIBUTE = Object.keys(ACCEPTED).join(",");

export function extensionOf(filename: string): string {
  const dot = filename.lastIndexOf(".");
  return dot > 0 ? filename.slice(dot).toLowerCase() : "";
}

/** Returns a sentence explaining why the file can't be uploaded, or null if it can. */
export function checkFile(file: { name: string; size: number }): string | null {
  const ext = extensionOf(file.name);
  if (ext in LEGACY) {
    return `${ext} files aren't accepted. Please save it as ${LEGACY[ext]} and upload that instead.`;
  }
  if (!(ext in ACCEPTED)) {
    return "Only Word (.docx), PowerPoint (.pptx), Excel (.xlsx), PDF, Markdown and text files can be uploaded.";
  }
  if (file.size === 0) return "The file is empty.";
  if (file.size > MAX_BYTES) return `Files can be up to 15 MB. This one is ${formatBytes(file.size)}.`;
  return null;
}

export async function sha256Hex(data: ArrayBuffer): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", data);
  return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("");
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** PUT the file to the presigned URL, reporting progress (fetch can't report upload progress). */
export function putWithProgress(
  url: string,
  headers: Record<string, string>,
  body: ArrayBuffer,
  onProgress: (fraction: number) => void,
): Promise<void> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", url);
    for (const [name, value] of Object.entries(headers)) xhr.setRequestHeader(name, value);
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(event.loaded / event.total);
    };
    xhr.onload = () =>
      xhr.status >= 200 && xhr.status < 300
        ? resolve()
        : reject(new Error(`Storage refused the upload (${xhr.status}).`));
    xhr.onerror = () => reject(new Error("The upload was interrupted. Check your connection and try again."));
    xhr.send(body);
  });
}

// ---- status, for people ----

export type Tone = "busy" | "ok" | "warn" | "bad";

const STATUS: Record<string, { label: string; tone: Tone }> = {
  awaiting_upload: { label: "Waiting for upload", tone: "busy" },
  uploaded: { label: "Uploaded", tone: "busy" },
  scanning: { label: "Scanning for malware", tone: "busy" },
  clean: { label: "Scan passed", tone: "busy" },
  processing: { label: "Extracting content", tone: "busy" },
  ready: { label: "Ready to review", tone: "ok" },
  needs_ocr: { label: "Needs OCR", tone: "warn" },
  scan_failed: { label: "Scan couldn't finish", tone: "warn" },
  processing_failed: { label: "Couldn't be read", tone: "bad" },
  quarantined: { label: "Quarantined", tone: "bad" },
  expired: { label: "Upload expired", tone: "warn" },
};

export function describeStatus(status: string): { label: string; tone: Tone } {
  return STATUS[status] ?? { label: status.replace(/_/g, " "), tone: "warn" };
}

/** Still moving through the pipeline, so the page should keep checking. */
export function isInProgress(status: string): boolean {
  return describeStatus(status).tone === "busy";
}

const ERRORS: Record<string, string> = {
  content_does_not_match_type:
    "The file's content doesn't match its extension. It may have been renamed. Save it again in the right format and re-upload.",
  corrupt_file: "The file is damaged and can't be opened. Try re-saving it and uploading again.",
  encrypted: "The file is password-protected. Remove the password and upload it again.",
  too_many_parts: "The file has an unusually large number of internal parts and was refused for safety.",
  too_large_unpacked: "The file is far larger once unpacked than its size suggests, so it was refused for safety.",
  suspicious_compression: "Part of the file is compressed in a way typical of malicious files, so it was refused.",
  unsafe_archive: "The file contains an unsafe internal path and was refused.",
  content_changed: "The stored file no longer matches what was uploaded. Upload it again.",
  too_large: "The file is larger than 15 MB.",
};

/** A sentence explaining why a version isn't usable, or null if there's nothing to explain. */
export function explainVersion(version: DocumentVersion): string | null {
  switch (version.status) {
    case "quarantined":
      return "Our malware scan flagged this file. It has been quarantined and will never be opened or processed. If you think this is a mistake, contact your administrator.";
    case "needs_ocr":
      return "This PDF looks like scanned images with no text layer, so there was nothing to extract. Upload a text-based PDF or the original document instead.";
    case "scan_failed":
      return "The malware scan couldn't finish. A project manager can retry processing.";
    case "expired":
      return "The upload link expired before the file arrived. Upload the file again.";
    case "processing_failed": {
      const code = version.last_run?.error_code ?? "";
      return ERRORS[code] ?? "The file couldn't be read. A project manager can retry processing.";
    }
    default:
      return null;
  }
}

export function describeLocation(location: BlockLocation): string {
  const parts: string[] = [];
  if (location.heading_path?.length) parts.push(location.heading_path.join(" › "));
  if (location.page != null) parts.push(`page ${location.page}`);
  if (location.slide != null) parts.push(`slide ${location.slide}`);
  if (location.sheet != null) parts.push(`sheet ${location.sheet}${location.cell_range ? ` ${location.cell_range}` : ""}`);
  if (location.table != null) parts.push(`table ${location.table}`);
  if (location.line != null) parts.push(`line ${location.line}`);
  return parts.join(" · ") || "start of document";
}

export const CATEGORIES = [
  { value: "srs", label: "Requirements (SRS)" },
  { value: "brief", label: "Brief" },
  { value: "architecture", label: "Architecture" },
  { value: "supporting", label: "Supporting" },
] as const;

export function categoryLabel(value: string): string {
  return CATEGORIES.find((c) => c.value === value)?.label ?? value;
}
