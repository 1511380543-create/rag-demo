"""表格切分：HTML → Markdown 管道表，按行组切分并重复表头。"""

from __future__ import annotations

from html.parser import HTMLParser
from typing import Any

from app.chunk.models import ChunkPiece


class _TableStructureParser(HTMLParser):
    """解析表格 HTML，提取 caption、表头行与数据行（单元格纯文本）。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.caption: str = ""
        self.header_rows: list[list[str]] = []
        self.data_rows: list[list[str]] = []
        self._capture: str | None = None
        self._buffer: list[str] = []
        self._row_cells: list[str] = []
        self._in_row = False
        self._in_cell = False
        self._cell_parts: list[str] = []
        self._depth_table = 0
        self._in_thead = False
        self._in_tbody = False
        self._parse_ok = True

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            self._depth_table += 1
            return
        if self._depth_table != 1:
            return
        if tag == "caption" and self._capture is None:
            self._capture = "caption"
            self._buffer = []
            return
        if tag == "thead":
            self._in_thead = True
            return
        if tag == "tbody":
            self._in_tbody = True
            return
        if tag == "tr":
            self._in_row = True
            self._row_cells = []
            return
        if tag in {"td", "th"} and self._in_row:
            self._in_cell = True
            self._cell_parts = []
            return

    def handle_endtag(self, tag: str) -> None:
        if tag == "table":
            self._depth_table = max(0, self._depth_table - 1)
            return
        if self._depth_table != 1 and tag != "table":
            return
        if tag == "caption" and self._capture == "caption":
            self.caption = "".join(self._buffer).strip()
            self._capture = None
            self._buffer = []
            return
        if tag == "thead":
            self._in_thead = False
            return
        if tag == "tbody":
            self._in_tbody = False
            return
        if tag in {"td", "th"} and self._in_cell:
            self._row_cells.append("".join(self._cell_parts).strip())
            self._in_cell = False
            self._cell_parts = []
            return
        if tag == "tr" and self._in_row:
            self._in_row = False
            if not self._row_cells:
                return
            if self._in_thead:
                self.header_rows.append(self._row_cells)
            else:
                # 无 thead 时的顶层 tr，或 tbody 内 tr，先记入 data，后续再推断表头
                self.data_rows.append(self._row_cells)
            self._row_cells = []

    def handle_data(self, data: str) -> None:
        if self._capture == "caption":
            self._buffer.append(data)
            return
        if self._in_cell:
            self._cell_parts.append(data)

    def error(self, message: str) -> None:
        self._parse_ok = False


def _escape_md_cell(value: str) -> str:
    return " ".join(value.replace("|", "\\|").split())


def _normalize_row(row: list[str], width: int) -> list[str]:
    if len(row) >= width:
        return row[:width]
    return row + [""] * (width - len(row))


def _render_markdown_table(
    caption: str,
    headers: list[str],
    rows: list[list[str]],
) -> str:
    """渲染 Markdown 管道表；headers 为空时仅输出可读行文本。"""
    parts: list[str] = []
    if caption:
        parts.append(caption)
        parts.append("")

    if not headers:
        for row in rows:
            line = " | ".join(_escape_md_cell(cell) for cell in row if cell)
            if line:
                parts.append(line)
        return "\n".join(parts).strip()

    width = len(headers)
    header_line = "| " + " | ".join(_escape_md_cell(cell) for cell in headers) + " |"
    sep_line = "| " + " | ".join("---" for _ in headers) + " |"
    parts.append(header_line)
    parts.append(sep_line)
    for row in rows:
        normalized = _normalize_row(row, width)
        parts.append("| " + " | ".join(_escape_md_cell(cell) for cell in normalized) + " |")
    return "\n".join(parts).strip()


def _parse_table_structure(
    html: str,
) -> tuple[str, list[str], list[list[str]], bool]:
    """
    返回 (caption, headers, data_rows, ok)。

    无 thead 时：首行视为表头，其余为数据行。
    """
    parser = _TableStructureParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        return "", [], [], False

    if not parser._parse_ok:
        return "", [], [], False

    caption = parser.caption
    if parser.header_rows:
        headers = parser.header_rows[0]
        data_rows = parser.data_rows
    elif parser.data_rows:
        headers = parser.data_rows[0]
        data_rows = parser.data_rows[1:]
    else:
        return caption, [], [], True

    return caption, headers, data_rows, True


def _strip_tags_fallback(html: str) -> str:
    """无法结构化解析时，去掉标签得到可读纯文本（禁止原样输出 HTML）。"""
    parser = _TableStructureParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        pass
    # 简单去标签
    from re import sub

    text = sub(r"<[^>]+>", " ", html)
    return " ".join(text.split()).strip()


def split_table_html(
    html: str,
    *,
    chunk_size: int,
    base_metadata: dict[str, Any],
    logical_table_id: str | None = None,
    title_prefix: str | None = None,
    section_title: str | None = None,
    parent_section: str | None = None,
    full_section_path: list[str] | None = None,
    page_num: int | None = None,
    page_end: int | None = None,
    bbox: list[float] | None = None,
) -> list[ChunkPiece]:
    """
    HTML → Markdown 后按数据行组切分；每个 chunk 重复表头。

    title_prefix：表前短标题（无法并入前文本块时）挂到首个表格 chunk 上方。
    """
    cleaned = (html or "").strip()
    if not cleaned:
        return []

    caption, headers, data_rows, parse_ok = _parse_table_structure(cleaned)
    prefix = (title_prefix or "").strip()
    table_cols = len(headers) if headers else None

    def _meta(kind: str, **extra: Any) -> dict[str, Any]:
        metadata = dict(base_metadata)
        metadata["chunk_kind"] = kind
        metadata["table_format"] = "markdown"
        metadata["chunk_overlap"] = 0
        if logical_table_id:
            metadata["logical_table_id"] = logical_table_id
        if table_cols is not None:
            metadata["table_cols"] = table_cols
        if section_title:
            metadata["section_title"] = section_title
        metadata["parent_section"] = parent_section
        metadata["full_section_path"] = list(full_section_path or [])
        metadata["page_num"] = page_num
        metadata["page_end"] = page_end if page_end is not None else page_num
        metadata["bbox"] = bbox
        metadata.update(extra)
        return metadata

    def _with_prefix(text: str, *, apply: bool) -> str:
        if apply and prefix:
            return f"{prefix}\n\n{text}".strip()
        return text

    if not parse_ok or (not headers and not data_rows):
        fallback_text = _strip_tags_fallback(cleaned) or cleaned
        if "<" in fallback_text and "table" in fallback_text.lower():
            from re import sub

            fallback_text = " ".join(sub(r"<[^>]+>", " ", cleaned).split()).strip() or "（空表）"
        return [
            ChunkPiece(
                chunk_text=_with_prefix(fallback_text, apply=True),
                metadata=_meta("table_fallback"),
            )
        ]

    if not data_rows:
        text = _render_markdown_table(caption, headers, [])
        return [
            ChunkPiece(
                chunk_text=_with_prefix(text, apply=True),
                metadata=_meta("table_rows", table_row_start=0, table_row_end=-1),
            )
        ]

    header_prefix = _render_markdown_table(caption, headers, [])
    fixed_len = len(header_prefix) + (1 if header_prefix else 0)
    # 首块还要计入 title_prefix
    first_extra = len(prefix) + 2 if prefix else 0

    pieces: list[ChunkPiece] = []
    batch: list[list[str]] = []
    batch_start = 0
    batch_chars = 0
    is_first_chunk = True

    def flush(end_index: int) -> None:
        nonlocal batch, batch_start, batch_chars, is_first_chunk
        if not batch:
            return
        chunk_text = _render_markdown_table(caption, headers, batch)
        chunk_text = _with_prefix(chunk_text, apply=is_first_chunk)
        pieces.append(
            ChunkPiece(
                chunk_text=chunk_text,
                metadata=_meta(
                    "table_rows",
                    table_row_start=batch_start,
                    table_row_end=end_index,
                ),
            )
        )
        batch = []
        batch_chars = 0
        is_first_chunk = False

    for index, row in enumerate(data_rows):
        row_md = "| " + " | ".join(_escape_md_cell(c) for c in _normalize_row(row, len(headers))) + " |"
        row_len = len(row_md) + 1
        budget_extra = first_extra if is_first_chunk and not batch else 0
        effective_fixed = fixed_len + budget_extra

        if effective_fixed + row_len > chunk_size:
            if batch:
                flush(index - 1)
                batch_start = index
            batch = [row]
            flush(index)
            batch_start = index + 1
            continue

        projected = effective_fixed + batch_chars + row_len
        if batch and projected > chunk_size:
            flush(index - 1)
            batch_start = index
            batch = [row]
            batch_chars = row_len
            continue

        if not batch:
            batch_start = index
        batch.append(row)
        batch_chars += row_len

    if batch:
        flush(len(data_rows) - 1)

    if not pieces:
        text = _with_prefix(_render_markdown_table(caption, headers, data_rows), apply=True)
        return [
            ChunkPiece(
                chunk_text=text,
                metadata=_meta("table_rows", table_row_start=0, table_row_end=len(data_rows) - 1),
            )
        ]
    return pieces
