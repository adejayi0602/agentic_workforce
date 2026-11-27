import { describe, expect, it } from "vitest";

import type { DocumentVersion } from "./api";
import { checkFile, describeLocation, describeStatus, explainVersion, isInProgress, sha256Hex } from "./documents";

describe("checkFile", () => {
  it("accepts the six formats up to 15 MB", () => {
    for (const name of ["a.docx", "b.PPTX", "c.xlsx", "d.pdf", "e.md", "f.txt"]) {
      expect(checkFile({ name, size: 1024 })).toBeNull();
    }
    expect(checkFile({ name: "big.docx", size: 15 * 1024 * 1024 })).toBeNull();
  });

  it("gives save-as advice for legacy formats", () => {
    expect(checkFile({ name: "old.doc", size: 10 })).toContain("save it as .docx");
    expect(checkFile({ name: "deck.ppt", size: 10 })).toContain(".pptx");
  });

  it("refuses other types, empty and oversized files", () => {
    expect(checkFile({ name: "virus.exe", size: 10 })).toContain("Only Word");
    expect(checkFile({ name: "a.docx", size: 0 })).toBe("The file is empty.");
    expect(checkFile({ name: "a.docx", size: 15 * 1024 * 1024 + 1 })).toContain("up to 15 MB");
  });
});

describe("sha256Hex", () => {
  it("matches the known digest of 'abc'", async () => {
    const data = new TextEncoder().encode("abc").buffer as ArrayBuffer;
    expect(await sha256Hex(data)).toBe("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
  });
});

describe("status", () => {
  it("keeps polling only while the pipeline is moving", () => {
    for (const s of ["uploaded", "scanning", "clean", "processing"]) expect(isInProgress(s)).toBe(true);
    for (const s of ["ready", "needs_ocr", "quarantined", "processing_failed"]) expect(isInProgress(s)).toBe(false);
  });

  it("labels statuses for people", () => {
    expect(describeStatus("quarantined")).toEqual({ label: "Quarantined", tone: "bad" });
    expect(describeStatus("ready").tone).toBe("ok");
  });

  it("explains failures by error code", () => {
    const failed = { status: "processing_failed", last_run: { error_code: "encrypted" } } as DocumentVersion;
    expect(explainVersion(failed)).toContain("password-protected");
    expect(explainVersion({ status: "quarantined" } as DocumentVersion)).toContain("quarantined");
    expect(explainVersion({ status: "ready" } as DocumentVersion)).toBeNull();
  });
});

describe("describeLocation", () => {
  it("matches the API's citation format", () => {
    expect(describeLocation({ heading_path: ["Scope"], slide: 2, table: 1 })).toBe("Scope · slide 2 · table 1");
    expect(describeLocation({ heading_path: [] })).toBe("start of document");
  });
});
