"""Checks that run before any parser opens a file (ADR-0009, threat T10)."""

import io
import zipfile
from dataclasses import dataclass, field

# Office Open XML (.docx, .pptx, .xlsx) files are ZIP archives.
MAX_ZIP_ENTRIES = 2_000
MAX_UNCOMPRESSED_BYTES = 150 * 1024 * 1024
MAX_COMPRESSION_RATIO = 120  # real Office XML compresses ~5-20x; bombs go far beyond

MACRO_PARTS = ("vbaproject.bin", "vbadata.xml")
EMBEDDED_PREFIXES = ("word/embeddings/", "ppt/embeddings/", "xl/embeddings/")

SIGNATURES: dict[str, tuple[bytes, ...]] = {
    "zip": (b"PK\x03\x04",),
    "pdf": (b"%PDF-",),
}


class ExtractionError(Exception):
    """A file that can't or mustn't be parsed. `code` is stable and safe to store."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass
class ZipReport:
    warnings: list[str] = field(default_factory=list)


def require_signature(content: bytes, kind: str) -> None:
    if not any(content.startswith(sig) for sig in SIGNATURES[kind]):
        raise ExtractionError(
            "content_does_not_match_type",
            f"The file's content isn't a valid {kind.upper()} file, despite its extension.",
        )


def inspect_ooxml(content: bytes) -> ZipReport:
    """Reject archives that are malformed, oversized when unpacked, or bomb-like."""
    require_signature(content, "zip")
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as exc:
        raise ExtractionError("corrupt_file", "The file is damaged and can't be opened.") from exc

    report = ZipReport()
    entries = archive.infolist()
    if len(entries) > MAX_ZIP_ENTRIES:
        raise ExtractionError("too_many_parts", "The file has an unusually large number of parts.")

    total = 0
    for entry in entries:
        name = entry.filename.replace("\\", "/")
        if name.startswith("/") or ".." in name.split("/"):
            raise ExtractionError("unsafe_archive", "The file contains an unsafe internal path.")
        total += entry.file_size
        if total > MAX_UNCOMPRESSED_BYTES:
            raise ExtractionError("too_large_unpacked", "The file is too large once unpacked.")
        if entry.compress_size and entry.file_size / entry.compress_size > MAX_COMPRESSION_RATIO:
            raise ExtractionError(
                "suspicious_compression", "Part of the file is compressed suspiciously well."
            )
        lowered = name.lower()
        if lowered.endswith(MACRO_PARTS) and "macros_ignored" not in report.warnings:
            report.warnings.append("macros_ignored")
        if lowered.startswith(EMBEDDED_PREFIXES) and "embedded_objects_ignored" not in (
            report.warnings
        ):
            report.warnings.append("embedded_objects_ignored")
    return report
