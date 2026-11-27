"""The normalised document model: one shape for every format (ADR-0009).

A document is an ordered list of blocks. Every block carries a location precise enough for a
requirement extracted later to cite its source ("SRS v3, §3.2 Payments, table 1, row 4").
"""

from enum import StrEnum

from pydantic import BaseModel, Field

SCHEMA_VERSION = "1.0"


class BlockKind(StrEnum):
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    LIST_ITEM = "list_item"
    TABLE = "table"
    SLIDE_TITLE = "slide_title"
    NOTE = "note"


class Location(BaseModel):
    heading_path: list[str] = Field(default_factory=list)
    page: int | None = None
    slide: int | None = None
    sheet: str | None = None
    cell_range: str | None = None
    table: int | None = None
    paragraph: int | None = None
    line: int | None = None

    def describe(self) -> str:
        """A short human-readable citation, e.g. "slide 7 · table 1"."""
        parts: list[str] = []
        if self.heading_path:
            parts.append(" \u203a ".join(self.heading_path))
        if self.page is not None:
            parts.append(f"page {self.page}")
        if self.slide is not None:
            parts.append(f"slide {self.slide}")
        if self.sheet is not None:
            parts.append(f"sheet {self.sheet}" + (f" {self.cell_range}" if self.cell_range else ""))
        if self.table is not None:
            parts.append(f"table {self.table}")
        if self.line is not None:
            parts.append(f"line {self.line}")
        return " · ".join(parts) or "start of document"


class Block(BaseModel):
    id: str
    kind: BlockKind
    text: str = ""
    level: int | None = None
    rows: list[list[str]] | None = None
    location: Location


class Source(BaseModel):
    filename: str
    media_type: str
    sha256: str
    size_bytes: int


class Parser(BaseModel):
    name: str
    version: str
    library: str


class Stats(BaseModel):
    blocks: int = 0
    headings: int = 0
    paragraphs: int = 0
    tables: int = 0
    pages: int | None = None
    slides: int | None = None
    sheets: int | None = None
    characters: int = 0


class NormalisedDocument(BaseModel):
    schema_version: str = SCHEMA_VERSION
    source: Source
    parser: Parser
    needs_ocr: bool = False
    blocks: list[Block]
    stats: Stats
    # Facts about the file worth knowing (macros ignored, content truncated). Never content.
    warnings: list[str] = Field(default_factory=list)
