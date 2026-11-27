"""Accumulates blocks in reading order, tracks the heading path, and enforces caps."""

from typing import Any

from workforce_intake.extraction.model import Block, BlockKind, Location, Stats

MAX_BLOCKS = 20_000
MAX_BLOCK_CHARS = 20_000
MAX_TABLE_ROWS = 2_000
MAX_TABLE_COLS = 100


def clean(text: str) -> str:
    """Normalise whitespace and drop control characters (they can hide instructions)."""
    printable = "".join(ch if ch.isprintable() or ch in "\n\t" else " " for ch in text)
    lines = [" ".join(line.split()) for line in printable.splitlines()]
    return "\n".join(line for line in lines if line).strip()


class Builder:
    def __init__(self) -> None:
        self.blocks: list[Block] = []
        self.warnings: list[str] = []
        self.stats = Stats()
        self._headings: list[tuple[int, str]] = []
        self.full = False

    @property
    def heading_path(self) -> list[str]:
        return [text for _, text in self._headings]

    def warn(self, code: str) -> None:
        if code not in self.warnings:
            self.warnings.append(code)

    def heading(self, text: str, level: int, **location: Any) -> None:
        text = clean(text)
        if not text:
            return
        while self._headings and self._headings[-1][0] >= level:
            self._headings.pop()
        self._headings.append((level, text[:500]))
        self._add(BlockKind.HEADING, text, location, level=level)
        self.stats.headings += 1

    def paragraph(
        self, text: str, kind: BlockKind = BlockKind.PARAGRAPH, **location: object
    ) -> None:
        text = clean(text)
        if text:
            self._add(kind, text, location)
            if kind == BlockKind.PARAGRAPH:
                self.stats.paragraphs += 1

    def table(self, rows: list[list[str]], **location: Any) -> None:
        if len(rows) > MAX_TABLE_ROWS:
            self.warn("table_truncated")
        cleaned = [
            [clean(cell)[:2_000] for cell in row[:MAX_TABLE_COLS]] for row in rows[:MAX_TABLE_ROWS]
        ]
        cleaned = [row for row in cleaned if any(row)]
        # Keep every row the same width as the widest one.
        width = max((len(row) for row in cleaned), default=0)
        cleaned = [row + [""] * (width - len(row)) for row in cleaned]
        if cleaned:
            self._add(BlockKind.TABLE, "", location, rows=cleaned)
            self.stats.tables += 1

    def _add(
        self,
        kind: BlockKind,
        text: str,
        location: dict[str, Any],
        *,
        level: int | None = None,
        rows: list[list[str]] | None = None,
    ) -> None:
        if len(self.blocks) >= MAX_BLOCKS:
            self.full = True
            self.warn("content_truncated")
            return
        if len(text) > MAX_BLOCK_CHARS:
            text = text[:MAX_BLOCK_CHARS]
            self.warn("long_text_truncated")
        loc = Location(heading_path=self.heading_path, **location)
        self.blocks.append(
            Block(
                id=f"b{len(self.blocks) + 1}",
                kind=kind,
                text=text,
                level=level,
                rows=rows,
                location=loc,
            )
        )
        self.stats.blocks += 1
        self.stats.characters += len(text) + sum(len(c) for r in rows or [] for c in r)
