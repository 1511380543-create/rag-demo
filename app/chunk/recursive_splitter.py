"""文本递归切分：空行 → 句子 → 字符硬切。"""

from __future__ import annotations

import re

# 句子边界：分隔符留在前一句末尾
_SENTENCE_SPLIT = re.compile(r"(?<=[。！？；.!?;])\s*")


def recursive_split_text(
    text: str,
    *,
    chunk_size: int,
    chunk_overlap: int = 0,
) -> list[str]:
    """
    按层级递归切分文本。

    1. len ≤ chunk_size → 整段返回
    2. 否则按空行拆分并装箱；超长单元再按句切
    3. 仍超长则按字符硬切（可带 overlap）
    """
    cleaned = (text or "").strip()
    if not cleaned:
        return []
    if chunk_size <= 0:
        return [cleaned]
    return _split_recursive(cleaned, chunk_size=chunk_size, chunk_overlap=max(0, chunk_overlap), depth="para")


def _split_recursive(text: str, *, chunk_size: int, chunk_overlap: int, depth: str) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]

    if depth == "para":
        units = [part.strip() for part in text.split("\n\n") if part.strip()]
        if len(units) <= 1:
            return _split_recursive(text, chunk_size=chunk_size, chunk_overlap=chunk_overlap, depth="sent")
        return _pack_units(
            units,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            joiner="\n\n",
            next_depth="sent",
        )

    if depth == "sent":
        units = _split_sentences(text)
        if len(units) <= 1:
            return _split_by_chars(text, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        return _pack_units(
            units,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            joiner="",
            next_depth="char",
        )

    return _split_by_chars(text, chunk_size=chunk_size, chunk_overlap=chunk_overlap)


def _split_sentences(text: str) -> list[str]:
    parts = _SENTENCE_SPLIT.split(text)
    return [part.strip() for part in parts if part and part.strip()]


def _pack_units(
    units: list[str],
    *,
    chunk_size: int,
    chunk_overlap: int,
    joiner: str,
    next_depth: str,
) -> list[str]:
    """将单元装箱；单个超长单元交给下一层递归。"""
    chunks: list[str] = []
    current = ""

    def flush() -> None:
        nonlocal current
        if current.strip():
            chunks.append(current.strip())
        current = ""

    for unit in units:
        unit = unit.strip()
        if not unit:
            continue

        if len(unit) > chunk_size:
            flush()
            chunks.extend(
                _split_recursive(
                    unit,
                    chunk_size=chunk_size,
                    chunk_overlap=chunk_overlap,
                    depth=next_depth,
                )
            )
            continue

        candidate = unit if not current else f"{current}{joiner}{unit}"
        if len(candidate) <= chunk_size:
            current = candidate
            continue

        flush()
        current = unit

    flush()
    return chunks


def _split_by_chars(text: str, *, chunk_size: int, chunk_overlap: int) -> list[str]:
    """字符硬切；overlap 仅在本层使用，且小于 chunk_size。"""
    if len(text) <= chunk_size:
        return [text]

    overlap = min(max(0, chunk_overlap), max(0, chunk_size - 1))
    step = max(1, chunk_size - overlap)
    result: list[str] = []
    start = 0
    length = len(text)
    while start < length:
        end = min(start + chunk_size, length)
        piece = text[start:end].strip()
        if piece:
            result.append(piece)
        if end >= length:
            break
        start += step
    return result
