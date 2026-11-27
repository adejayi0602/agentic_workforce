# 0012. Document intake: formats, limits, scanning and lifecycle

- Status: Accepted
- Date: 2026-11-27
- Spec references: FR-001, FR-002, §12, §13; refines ADR-0009
- Decided with the product owner on 27 Nov 2026

## Context

Sprint 2 accepts project documents (SRS, briefs, architecture notes, supporting files). They are
untrusted input: they may be malformed, hostile, or carry prompt injection. The product owner
expects SRS documents as Word files and sometimes PowerPoint decks, never larger than 15 MB.

## Decision

**Formats.** Accepted: Word (.docx), PowerPoint (.pptx), PDF, Excel (.xlsx), Markdown (.md) and
plain text (.txt). Legacy binary formats (.doc, .ppt, .xls) are refused with a message asking for
the modern format: they are where macro attacks usually hide and they parse unreliably.

**Size.** 15 MB per file, enforced twice: the presigned upload only accepts the declared size,
and the size is checked again when the upload completes.

**Integrity.** The client declares the SHA-256 before uploading. S3 verifies it on upload, and
the API checks it again on completion. Originals are never modified. Uploading again creates a
new, immutable version.

**Storage.** `org/{organisation_id}/project/{project_id}/documents/{document_id}/v{n}/original`
in the uploads bucket (ADR-0003). Normalised extraction results go to the artefacts bucket
under the same prefix.

**Malware scanning.** Every version is scanned before any parser reads it. In AWS this is
GuardDuty Malware Protection for S3 on the uploads bucket, and the result is read from the
object's tags. Locally and in tests a scanner detects the EICAR test file. Scanners sit behind
one interface. Unscanned means unprocessed (fail closed). Infected versions are quarantined:
never parsed, never downloadable, kept for investigation.

**Lifecycle.** Each version has one status, changed only along this table:

| From | To |
| --- | --- |
| awaiting_upload | uploaded, expired |
| uploaded | scanning |
| scanning | clean, quarantined, scan_failed |
| scan_failed | scanning (retry) |
| clean | processing |
| processing | ready, needs_ocr, processing_failed |
| processing_failed | processing (retry) |

`ready`, `needs_ocr`, `quarantined` and `expired` are terminal.

## Consequences

- A hostile file is stopped twice before a parser sees it: by type and size, then by the scan.
- Every requirement extracted later can cite an exact, immutable source version.
- GuardDuty is billed per GB scanned. With a 15 MB limit the cost stays small.
