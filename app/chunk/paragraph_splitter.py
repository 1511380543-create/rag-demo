"""文本切分：递归切分 + 章节软上限整节保留 + 标题粘性 + 过短合并。"""

from __future__ import annotations

from typing import Any

from app.chunk.models import ChunkPiece
from app.chunk.recursive_splitter import recursive_split_text

DEFAULT_MIN_CHUNK_CHARS = 20
# 同标题章节软上限默认：允许整节超过 chunk_size，避免检索信号被拆散
DEFAULT_SECTION_SOFT_MAX = 1000


def split_section_text(
    *,
    title_header: str | None,
    body: str,
    chunk_size: int,
    chunk_overlap: int = 0,
    base_metadata: dict,
    min_chunk_chars: int = DEFAULT_MIN_CHUNK_CHARS,
    section_soft_max: int | None = None,
    section_title: str | None = None,
    parent_section: str | None = None,
    full_section_path: list[str] | None = None,
    page_num: int | None = None,
    page_end: int | None = None,
    bbox: list[float] | None = None,
) -> list[ChunkPiece]:
    """
    按章节切分（语义完整优先）。

    - 有 title_header：
      - 整节（标题+正文）长度 ≤ section_soft_max → 整节一块（可超过 chunk_size）
      - 超过 soft_max → 再切；**每一块** chunk_text 都以标题为前缀
    - 无标题：仍按 chunk_size 递归切（兜底路径）
    """
    header = (title_header or "").strip()
    body_text = (body or "").strip()
    meta_title = (section_title or "").strip() or (header.split("\n\n")[-1] if header else None)
    soft_max = _resolve_section_soft_max(chunk_size=chunk_size, section_soft_max=section_soft_max)
    section_kwargs: dict[str, Any] = dict(
        section_title=meta_title,
        parent_section=parent_section,
        full_section_path=full_section_path,
        page_num=page_num,
        page_end=page_end,
        bbox=bbox,
    )

    if not header and not body_text:
        return []

    if not body_text:
        return _to_paragraph_pieces(
            [header],
            base_metadata=base_metadata,
            min_chunk_chars=min_chunk_chars,
            chunk_overlap=0,
            **section_kwargs,
        )

    if not header:
        parts = recursive_split_text(
            body_text,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
        return _to_paragraph_pieces(
            parts,
            base_metadata=base_metadata,
            min_chunk_chars=min_chunk_chars,
            chunk_overlap=chunk_overlap if len(parts) > 1 else 0,
            **section_kwargs,
        )

    section_text = f"{header}\n\n{body_text}"
    # 同节未超软上限：整节保留，允许超过 chunk_size
    if len(section_text) <= soft_max:
        return _to_paragraph_pieces(
            [section_text],
            base_metadata=base_metadata,
            min_chunk_chars=min_chunk_chars,
            chunk_overlap=0,
            **section_kwargs,
        )

    # 超软上限：按「软上限 - 标题预留」切正文，每块都带标题前缀
    reserve = len(header) + 2
    body_limit = max(32, soft_max - reserve)
    body_parts = recursive_split_text(
        body_text,
        chunk_size=body_limit,
        chunk_overlap=chunk_overlap,
    )
    if not body_parts:
        return _to_paragraph_pieces(
            [header],
            base_metadata=base_metadata,
            min_chunk_chars=min_chunk_chars,
            chunk_overlap=0,
            **section_kwargs,
        )

    glued = [f"{header}\n\n{part}" for part in body_parts]
    return _to_paragraph_pieces(
        glued,
        base_metadata=base_metadata,
        min_chunk_chars=min_chunk_chars,
        chunk_overlap=chunk_overlap if len(glued) > 1 else 0,
        **section_kwargs,
    )


def _resolve_section_soft_max(*, chunk_size: int, section_soft_max: int | None) -> int:
    """软上限至少不低于 chunk_size，避免配置失误导致比硬上限更严。"""
    if section_soft_max is None or section_soft_max <= 0:
        return max(chunk_size, DEFAULT_SECTION_SOFT_MAX)
    return max(chunk_size, int(section_soft_max))


def split_paragraph_text(
    text: str,
    *,
    chunk_size: int,
    chunk_overlap: int = 0,
    base_metadata: dict,
    min_chunk_chars: int = DEFAULT_MIN_CHUNK_CHARS,
    section_soft_max: int | None = None,
    section_title: str | None = None,
) -> list[ChunkPiece]:
    """对拼接后的纯文本做递归切分（无结构化 title 时的兼容入口）。"""
    return split_section_text(
        title_header=None,
        body=text,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        base_metadata=base_metadata,
        min_chunk_chars=min_chunk_chars,
        section_soft_max=section_soft_max,
        section_title=section_title,
    )


def split_full_text_fallback(
    full_text: str,
    *,
    chunk_size: int,
    chunk_overlap: int = 0,
    base_metadata: dict,
    min_chunk_chars: int = DEFAULT_MIN_CHUNK_CHARS,
) -> list[ChunkPiece]:
    """无 blocks 时整篇 full_text 递归切分。"""
    cleaned = (full_text or "").strip()
    if not cleaned:
        return []

    parts = recursive_split_text(
        cleaned,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )
    pieces: list[ChunkPiece] = []
    overlap = chunk_overlap if len(parts) > 1 else 0
    for part in parts:
        chunk_text = part.strip()
        if not chunk_text:
            continue
        metadata = dict(base_metadata)
        metadata["chunk_kind"] = "full_text_fallback"
        metadata["chunk_overlap"] = overlap
        metadata["full_section_path"] = []
        metadata["section_title"] = None
        metadata["parent_section"] = None
        pieces.append(ChunkPiece(chunk_text=chunk_text, metadata=metadata))

    pieces = merge_short_text_pieces(pieces, min_chunk_chars=min_chunk_chars)
    pieces = dedupe_adjacent_overlap(pieces, min_overlap=min_chunk_chars)
    pieces = merge_short_text_pieces(pieces, min_chunk_chars=min_chunk_chars)
    return pieces


def _to_paragraph_pieces(
    parts: list[str],
    *,
    base_metadata: dict,
    min_chunk_chars: int,
    chunk_overlap: int = 0,
    section_title: str | None = None,
    parent_section: str | None = None,
    full_section_path: list[str] | None = None,
    page_num: int | None = None,
    page_end: int | None = None,
    bbox: list[float] | None = None,
) -> list[ChunkPiece]:
    pieces: list[ChunkPiece] = []
    for part in parts:
        chunk_text = (part or "").strip()
        if not chunk_text:
            continue
        metadata: dict[str, Any] = dict(base_metadata)
        metadata["chunk_kind"] = "paragraph"
        metadata["chunk_overlap"] = chunk_overlap
        if section_title:
            metadata["section_title"] = section_title
        metadata["parent_section"] = parent_section
        metadata["full_section_path"] = list(full_section_path or [])
        metadata["page_num"] = page_num
        metadata["page_end"] = page_end if page_end is not None else page_num
        metadata["bbox"] = bbox
        pieces.append(ChunkPiece(chunk_text=chunk_text, metadata=metadata))

    pieces = merge_short_text_pieces(pieces, min_chunk_chars=min_chunk_chars)
    pieces = dedupe_adjacent_overlap(pieces, min_overlap=min_chunk_chars)
    pieces = merge_short_text_pieces(pieces, min_chunk_chars=min_chunk_chars)
    return pieces


def merge_short_text_pieces(
    pieces: list[ChunkPiece],
    *,
    min_chunk_chars: int = DEFAULT_MIN_CHUNK_CHARS,
) -> list[ChunkPiece]:
    """过短文本优先并入前一块；整篇仅一块过短时仍保留。"""
    if min_chunk_chars <= 0 or not pieces:
        return pieces

    merged: list[ChunkPiece] = []
    for piece in pieces:
        text = (piece.chunk_text or "").strip()
        if not text:
            continue
        if merged and len(text) < min_chunk_chars:
            prev = merged[-1]
            merged[-1] = ChunkPiece(
                chunk_text=f"{prev.chunk_text.rstrip()}\n{text}",
                metadata=dict(prev.metadata),
            )
            continue
        merged.append(ChunkPiece(chunk_text=text, metadata=dict(piece.metadata)))

    while len(merged) > 1 and len(merged[-1].chunk_text.strip()) < min_chunk_chars:
        last = merged.pop()
        prev = merged[-1]
        merged[-1] = ChunkPiece(
            chunk_text=f"{prev.chunk_text.rstrip()}\n{last.chunk_text.strip()}",
            metadata=dict(prev.metadata),
        )
    return merged


def dedupe_adjacent_overlap(
    pieces: list[ChunkPiece],
    *,
    min_overlap: int = 20,
) -> list[ChunkPiece]:
    """去掉下一块开头与上一块末尾重复的前缀。"""
    if len(pieces) <= 1 or min_overlap <= 0:
        return pieces

    result: list[ChunkPiece] = [pieces[0]]
    for piece in pieces[1:]:
        prev_text = result[-1].chunk_text
        curr_text = (piece.chunk_text or "").strip()
        if not curr_text:
            continue

        strip_len = _longest_suffix_prefix_overlap(prev_text, curr_text, min_overlap=min_overlap)
        if strip_len > 0:
            curr_text = curr_text[strip_len:].lstrip("\n").strip()
        if not curr_text:
            continue
        result.append(ChunkPiece(chunk_text=curr_text, metadata=dict(piece.metadata)))
    return result


def _longest_suffix_prefix_overlap(prev: str, curr: str, *, min_overlap: int) -> int:
    """
    仅去除「明确的切分 overlap 尾巴」。

    限制最大剥离长度为 curr 的 1/3，避免重复语料被误判为 overlap。
    """
    max_check = min(len(prev), len(curr), 200, max(min_overlap, len(curr) // 3))
    for length in range(max_check, min_overlap - 1, -1):
        if prev.endswith(curr[:length]):
            return length
    return 0
