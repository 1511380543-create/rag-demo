"""文本切分：递归切分 + 章节标题粘性 + 过短合并 + 相邻重叠去重。"""

from __future__ import annotations

from app.chunk.models import ChunkPiece
from app.chunk.recursive_splitter import recursive_split_text

DEFAULT_MIN_CHUNK_CHARS = 20


def split_section_text(
    *,
    title_header: str | None,
    body: str,
    chunk_size: int,
    chunk_overlap: int = 0,
    base_metadata: dict,
    min_chunk_chars: int = DEFAULT_MIN_CHUNK_CHARS,
    section_title: str | None = None,
) -> list[ChunkPiece]:
    """
    按章节切分：title_header 必须粘在第一个文本 chunk 开头，不与正文拆到两块。

    - 仅有标题无正文：整段标题成块（再走过短合并）
    - 有正文：先按「为标题预留额度」切正文，再把标题粘到首块
    """
    header = (title_header or "").strip()
    body_text = (body or "").strip()
    meta_title = (section_title or "").strip() or (header.split("\n\n")[-1] if header else None)

    if not header and not body_text:
        return []

    if not body_text:
        return _to_paragraph_pieces(
            [header],
            base_metadata=base_metadata,
            section_title=meta_title,
            min_chunk_chars=min_chunk_chars,
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
            section_title=meta_title,
            min_chunk_chars=min_chunk_chars,
        )

    # 为标题预留空间，尽量保证 header + 首段正文 ≤ chunk_size
    reserve = len(header) + 2
    body_limit = max(32, chunk_size - reserve)
    body_parts = recursive_split_text(
        body_text,
        chunk_size=body_limit,
        chunk_overlap=chunk_overlap,
    )
    if not body_parts:
        return _to_paragraph_pieces(
            [header],
            base_metadata=base_metadata,
            section_title=meta_title,
            min_chunk_chars=min_chunk_chars,
        )

    glued = [f"{header}\n\n{body_parts[0]}"] + body_parts[1:]
    return _to_paragraph_pieces(
        glued,
        base_metadata=base_metadata,
        section_title=meta_title,
        min_chunk_chars=min_chunk_chars,
    )


def split_paragraph_text(
    text: str,
    *,
    chunk_size: int,
    chunk_overlap: int = 0,
    base_metadata: dict,
    min_chunk_chars: int = DEFAULT_MIN_CHUNK_CHARS,
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
    for part in parts:
        chunk_text = part.strip()
        if not chunk_text:
            continue
        metadata = dict(base_metadata)
        metadata["chunk_kind"] = "full_text_fallback"
        pieces.append(ChunkPiece(chunk_text=chunk_text, metadata=metadata))

    pieces = merge_short_text_pieces(pieces, min_chunk_chars=min_chunk_chars)
    pieces = dedupe_adjacent_overlap(pieces, min_overlap=min_chunk_chars)
    pieces = merge_short_text_pieces(pieces, min_chunk_chars=min_chunk_chars)
    return pieces


def _to_paragraph_pieces(
    parts: list[str],
    *,
    base_metadata: dict,
    section_title: str | None,
    min_chunk_chars: int,
) -> list[ChunkPiece]:
    pieces: list[ChunkPiece] = []
    for part in parts:
        chunk_text = (part or "").strip()
        if not chunk_text:
            continue
        metadata = dict(base_metadata)
        metadata["block_type"] = "paragraph"
        metadata["chunk_kind"] = "paragraph"
        if section_title:
            metadata["section_title"] = section_title
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
