"""文档切块管线：文本流按章节粘性切分；表前标题挂表格前缀。"""

from __future__ import annotations

from typing import Any

from app.chunk.models import ChunkPiece, EmptyChunkInputError
from app.chunk.paragraph_splitter import (
    DEFAULT_MIN_CHUNK_CHARS,
    split_full_text_fallback,
    split_section_text,
)
from app.chunk.table_splitter import split_table_html
from app.extract.models import ContentBlock

_TEXT_BLOCK_TYPES = frozenset({"title", "paragraph", "list_item"})


class ChunkPipeline:
    """文档切块：连续文本块按章节粘性递归切；表格单独按 Markdown 行组切。"""

    def __init__(
        self,
        *,
        chunk_size: int,
        chunk_overlap: int = 20,
        min_chunk_chars: int = DEFAULT_MIN_CHUNK_CHARS,
    ) -> None:
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap
        self._min_chunk_chars = min_chunk_chars

    def chunk_document(
        self,
        *,
        blocks: list[ContentBlock],
        full_text: str,
        base_metadata: dict[str, Any],
    ) -> list[ChunkPiece]:
        if blocks:
            return self._chunk_from_blocks(blocks, base_metadata)

        cleaned = (full_text or "").strip()
        if cleaned:
            return split_full_text_fallback(
                cleaned,
                chunk_size=self._chunk_size,
                chunk_overlap=self._chunk_overlap,
                base_metadata=base_metadata,
                min_chunk_chars=self._min_chunk_chars,
            )

        raise EmptyChunkInputError("文档 blocks 与 full_text 皆空，无法切块")

    def _chunk_from_blocks(
        self,
        blocks: list[ContentBlock],
        base_metadata: dict[str, Any],
    ) -> list[ChunkPiece]:
        ordered = sorted(blocks, key=lambda block: block.order)
        pieces: list[ChunkPiece] = []
        # (block_type, text)
        pending: list[tuple[str, str]] = []
        section_title: str | None = None

        def flush_texts(*, table_prefix: str | None = None) -> None:
            nonlocal section_title
            if not pending:
                return
            items = list(pending)
            pending.clear()
            for title_header, body in _iter_sections(items):
                header = title_header
                effective_section = header.split("\n\n")[-1] if header else section_title
                if header:
                    section_title = effective_section
                pieces.extend(
                    split_section_text(
                        title_header=header,
                        body=body,
                        chunk_size=self._chunk_size,
                        chunk_overlap=self._chunk_overlap,
                        base_metadata=base_metadata,
                        min_chunk_chars=self._min_chunk_chars,
                        section_title=effective_section or section_title,
                    )
                )

        for block in ordered:
            if block.block_type in _TEXT_BLOCK_TYPES:
                text = (block.text or "").strip()
                if not text:
                    continue
                if block.block_type == "title":
                    section_title = text
                pending.append((block.block_type, text))
                continue

            if block.block_type == "table":
                # 表前连续 title 一律挂到表格前缀（不限长度）
                table_prefix = _peel_trailing_titles(pending)
                flush_texts()
                pieces.extend(
                    split_table_html(
                        block.html or "",
                        chunk_size=self._chunk_size,
                        base_metadata=base_metadata,
                        logical_table_id=block.logical_table_id,
                        title_prefix=table_prefix,
                    )
                )
                continue

        flush_texts()

        if not pieces:
            raise EmptyChunkInputError("结构感知切块未产出任何有效 chunk")
        return pieces


def _peel_trailing_titles(pending: list[tuple[str, str]]) -> str | None:
    """从 pending 尾部剥下连续 title，返回拼接前缀。"""
    titles: list[str] = []
    while pending and pending[-1][0] == "title":
        titles.insert(0, pending.pop()[1])
    if not titles:
        return None
    return "\n\n".join(titles)


def _iter_sections(items: list[tuple[str, str]]) -> list[tuple[str | None, str]]:
    """
    将 typed pending 切成章节段：

    - 连续 title 作为 title_header
    - 随后直到下一组 title 之前的正文/列表作为 body
    - 无 title 的前置正文单独成段（title_header=None）
    """
    sections: list[tuple[str | None, str]] = []
    index = 0
    while index < len(items):
        if items[index][0] == "title":
            title_parts: list[str] = []
            while index < len(items) and items[index][0] == "title":
                title_parts.append(items[index][1])
                index += 1
            body_parts: list[str] = []
            while index < len(items) and items[index][0] != "title":
                body_parts.append(items[index][1])
                index += 1
            sections.append(("\n\n".join(title_parts), "\n\n".join(body_parts)))
            continue

        body_parts = []
        while index < len(items) and items[index][0] != "title":
            body_parts.append(items[index][1])
            index += 1
        sections.append((None, "\n\n".join(body_parts)))
    return sections
