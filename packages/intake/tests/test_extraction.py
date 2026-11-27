"""Extraction across formats, plus the hostile files it must refuse."""

import hashlib
import io
import zipfile

import pytest

from workforce_intake.extraction import ExtractionError, extract
from workforce_intake.extraction.model import BlockKind, NormalisedDocument

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def run(content: bytes, media_type: str, filename: str = "file") -> NormalisedDocument:
    return extract(
        content,
        filename=filename,
        media_type=media_type,
        sha256=hashlib.sha256(content).hexdigest(),
    )


# ---------- fixtures built in code ----------


def make_docx() -> bytes:
    import docx

    d = docx.Document()
    d.add_heading("Payments SRS", level=0)
    d.add_heading("1 Introduction", level=1)
    d.add_paragraph("This document describes the payments platform.")
    d.add_heading("3 Functional requirements", level=1)
    d.add_heading("3.2 Card payments", level=2)
    d.add_paragraph("REQ-PAY-014: The system shall refund within 5 working days.")
    d.add_paragraph("Visa and Mastercard", style="List Bullet")
    table = d.add_table(rows=2, cols=2)
    table.cell(0, 0).text, table.cell(0, 1).text = "ID", "Priority"
    table.cell(1, 0).text, table.cell(1, 1).text = "REQ-PAY-014", "Critical"
    out = io.BytesIO()
    d.save(out)
    return out.getvalue()


def make_pptx() -> bytes:
    from pptx import Presentation
    from pptx.util import Inches

    deck = Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[1])
    slide.shapes.title.text = "Project goals"
    body = slide.placeholders[1].text_frame
    body.text = "Launch card payments"
    sub = body.add_paragraph()
    sub.text = "By Q2"
    sub.level = 1
    slide.notes_slide.notes_text_frame.text = "Mention the regulator deadline."
    second = deck.slides.add_slide(deck.slide_layouts[5])
    second.shapes.title.text = "Scope"
    shape = second.shapes.add_table(2, 2, Inches(1), Inches(2), Inches(6), Inches(1.5))
    shape.table.cell(0, 0).text, shape.table.cell(0, 1).text = "In", "Out"
    shape.table.cell(1, 0).text, shape.table.cell(1, 1).text = "Cards", "Crypto"
    out = io.BytesIO()
    deck.save(out)
    return out.getvalue()


def make_xlsx() -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "Estimates"
    ws.append(["Task", "Days"])
    ws.append(["API", 5])
    ws.append(["Total", "=SUM(B2:B2)"])  # formulas are never evaluated
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def make_pdf(pages: list[str]) -> bytes:
    """A minimal valid PDF with one line of Helvetica text per page ("" = blank page)."""
    objects: list[bytes] = []
    kids = " ".join(f"{3 + i * 2} 0 R" for i in range(len(pages)))
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode())
    font_id = 3 + len(pages) * 2
    for i, text in enumerate(pages):
        content_id = 4 + i * 2
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {content_id} 0 R "
            f"/Resources << /Font << /F1 {font_id} 0 R >> >> >>".encode()
        )
        stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode() if text else b""
        objects.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(f"{number} 0 obj\n".encode() + body + b"\nendobj\n")
    xref = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets:
        out.write(f"{offset:010d} 00000 n \n".encode())
    out.write(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return out.getvalue()


# ---------- formats ----------


def test_word_headings_paragraphs_lists_and_tables_with_locations() -> None:
    doc = run(make_docx(), DOCX, "srs.docx")
    kinds = [b.kind for b in doc.blocks]
    assert BlockKind.TABLE in kinds
    assert BlockKind.LIST_ITEM in kinds
    req = next(b for b in doc.blocks if "REQ-PAY-014: The system" in b.text)
    assert req.location.heading_path == [
        "Payments SRS",
        "3 Functional requirements",
        "3.2 Card payments",
    ]
    table = next(b for b in doc.blocks if b.kind == BlockKind.TABLE)
    assert table.rows == [["ID", "Priority"], ["REQ-PAY-014", "Critical"]]
    assert table.location.table == 1
    assert doc.parser.name == "docx"
    assert doc.parser.library.startswith("python-docx ")
    assert doc.stats.headings == 4
    assert doc.warnings == []


def test_powerpoint_slides_text_levels_tables_and_notes() -> None:
    doc = run(make_pptx(), PPTX, "deck.pptx")
    assert doc.stats.slides == 2
    titles = [b.text for b in doc.blocks if b.kind == BlockKind.SLIDE_TITLE]
    assert titles == ["Project goals", "Scope"]
    note = next(b for b in doc.blocks if b.kind == BlockKind.NOTE)
    assert note.text == "Mention the regulator deadline."
    assert note.location.slide == 1
    sub = next(b for b in doc.blocks if b.text == "By Q2")
    assert sub.kind == BlockKind.LIST_ITEM
    table = next(b for b in doc.blocks if b.kind == BlockKind.TABLE)
    assert table.location.slide == 2
    assert table.location.describe() == "Scope · slide 2 · table 1"


def test_excel_sheet_as_table_without_evaluating_formulas() -> None:
    doc = run(make_xlsx(), XLSX, "est.xlsx")
    table = next(b for b in doc.blocks if b.kind == BlockKind.TABLE)
    assert table.location.sheet == "Estimates"
    assert table.location.cell_range == "A1:B3"
    assert table.rows is not None
    assert table.rows[1] == ["API", "5"]
    assert table.rows[2] == ["Total", ""]  # the formula is never evaluated


def test_pdf_text_with_page_numbers() -> None:
    doc = run(make_pdf(["Introduction to payments", "REQ-PAY-014 refunds"]), "application/pdf")
    assert doc.stats.pages == 2
    assert not doc.needs_ocr
    assert [b.location.page for b in doc.blocks] == [1, 2]
    assert "REQ-PAY-014" in doc.blocks[1].text


def test_pdf_without_text_is_flagged_for_ocr() -> None:
    doc = run(make_pdf(["", ""]), "application/pdf")
    assert doc.needs_ocr
    assert "needs_ocr" in doc.warnings


def test_one_blank_page_among_text_pages_is_not_ocr() -> None:
    doc = run(make_pdf(["Cover", "", "Requirements text here"]), "application/pdf")
    assert not doc.needs_ocr


def test_markdown_structure() -> None:
    md = b"""# SRS

Intro paragraph
over two lines.

## Requirements

- REQ-1 first
- REQ-2 second

| ID | Priority |
| --- | --- |
| REQ-1 | High |

```
code is kept verbatim
```
"""
    doc = run(md, "text/markdown")
    para = next(b for b in doc.blocks if b.kind == BlockKind.PARAGRAPH)
    assert para.text == "Intro paragraph over two lines."
    assert para.location.line == 3
    items = [b for b in doc.blocks if b.kind == BlockKind.LIST_ITEM]
    assert [i.location.heading_path for i in items] == [["SRS", "Requirements"]] * 2
    table = next(b for b in doc.blocks if b.kind == BlockKind.TABLE)
    assert table.rows == [["ID", "Priority"], ["REQ-1", "High"]]


def test_plain_text_paragraphs_and_encoding_fallback() -> None:
    doc = run("First.\n\nSecond caf\xe9.".encode("latin-1"), "text/plain")
    assert [b.text for b in doc.blocks] == ["First.", "Second café."]


def test_extraction_is_deterministic() -> None:
    content = make_docx()
    assert run(content, DOCX).model_dump() == run(content, DOCX).model_dump()


def test_control_characters_are_stripped() -> None:
    doc = run(b"Visible\x1b[31m text\x00 here", "text/plain")
    assert doc.blocks[0].text == "Visible [31m text here"


# ---------- hostile files ----------


def zip_bytes(entries: dict[str, bytes], compression: int = zipfile.ZIP_DEFLATED) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", compression) as z:
        for name, data in entries.items():
            z.writestr(name, data)
    return out.getvalue()


def code(content: bytes, media_type: str = DOCX) -> str:
    with pytest.raises(ExtractionError) as info:
        run(content, media_type)
    return info.value.code


def test_renamed_executable_is_refused() -> None:
    assert code(b"MZ\x90\x00 this is a Windows program") == "content_does_not_match_type"
    assert code(b"not a pdf", "application/pdf") == "content_does_not_match_type"


def test_zip_bomb_is_refused() -> None:
    bomb = zip_bytes({"word/document.xml": b"\x00" * (20 * 1024 * 1024)})
    assert len(bomb) < 100_000
    assert code(bomb) == "suspicious_compression"


def test_path_traversal_entry_is_refused() -> None:
    assert code(zip_bytes({"../../evil.sh": b"rm -rf /"})) == "unsafe_archive"


def test_too_many_parts_is_refused() -> None:
    assert code(zip_bytes({f"p/{i}.xml": b"x" for i in range(2001)}, zipfile.ZIP_STORED)) == (
        "too_many_parts"
    )


def test_corrupt_office_file_is_refused() -> None:
    assert code(zip_bytes({"word/document.xml": b"<not xml"})) == "corrupt_file"


def test_macros_and_embedded_objects_are_ignored_and_reported() -> None:
    original = zipfile.ZipFile(io.BytesIO(make_docx()))
    entries = {i.filename: original.read(i.filename) for i in original.infolist()}
    entries["word/vbaProject.bin"] = b"\x00fake macro"
    entries["word/embeddings/oleObject1.bin"] = b"\x00fake object"
    doc = run(zip_bytes(entries), DOCX)
    assert set(doc.warnings) == {"macros_ignored", "embedded_objects_ignored"}
    assert any("REQ-PAY-014" in b.text for b in doc.blocks)


def test_xml_external_entities_are_not_resolved() -> None:
    original = zipfile.ZipFile(io.BytesIO(make_docx()))
    entries = {i.filename: original.read(i.filename) for i in original.infolist()}
    xxe = (
        b'<?xml version="1.0"?><!DOCTYPE d [<!ENTITY x SYSTEM "file:///etc/passwd">]>'
        b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        b"<w:body><w:p><w:r><w:t>&x;</w:t></w:r></w:p></w:body></w:document>"
    )
    entries["word/document.xml"] = xxe
    # Either the file is refused as corrupt, or the entity is left unexpanded. Never resolved.
    content = zip_bytes(entries)
    try:
        doc = run(content, DOCX)
    except ExtractionError:
        assert code(content) == "corrupt_file"
        return
    assert all("root:" not in b.text for b in doc.blocks)


def test_oversized_input_is_refused() -> None:
    assert code(b"x" * (15 * 1024 * 1024 + 1), "text/plain") == "too_large"
