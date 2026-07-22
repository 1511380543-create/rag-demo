"""将 MinerU content_list 项映射为内部 ExtractNode。"""

from __future__ import annotations

from html import escape
from typing import Any

from app.extract.nodes import ExtractNode, NodeType

# 本阶段丢弃的类型（计入 discarded_other）
_DROP_TYPES = {
    "image",
    "chart",
    "equation",
    "code",
    "header",
    "footer",
    "page_number",
    "aside_text",
    "page_footnote",
    "page_header",
    "page_footer",
    "page_aside_text",
}


def map_content_list_to_nodes(items: list[dict[str, Any]]) -> tuple[list[ExtractNode], int]:
    """
    MinerU → ExtractNode。

    返回 (nodes, discarded_other_count)。
    """
    nodes: list[ExtractNode] = []
    discarded = 0
    for index, item in enumerate(items):
        item_type = str(item.get("type") or "").strip().lower()
        if item_type in _DROP_TYPES:
            discarded += 1
            continue

        if item_type == "table":
            html = _build_table_html(item)
            if not html.strip():
                discarded += 1
                continue
            nodes.append(
                ExtractNode(
                    text=html,
                    node_type="table",
                    metadata={
                        "table_html": html,
                        "page_idx": _as_page_idx(item.get("page_idx")),
                        "bbox": _as_bbox(item.get("bbox")),
                        "table_caption": item.get("table_caption"),
                    },
                    node_id=f"table-{index}",
                )
            )
            continue

        if item_type == "list":
            list_nodes, list_discarded = _map_list_item(item, index)
            discarded += list_discarded
            nodes.extend(list_nodes)
            continue

        if item_type in {"text", "title", "paragraph"}:
            text = str(item.get("text") or "").strip()
            if not text:
                discarded += 1
                continue
            node_type = _resolve_text_type(item_type, item)
            meta: dict[str, Any] = {
                "page_idx": _as_page_idx(item.get("page_idx")),
                "bbox": _as_bbox(item.get("bbox")),
            }
            text_level = _as_text_level(item.get("text_level"))
            if text_level is not None:
                meta["text_level"] = text_level
            nodes.append(
                ExtractNode(
                    text=text,
                    node_type=node_type,
                    metadata=meta,
                    node_id=f"text-{index}",
                )
            )
            continue

        # 未知类型：丢弃
        discarded += 1

    return nodes, discarded


def _resolve_text_type(item_type: str, item: dict[str, Any]) -> NodeType:
    if item_type == "title":
        return "title"
    if item_type == "paragraph":
        return "paragraph"
    text_level = item.get("text_level")
    try:
        level = int(text_level) if text_level is not None else 0
    except (TypeError, ValueError):
        level = 0
    if level >= 1:
        return "title"
    return "paragraph"


def _map_list_item(item: dict[str, Any], index: int) -> tuple[list[ExtractNode], int]:
    list_items = item.get("list_items")
    nodes: list[ExtractNode] = []
    if isinstance(list_items, list) and list_items:
        for offset, entry in enumerate(list_items):
            text = _stringify_list_entry(entry).strip()
            if not text:
                continue
            nodes.append(
                ExtractNode(
                    text=text,
                    node_type="list_item",
                    metadata={
                        "page_idx": _as_page_idx(item.get("page_idx")),
                        "bbox": _as_bbox(item.get("bbox")),
                    },
                    node_id=f"list-{index}-{offset}",
                )
            )
        return nodes, 0 if nodes else 1

    # 部分版本把列表写成单条 text
    text = str(item.get("text") or "").strip()
    if text:
        return (
            [
                ExtractNode(
                    text=text,
                    node_type="list_item",
                    metadata={
                        "page_idx": _as_page_idx(item.get("page_idx")),
                        "bbox": _as_bbox(item.get("bbox")),
                    },
                    node_id=f"list-{index}",
                )
            ],
            0,
        )
    return [], 1


def _as_page_idx(value: Any) -> int | None:
    """规范化 MinerU page_idx（0-based）。"""
    try:
        if value is None:
            return None
        page_idx = int(value)
    except (TypeError, ValueError):
        return None
    return page_idx if page_idx >= 0 else None


def _as_bbox(value: Any) -> list[float] | None:
    """规范化 bbox 为长度为 4 的 float 列表。"""
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        return [float(v) for v in value]
    except (TypeError, ValueError):
        return None


def _as_text_level(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _stringify_list_entry(entry: Any) -> str:
    if isinstance(entry, str):
        return entry
    if isinstance(entry, dict):
        if "text" in entry:
            return str(entry.get("text") or "")
        if "content" in entry and isinstance(entry["content"], str):
            return entry["content"]
    return str(entry or "")


def _build_table_html(item: dict[str, Any]) -> str:
    body = str(item.get("table_body") or item.get("html") or "").strip()
    captions = item.get("table_caption") or []
    if isinstance(captions, str):
        captions = [captions]
    caption_text = " ".join(str(c).strip() for c in captions if str(c).strip())

    if not body:
        return ""

    # 已有 caption 则不强行再包一层
    if caption_text and "<caption" not in body.lower():
        safe_caption = escape(caption_text)
        lower = body.lower()
        pos = lower.find("<table")
        if pos >= 0:
            end = body.find(">", pos)
            if end >= 0:
                return body[: end + 1] + f"<caption>{safe_caption}</caption>" + body[end + 1 :]
        return (
            f"<table><caption>{safe_caption}</caption>"
            f"<tbody><tr><td>{escape(body)}</td></tr></tbody></table>"
        )
    return body
