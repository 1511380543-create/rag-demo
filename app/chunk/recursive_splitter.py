"""文本递归切分：空行 → 句子 → 软标点 → 字符硬切（优先软边界）。"""

from __future__ import annotations

import re

# 句子边界：分隔符留在前一句末尾
_SENTENCE_SPLIT = re.compile(r"(?<=[。！？；.!?;])\s*")
# 软标点单元：无句号的长段按逗号/顿号/冒号/换行切开（分隔符留在前一单元）
_SOFT_UNIT_SPLIT = re.compile(r"(?<=[，、；：:\n])")

# 硬切回看时的软边界（优先级：强 → 弱）
_STRONG_BOUNDARY = frozenset("\n。！？；.!?;")
_WEAK_BOUNDARY = frozenset("，、：:")
# 过短尾块阈值（相对硬切兜底；与 min_chunk_chars 默认对齐）
_DEFAULT_TAIL_MIN_CHARS = 20


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
    3. 仍超长则按软标点（，、；：换行）装箱
    4. 再不行则字符硬切：优先在软边界落刀，禁止无信息短尾单独成块
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
            # 无句号的长段：先走软标点，避免直接硬切到汉字中间
            return _split_recursive(text, chunk_size=chunk_size, chunk_overlap=chunk_overlap, depth="soft")
        return _pack_units(
            units,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            joiner="",
            next_depth="soft",
        )

    if depth == "soft":
        units = _split_soft_units(text)
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


def _split_soft_units(text: str) -> list[str]:
    """按软标点切开；无软标点时返回整段。"""
    parts = _SOFT_UNIT_SPLIT.split(text)
    return [part for part in parts if part and part.strip()]


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
        # 软标点切出的单元可能含前导空白，统一 strip 后再装箱
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
    """
    长度上限兜底切分。

    - 优先在 chunk_size 窗口内回看软边界（换行/句读/逗号等）落刀
    - 找不到软边界才按字符硬切
    - overlap 仅本层使用；过短尾块并入上一块（可轻微超过 chunk_size）
    """
    cleaned = (text or "").strip()
    if not cleaned:
        return []
    if len(cleaned) <= chunk_size:
        return [cleaned]

    overlap = min(max(0, chunk_overlap), max(0, chunk_size - 1))
    result: list[str] = []
    start = 0
    length = len(cleaned)
    # 至少保留半窗，避免软边界回看把当前块切得过短
    min_keep = max(1, chunk_size // 2)

    while start < length:
        hard_end = min(start + chunk_size, length)
        if hard_end >= length:
            tail = cleaned[start:].strip()
            if tail:
                result.append(tail)
            break

        cut = _find_soft_cut_end(cleaned, start=start, hard_end=hard_end, min_keep=min_keep)
        piece = cleaned[start:cut].strip()
        if piece:
            result.append(piece)

        if cut >= length:
            break

        # 下一块起点：软切后跳过前导空白；有 overlap 时回退 overlap 字符
        next_start = cut
        if overlap > 0:
            next_start = max(start + 1, cut - overlap)
        # 避免卡死
        if next_start <= start:
            next_start = start + max(1, chunk_size - overlap)
        start = next_start

    return _merge_short_tails(result, min_chars=_DEFAULT_TAIL_MIN_CHARS)


def _find_soft_cut_end(text: str, *, start: int, hard_end: int, min_keep: int) -> int:
    """
    在 [start + min_keep, hard_end) 内从右往左找软边界。

    返回切点下标（不含右开区间习惯：返回值作为下一片 start）。
    强边界（句号/换行）优先于弱边界（逗号）；找不到则 hard_end。
    """
    search_from = start + min_keep
    if search_from >= hard_end:
        return hard_end

    strong_cut: int | None = None
    weak_cut: int | None = None
    for index in range(hard_end - 1, search_from - 1, -1):
        char = text[index]
        if char in _STRONG_BOUNDARY:
            strong_cut = index + 1
            break
        if weak_cut is None and char in _WEAK_BOUNDARY:
            weak_cut = index + 1

    if strong_cut is not None:
        return strong_cut
    if weak_cut is not None:
        return weak_cut
    return hard_end


def _merge_short_tails(parts: list[str], *, min_chars: int) -> list[str]:
    """过短尾块并入上一块，避免「处/罚」类无信息碎片单独成块。"""
    if min_chars <= 0 or len(parts) <= 1:
        return parts

    merged: list[str] = []
    for part in parts:
        text = (part or "").strip()
        if not text:
            continue
        if merged and len(text) < min_chars:
            merged[-1] = f"{merged[-1]}{text}"
            continue
        merged.append(text)

    while len(merged) > 1 and len(merged[-1]) < min_chars:
        last = merged.pop()
        merged[-1] = f"{merged[-1]}{last}"
    return merged
