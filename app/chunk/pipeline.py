"""文档切块管线：文本流按章节粘性切分；表前标题挂表格前缀；写入企业级 metadata。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.chunk.metadata import (
    SectionStack,
    aggregate_page_span,
    build_doc_attr_metadata,
    finalize_pieces,
    parse_table_page_span,
    single_bbox,
)
from app.chunk.models import ChunkPiece, EmptyChunkInputError
from app.chunk.paragraph_splitter import (
    DEFAULT_MIN_CHUNK_CHARS,
    split_full_text_fallback,
    split_section_text,
)
from app.chunk.table_splitter import split_table_html
from app.extract.models import ContentBlock

_TEXT_BLOCK_TYPES = frozenset({"title", "paragraph", "list_item"})


@dataclass
class _PendingText:
    """待切文本块及其溯源信息。"""

    block_type: str
    text: str
    page_idx: int | None
    bbox: list[float] | None
    text_level: int | None


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
        created_at: datetime | None = None,
        updated_at: datetime | None = None,
    ) -> list[ChunkPiece]:
        doc_attrs = build_doc_attr_metadata(
            base_metadata,
            created_at=created_at,
            updated_at=updated_at,
        )
        if blocks:
            pieces = self._chunk_from_blocks(blocks, base_metadata)
        else:
            cleaned = (full_text or "").strip()
            if not cleaned:
                raise EmptyChunkInputError("文档 blocks 与 full_text 皆空，无法切块")
            pieces = split_full_text_fallback(
                cleaned,
                chunk_size=self._chunk_size,
                chunk_overlap=self._chunk_overlap,
                base_metadata=base_metadata,
                min_chunk_chars=self._min_chunk_chars,
            )

        return finalize_pieces(
            pieces,
            configured_overlap=self._chunk_overlap,
            doc_attrs=doc_attrs,
        )

    def _chunk_from_blocks(
        self,
        blocks: list[ContentBlock],
        base_metadata: dict[str, Any],
    ) -> list[ChunkPiece]:
        ordered = sorted(blocks, key=lambda block: block.order)
        pieces: list[ChunkPiece] = []
        pending: list[_PendingText] = []
        section_stack = SectionStack()

        def flush_texts() -> None:
            if not pending:
                return
            items = list(pending)
            pending.clear()
            for title_header, body, section_items in _iter_sections(items):
                # 标题入栈（按出现顺序）
                for item in section_items:
                    if item.block_type == "title":
                        section_stack.push(item.text, item.text_level)

                page_num, page_end, _ = aggregate_page_span([it.page_idx for it in section_items])
                bbox = single_bbox([it.bbox for it in section_items])
                path = section_stack.path()
                leaf = section_stack.leaf()
                parent = section_stack.parent()

                pieces.extend(
                    split_section_text(
                        title_header=title_header,
                        body=body,
                        chunk_size=self._chunk_size,
                        chunk_overlap=self._chunk_overlap,
                        base_metadata=base_metadata,
                        min_chunk_chars=self._min_chunk_chars,
                        section_title=leaf,
                        parent_section=parent,
                        full_section_path=path,
                        page_num=page_num,
                        page_end=page_end,
                        bbox=bbox,
                    )
                )

        for block in ordered:
            if block.block_type in _TEXT_BLOCK_TYPES:
                text = (block.text or "").strip()
                if not text:
                    continue
                pending.append(
                    _PendingText(
                        block_type=block.block_type,
                        text=text,
                        page_idx=block.page_idx,
                        bbox=list(block.bbox) if block.bbox is not None else None,
                        text_level=block.text_level,
                    )
                )
                continue

            if block.block_type == "table":
                # 先 flush 表前正文/上级标题，再挂表前 title，避免 section 被旧叶子盖住
                table_prefix_items = _peel_trailing_titles(pending)
                flush_texts()
                for item in table_prefix_items:
                    section_stack.push(item.text, item.text_level)

                prefix = "\n\n".join(item.text for item in table_prefix_items) or None
                path = section_stack.path()
                leaf = section_stack.leaf()
                parent = section_stack.parent()

                html = block.html or ""
                span_start, span_end = parse_table_page_span(html)
                if span_start is None:
                    span_start = block.page_idx
                    span_end = block.page_idx
                page_num, page_end, _ = aggregate_page_span([span_start, span_end])

                pieces.extend(
                    split_table_html(
                        html,
                        chunk_size=self._chunk_size,
                        base_metadata=base_metadata,
                        logical_table_id=block.logical_table_id,
                        title_prefix=prefix,
                        section_title=leaf,
                        parent_section=parent,
                        full_section_path=path,
                        page_num=page_num,
                        page_end=page_end,
                        bbox=list(block.bbox) if block.bbox is not None else None,
                    )
                )
                continue

        flush_texts()

        if not pieces:
            raise EmptyChunkInputError("结构感知切块未产出任何有效 chunk")
        return pieces


def _peel_trailing_titles(pending: list[_PendingText]) -> list[_PendingText]:
    """从 pending 尾部剥下连续 title。"""
    titles: list[_PendingText] = []
    while pending and pending[-1].block_type == "title":
        titles.insert(0, pending.pop())
    return titles


def _iter_sections(
    items: list[_PendingText],
) -> list[tuple[str | None, str, list[_PendingText]]]:
    """
    将 typed pending 切成章节段，并返回该段对应的原始 items（用于页码聚合）。
    """
    sections: list[tuple[str | None, str, list[_PendingText]]] = []
    index = 0
    while index < len(items):
        if items[index].block_type == "title":
            title_parts: list[_PendingText] = []
            while index < len(items) and items[index].block_type == "title":
                title_parts.append(items[index])
                index += 1
            body_parts: list[_PendingText] = []
            while index < len(items) and items[index].block_type != "title":
                body_parts.append(items[index])
                index += 1
            section_items = title_parts + body_parts
            sections.append(
                (
                    "\n\n".join(p.text for p in title_parts),
                    "\n\n".join(p.text for p in body_parts),
                    section_items,
                )
            )
            continue

        body_parts = []
        while index < len(items) and items[index].block_type != "title":
            body_parts.append(items[index])
            index += 1
        sections.append((None, "\n\n".join(p.text for p in body_parts), list(body_parts)))
    return sections
