# 0009. Document extraction

- Status: Accepted
- Date: 2026-11-25
- Spec references: FR-002, §13, §18

## Context

SRS documents arrive as DOCX, PDF, XLSX and Markdown. Extraction must keep provenance (which page, section or table each piece came from) so requirements can cite their source. Uploaded files are untrusted.

## Decision

- Extract with open-source parsers in an isolated worker: DOCX, text-layer PDF, XLSX and Markdown.
- Use **Amazon Textract** only for scanned or image-only PDFs, detected automatically.
- Output is a normalised document model: sections, paragraphs and tables, each with a stable location reference (page, heading path, table and cell). This model feeds requirement extraction and source citations.
- Files are checksummed on upload, malware-scanned before parsing, and never executed. Macros and embedded objects are ignored.
- Extracted text is data, never instructions. Prompt-injection defences apply to it (spec §13).
- The original file is kept unchanged in S3. Each processing run records parser name and version.

## Consequences

- Low cost and full control for most documents. A cloud service is used only where it adds real value.
- Complex PDFs may extract imperfectly. Extraction confidence is recorded, and low confidence raises a clarification.
