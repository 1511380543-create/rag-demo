"""切块 metadata  enrichment（对齐 spec 09 §3.6）。"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from app.chunk.models import ChunkPiece

# 协议报文 / 十六进制启发式
_HEX_TOKEN = re.compile(r"\b0x[0-9A-Fa-f]{2,}\b")
_HEX_PAIR_RUN = re.compile(r"(?:[0-9A-Fa-f]{2}[\s\-:]){3,}[0-9A-Fa-f]{2}")
_TITLE_NUMBER = re.compile(r"^(\d+(?:\.\d+)*)")


def estimate_token_count(text: str) -> int:
    """
    估算 token：CJK 按字，拉丁按空白分词（算法名 cjk_char_latin_word_v1）。
    """
    if not text:
        return 0
    count = 0
    buf: list[str] = []
    for ch in text:
        if "\u4e00" <= ch <= "\u9fff" or "\u3400" <= ch <= "\u4dbf" or "\uf900" <= ch <= "\ufaff":
            if buf:
                count += 1
                buf.clear()
            count += 1
        elif ch.isspace():
            if buf:
                count += 1
                buf.clear()
        else:
            buf.append(ch)
    if buf:
        count += 1
    return count


def detect_protocol_code(text: str) -> bool:
    """是否含协议报文 / 十六进制片段。"""
    if not text:
        return False
    return bool(_HEX_TOKEN.search(text) or _HEX_PAIR_RUN.search(text))


def normalize_access_group(value: Any) -> list[str]:
    """规范化权限分组，缺省 ["rd"]。"""
    allowed = {"rd", "ops", "after_sales"}
    if value is None:
        return ["rd"]
    if isinstance(value, str):
        cleaned = value.strip()
        return [cleaned] if cleaned in allowed else ["rd"]
    if isinstance(value, (list, tuple)):
        groups = [str(item).strip() for item in value if str(item).strip() in allowed]
        return groups or ["rd"]
    return ["rd"]


def format_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat(timespec="seconds")


def page_nums_from_idx(page_idx: int | None, page_idx_end: int | None = None) -> tuple[int | None, int | None, bool]:
    """0-based page_idx → 1-based page_num/page_end + is_cross_page。"""
    if page_idx is None:
        return None, None, False
    start = page_idx + 1
    end_idx = page_idx if page_idx_end is None else page_idx_end
    end = end_idx + 1
    if end < start:
        end = start
    return start, end, end > start


def aggregate_page_span(
    page_indices: list[int | None],
) -> tuple[int | None, int | None, bool]:
    """聚合多个 block 的 page_idx。"""
    valid = [idx for idx in page_indices if isinstance(idx, int) and idx >= 0]
    if not valid:
        return None, None, False
    return page_nums_from_idx(min(valid), max(valid))


def single_bbox(bboxes: list[list[float] | None]) -> list[float] | None:
    """仅当全部非空且相同（或仅一块）时保留 bbox。"""
    present = [box for box in bboxes if box is not None]
    if len(present) != 1:
        # 多块或没有：跨 block 不聚合
        if len(present) > 1 and all(box == present[0] for box in present):
            return list(present[0])
        return None
    return list(present[0])


def parse_table_page_span(html: str) -> tuple[int | None, int | None]:
    """从 table HTML 的 data-page-span 解析 0-based 起止页。"""
    match = re.search(r'data-page-span="([^"]+)"', html or "")
    if not match:
        return None, None
    raw = match.group(1).strip()
    if not raw:
        return None, None
    parts = raw.split("-")
    try:
        if len(parts) == 1:
            idx = int(parts[0])
            return idx, idx
        start = int(parts[0])
        end = int(parts[-1])
        return start, end
    except ValueError:
        return None, None


def count_table_cols(headers: list[str] | None, data_rows: list[list[str]] | None = None) -> int | None:
    if headers:
        return len(headers)
    if data_rows:
        return max((len(row) for row in data_rows), default=None)
    return None


class SectionStack:
    """维护标题栈，产出 full_section_path / parent_section / section_title。"""

    def __init__(self) -> None:
        self._stack: list[tuple[int, str]] = []

    def push(self, title: str, text_level: int | None = None) -> None:
        cleaned = (title or "").strip()
        if not cleaned:
            return
        level = resolve_title_level(cleaned, text_level=text_level, stack_depth=len(self._stack))
        while self._stack and self._stack[-1][0] >= level:
            self._stack.pop()
        self._stack.append((level, cleaned))

    def path(self) -> list[str]:
        return [title for _, title in self._stack]

    def parent(self) -> str | None:
        if len(self._stack) < 2:
            return None
        return self._stack[-2][1]

    def leaf(self) -> str | None:
        if not self._stack:
            return None
        return self._stack[-1][1]


def resolve_title_level(
    title: str,
    *,
    text_level: int | None = None,
    stack_depth: int = 0,
) -> int:
    """
    解析标题层级（用于章节栈）。

    优先级：
    1. 标题编号启发（如 1 / 1.1 / 4.2.1）——避免 MinerU 扁平 text_level 互顶
    2. 无编号时：栈空则视为文档根（level=0）；否则回退 text_level，再不行则栈深+1
    """
    inferred = _infer_title_level(title)
    if inferred is not None:
        return inferred
    if stack_depth == 0:
        return 0
    if text_level is not None:
        # 有根之后，避免把后续无编号标题全部压成与根同级（text_level=1）
        return max(int(text_level), 1)
    return stack_depth


def _infer_title_level(title: str) -> int | None:
    match = _TITLE_NUMBER.match(title.strip())
    if not match:
        return None
    return match.group(1).count(".") + 1


def build_doc_attr_metadata(
    base_metadata: dict[str, Any],
    *,
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
) -> dict[str, Any]:
    """从文档 metadata / 时间戳提取可透传字段。"""
    out: dict[str, Any] = {}
    for key in ("source", "category", "doc_version"):
        value = base_metadata.get(key)
        if value is not None and str(value).strip():
            out[key] = value if key != "doc_version" else str(value).strip()

    out["access_group"] = normalize_access_group(base_metadata.get("access_group"))

    create_time = base_metadata.get("create_time") or format_datetime(created_at)
    update_time = base_metadata.get("update_time") or format_datetime(updated_at)
    if create_time:
        out["create_time"] = create_time
    if update_time:
        out["update_time"] = update_time
    return out


def enrich_chunk_piece(
    piece: ChunkPiece,
    *,
    chunk_index: int,
    prev_chunk_index: int | None,
    next_chunk_index: int | None,
    chunk_overlap: int,
    page_num: int | None = None,
    page_end: int | None = None,
    bbox: list[float] | None = None,
    section_title: str | None = None,
    parent_section: str | None = None,
    full_section_path: list[str] | None = None,
    doc_attrs: dict[str, Any] | None = None,
) -> ChunkPiece:
    """为单个 chunk 写入通用企业字段（保留已有 table_* 等）。"""
    text = piece.chunk_text or ""
    metadata = dict(piece.metadata)
    metadata.pop("block_type", None)

    metadata["chunk_index"] = chunk_index
    metadata["char_count"] = len(text)
    metadata["token_count"] = estimate_token_count(text)
    metadata["chunk_overlap"] = max(0, int(chunk_overlap))
    metadata["prev_chunk_index"] = prev_chunk_index
    metadata["next_chunk_index"] = next_chunk_index
    metadata["has_protocol_code"] = detect_protocol_code(text)

    if page_num is not None:
        metadata["page_num"] = page_num
        end = page_end if page_end is not None else page_num
        metadata["page_end"] = end
        metadata["is_cross_page"] = end > page_num
    else:
        metadata["page_num"] = None
        metadata["page_end"] = None
        metadata["is_cross_page"] = False

    metadata["bbox"] = bbox

    path = list(full_section_path or [])
    metadata["full_section_path"] = path
    if section_title:
        metadata["section_title"] = section_title
    elif path:
        metadata["section_title"] = path[-1]
    if parent_section:
        metadata["parent_section"] = parent_section
    elif len(path) >= 2:
        metadata["parent_section"] = path[-2]
    else:
        metadata["parent_section"] = None

    if doc_attrs:
        for key, value in doc_attrs.items():
            if key in metadata and key in {"doc_id", "file_path"}:
                continue
            metadata[key] = value

    return ChunkPiece(chunk_text=text, metadata=metadata)


def finalize_pieces(
    pieces: list[ChunkPiece],
    *,
    configured_overlap: int,
    doc_attrs: dict[str, Any] | None = None,
) -> list[ChunkPiece]:
    """
    二次回填 index 链表，并补齐尚未 enrichment 的通用字段。

    若 piece 已带 page_num 等（切分阶段写入），则保留；否则仅补长度/链表等。
    """
    if not pieces:
        return []

    finalized: list[ChunkPiece] = []
    total = len(pieces)
    for index, piece in enumerate(pieces):
        meta = dict(piece.metadata)
        overlap = meta.get("chunk_overlap")
        if overlap is None:
            overlap = configured_overlap if total > 1 and meta.get("chunk_kind") != "table_rows" else 0
            # 表格装箱默认无 overlap
            if str(meta.get("chunk_kind", "")).startswith("table"):
                overlap = 0

        finalized.append(
            enrich_chunk_piece(
                piece,
                chunk_index=index,
                prev_chunk_index=None if index == 0 else index - 1,
                next_chunk_index=None if index == total - 1 else index + 1,
                chunk_overlap=int(overlap),
                page_num=meta.get("page_num"),
                page_end=meta.get("page_end"),
                bbox=meta.get("bbox"),
                section_title=meta.get("section_title"),
                parent_section=meta.get("parent_section"),
                full_section_path=meta.get("full_section_path"),
                doc_attrs=doc_attrs,
            )
        )
    return finalized
