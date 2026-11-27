"""Extraction: bytes of a scanned, clean file -> NormalisedDocument (ADR-0009, ADR-0012).

Pure and deterministic: the same bytes always give the same result. Never call this on a file
that hasn't passed the malware scan; the worker checks `ensure_parseable` first.
"""

from collections.abc import Callable

from workforce_intake.extraction import parsers
from workforce_intake.extraction.builder import Builder
from workforce_intake.extraction.model import NormalisedDocument, Parser, Source
from workforce_intake.extraction.safety import ExtractionError, inspect_ooxml

MAX_BYTES = 15 * 1024 * 1024

_OOXML: dict[str, tuple[str, str, Callable[[bytes, Builder], None]]] = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": (
        "docx",
        "python-docx",
        parsers.parse_docx,
    ),
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": (
        "pptx",
        "python-pptx",
        parsers.parse_pptx,
    ),
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": (
        "xlsx",
        "openpyxl",
        parsers.parse_xlsx,
    ),
}


def extract(content: bytes, *, filename: str, media_type: str, sha256: str) -> NormalisedDocument:
    if len(content) > MAX_BYTES:
        raise ExtractionError("too_large", "The file is larger than 15 MB.")
    builder = Builder()
    needs_ocr = False
    parser: Parser

    if media_type in _OOXML:
        name, library, parse = _OOXML[media_type]
        report = inspect_ooxml(content)
        for warning in report.warnings:
            builder.warn(warning)
        parser = parsers.parser_info(name, library)
        try:
            parse(content, builder)
        except ExtractionError:
            raise
        except Exception as exc:  # malformed XML inside a valid ZIP, and similar
            raise ExtractionError("corrupt_file", "The file is damaged and can't be read.") from exc
    elif media_type == "application/pdf":
        parser = parsers.parser_info("pdf", "pypdf")
        try:
            needs_ocr = parsers.parse_pdf(content, builder)
        except ExtractionError:
            raise
        except Exception as exc:
            raise ExtractionError("corrupt_file", "The PDF is damaged and can't be read.") from exc
    elif media_type == "text/markdown":
        parser = parsers.parser_info("markdown", None)
        parsers.parse_markdown(content, builder)
    elif media_type == "text/plain":
        parser = parsers.parser_info("text", None)
        parsers.parse_text(content, builder)
    else:
        raise ExtractionError("unsupported_type", f"No parser for {media_type}.")

    if needs_ocr:
        builder.warn("needs_ocr")
    return NormalisedDocument(
        source=Source(
            filename=filename, media_type=media_type, sha256=sha256, size_bytes=len(content)
        ),
        parser=parser,
        needs_ocr=needs_ocr,
        blocks=builder.blocks,
        stats=builder.stats,
        warnings=builder.warnings,
    )


__all__ = ["ExtractionError", "NormalisedDocument", "extract"]
