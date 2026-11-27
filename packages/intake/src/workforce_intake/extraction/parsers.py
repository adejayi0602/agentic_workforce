"""Format parsers. Each turns trusted-shape-checked bytes into blocks via the Builder."""

import io
import re
from importlib.metadata import version as package_version

from workforce_intake.extraction.builder import Builder, clean
from workforce_intake.extraction.model import BlockKind, Parser
from workforce_intake.extraction.safety import ExtractionError, require_signature

PARSER_VERSION = "1.0.0"
MAX_PDF_PAGES = 500
MAX_SLIDES = 300
MAX_SHEET_CELLS = 200_000
# A page with less text than this has no real text layer (it's probably a scanned image).
# A PDF needs OCR when most of its pages are like that; a short title page alone is fine.
EMPTY_PAGE_CHARS = 3
OCR_EMPTY_PAGE_SHARE = 0.5


def parser_info(name: str, library: str | None) -> Parser:
    lib = f"{library} {package_version(library)}" if library else "builtin"
    return Parser(name=name, version=PARSER_VERSION, library=lib)


# ---------- Word ----------

_HEADING_STYLE = re.compile(r"^heading\s*(\d)$", re.IGNORECASE)


def parse_docx(content: bytes, b: Builder) -> None:
    import docx  # python-docx: its XML parser doesn't resolve external entities
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    document = docx.Document(io.BytesIO(content))
    paragraph_no = table_no = 0
    for item in document.iter_inner_content():
        if b.full:
            break
        if isinstance(item, Paragraph):
            paragraph_no += 1
            style = (item.style.name if item.style is not None else "") or ""
            match = _HEADING_STYLE.match(style)
            if style.lower() == "title":
                # The title is the root of the heading path, above every Heading 1.
                b.heading(item.text, 0, paragraph=paragraph_no)
            elif match:
                b.heading(item.text, int(match.group(1)), paragraph=paragraph_no)
            elif "list" in style.lower() or (
                item._p.pPr is not None and item._p.pPr.numPr is not None
            ):
                b.paragraph(item.text, BlockKind.LIST_ITEM, paragraph=paragraph_no)
            else:
                b.paragraph(item.text, paragraph=paragraph_no)
        elif isinstance(item, Table):
            table_no += 1
            rows = [[cell.text for cell in row.cells] for row in item.rows]
            b.table(rows, table=table_no)


def _is_numbered(paragraph: object) -> bool:
    properties = paragraph._p.pPr  # type: ignore[attr-defined]
    return properties is not None and properties.numPr is not None


# ---------- PowerPoint ----------


def parse_pptx(content: bytes, b: Builder) -> None:
    from pptx import Presentation

    deck = Presentation(io.BytesIO(content))
    slides = list(deck.slides)
    if len(slides) > MAX_SLIDES:
        b.warn("slides_truncated")
    b.stats.slides = min(len(slides), MAX_SLIDES)
    for number, slide in enumerate(slides[:MAX_SLIDES], start=1):
        if b.full:
            break
        title_shape = slide.shapes.title
        title = clean(title_shape.text_frame.text) if title_shape is not None else ""
        if title:
            b.heading(title, 1, slide=number)
            b.blocks[-1].kind = BlockKind.SLIDE_TITLE
        else:
            b.heading(f"Slide {number}", 1, slide=number)
            b.blocks[-1].kind = BlockKind.SLIDE_TITLE
        table_no = 0
        for shape in slide.shapes:
            if shape is title_shape:
                continue
            if getattr(shape, "has_table", False) and shape.has_table:
                table_no += 1
                rows = [[cell.text for cell in row.cells] for row in shape.table.rows]
                b.table(rows, slide=number, table=table_no)
            elif getattr(shape, "has_text_frame", False) and shape.has_text_frame:
                for para in shape.text_frame.paragraphs:
                    text = "".join(run.text for run in para.runs)
                    kind = BlockKind.LIST_ITEM if para.level > 0 else BlockKind.PARAGRAPH
                    b.paragraph(text, kind, slide=number)
        if slide.has_notes_slide:
            notes = slide.notes_slide.notes_text_frame
            if notes is not None:
                b.paragraph(notes.text, BlockKind.NOTE, slide=number)


# ---------- Excel ----------


def parse_xlsx(content: bytes, b: Builder) -> None:
    from openpyxl import load_workbook
    from openpyxl.utils import get_column_letter

    # read_only streams rows; data_only reads cached values, never evaluating formulas.
    workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    try:
        sheets = workbook.worksheets
        b.stats.sheets = len(sheets)
        cells = 0
        for sheet in sheets:
            if b.full:
                break
            b.heading(sheet.title, 1, sheet=sheet.title)
            rows: list[list[str]] = []
            width = 0
            for row in sheet.iter_rows(values_only=True):
                cells += len(row)
                if cells > MAX_SHEET_CELLS:
                    b.warn("cells_truncated")
                    break
                values = ["" if v is None else str(v) for v in row]
                while values and not values[-1]:
                    values.pop()
                width = max(width, len(values))
                rows.append(values)
            while rows and not any(rows[-1]):
                rows.pop()
            # Pad to a rectangle so column positions line up with the sheet.
            rows = [row + [""] * (width - len(row)) for row in rows]
            if rows:
                span = f"A1:{get_column_letter(max(width, 1))}{len(rows)}"
                b.table(rows, sheet=sheet.title, cell_range=span, table=1)
    finally:
        workbook.close()


# ---------- PDF ----------


def parse_pdf(content: bytes, b: Builder) -> bool:
    """Returns True if the PDF looks scanned (needs OCR)."""
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    require_signature(content, "pdf")
    try:
        reader = PdfReader(io.BytesIO(content), strict=False)
        if reader.is_encrypted:
            raise ExtractionError("encrypted", "The PDF is password-protected.")
        pages = list(reader.pages)
    except PdfReadError as exc:
        raise ExtractionError("corrupt_file", "The PDF is damaged and can't be read.") from exc
    if len(pages) > MAX_PDF_PAGES:
        b.warn("pages_truncated")
    pages = pages[:MAX_PDF_PAGES]
    b.stats.pages = len(pages)
    empty_pages = 0
    for number, page in enumerate(pages, start=1):
        if b.full:
            break
        text = page.extract_text() or ""
        if len(text.strip()) < EMPTY_PAGE_CHARS:
            empty_pages += 1
        for chunk in re.split(r"\n\s*\n", text):
            b.paragraph(chunk, page=number)
    return bool(pages) and empty_pages / len(pages) > OCR_EMPTY_PAGE_SHARE


# ---------- Markdown and text ----------

_MD_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_MD_LIST = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.*)$")
_MD_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$")


def _decode(content: bytes) -> str:
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return content.decode("latin-1")


def parse_markdown(content: bytes, b: Builder) -> None:
    lines = _decode(content).splitlines()
    paragraph: list[str] = []
    start = 0
    table_no = 0
    in_code = False

    def flush() -> None:
        if paragraph:
            b.paragraph(" ".join(paragraph), line=start)
            paragraph.clear()

    i = 0
    while i < len(lines) and not b.full:
        line, number = lines[i], i + 1
        if line.strip().startswith("```"):
            flush()
            in_code = not in_code
            i += 1
            continue
        if in_code:
            b.paragraph(line, line=number)
            i += 1
            continue
        if (heading := _MD_HEADING.match(line)) is not None:
            flush()
            b.heading(heading.group(2), len(heading.group(1)), line=number)
        elif "|" in line and i + 1 < len(lines) and _MD_TABLE_SEP.match(lines[i + 1]):
            flush()
            table_no += 1
            rows = [_cells(line)]
            i += 2
            while i < len(lines) and "|" in lines[i] and lines[i].strip():
                rows.append(_cells(lines[i]))
                i += 1
            b.table(rows, table=table_no, line=number)
            continue
        elif (item := _MD_LIST.match(line)) is not None:
            flush()
            b.paragraph(item.group(1), BlockKind.LIST_ITEM, line=number)
        elif not line.strip():
            flush()
        else:
            if not paragraph:
                start = number
            paragraph.append(line.strip())
        i += 1
    flush()


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def parse_text(content: bytes, b: Builder) -> None:
    text = _decode(content)
    line = 1
    for chunk in re.split(r"(\n\s*\n)", text):
        if chunk.strip() and not chunk.isspace():
            b.paragraph(chunk, line=line)
        line += chunk.count("\n")
