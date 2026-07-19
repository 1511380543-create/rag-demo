import re
from typing import Any, Protocol

from app.extract.nodes import ExtractNode

TABLE_CATEGORY = "Table"
_HEADER_FOOTER_MAX_LEN = 30
_TOC_DOT_LINE = re.compile(r"^.{0,40}[\.·…\s]{3,}.{0,20}\d+\s*$")
_SENTENCE_END = re.compile(r"[。！？；.!?;:：]$")


class ExtractCleaner(Protocol):
    """抽取清洗器协议。"""

    def __call__(self, nodes: list[ExtractNode], **kwargs: Any) -> list[ExtractNode]:
        ...


def resolve_category(metadata: dict[str, Any]) -> str:
    category = metadata.get("category") or metadata.get("element_category") or ""
    return str(category).strip()


def is_table_node(node: ExtractNode) -> bool:
    return resolve_category(node.metadata) == TABLE_CATEGORY


class HeaderFooterCleaner:
    """去除跨页重复短文本（页眉页脚）。"""

    def __call__(self, nodes: list[ExtractNode], **kwargs: Any) -> list[ExtractNode]:
        text_counts: dict[str, int] = {}
        for node in nodes:
            if is_table_node(node):
                continue
            normalized = " ".join((node.text or "").split())
            if not normalized or len(normalized) > _HEADER_FOOTER_MAX_LEN:
                continue
            text_counts[normalized] = text_counts.get(normalized, 0) + 1

        repeated = {text for text, count in text_counts.items() if count >= 2}
        if not repeated:
            return nodes

        cleaned: list[ExtractNode] = []
        for node in nodes:
            if is_table_node(node):
                cleaned.append(node)
                continue
            normalized = " ".join((node.text or "").split())
            if normalized in repeated:
                continue
            cleaned.append(node)
        return cleaned


class TocCleaner:
    """跳过目录页模式内容。"""

    def __call__(self, nodes: list[ExtractNode], **kwargs: Any) -> list[ExtractNode]:
        cleaned: list[ExtractNode] = []
        for node in nodes:
            if is_table_node(node):
                cleaned.append(node)
                continue
            text = (node.text or "").strip()
            if not text:
                continue
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            if len(lines) >= 4:
                dot_lines = sum(1 for line in lines if _TOC_DOT_LINE.match(line))
                if dot_lines / len(lines) >= 0.6:
                    continue
            cleaned.append(node)
        return cleaned


class CnLineMergeCleaner:
    """合并中文 PDF 常见的不合理断行。"""

    def __call__(self, nodes: list[ExtractNode], **kwargs: Any) -> list[ExtractNode]:
        cleaned: list[ExtractNode] = []
        for node in nodes:
            if is_table_node(node):
                cleaned.append(node)
                continue
            merged = self._merge_lines(node.text or "")
            if merged != node.text:
                metadata = dict(node.metadata)
                cleaned.append(ExtractNode(text=merged, metadata=metadata, node_id=node.node_id))
            else:
                cleaned.append(node)
        return cleaned

    @staticmethod
    def _merge_lines(text: str) -> str:
        lines = text.splitlines()
        if len(lines) <= 1:
            return text.strip()

        merged_lines: list[str] = []
        buffer = ""
        for line in lines:
            stripped = line.strip()
            if not stripped:
                if buffer:
                    merged_lines.append(buffer)
                    buffer = ""
                continue
            if not buffer:
                buffer = stripped
                continue
            if _SENTENCE_END.search(buffer):
                merged_lines.append(buffer)
                buffer = stripped
            else:
                buffer = f"{buffer}{stripped}"
        if buffer:
            merged_lines.append(buffer)
        return "\n".join(merged_lines).strip()


class EmptyDropCleaner:
    """丢弃空元素。"""

    def __call__(self, nodes: list[ExtractNode], **kwargs: Any) -> list[ExtractNode]:
        cleaned: list[ExtractNode] = []
        for node in nodes:
            if is_table_node(node):
                html = str(node.metadata.get("table_html") or node.text or "").strip()
                if html:
                    cleaned.append(node)
                continue
            if (node.text or "").strip():
                cleaned.append(node)
        return cleaned


EXTRACT_CLEANERS: list[ExtractCleaner] = [
    HeaderFooterCleaner(),
    TocCleaner(),
    CnLineMergeCleaner(),
    EmptyDropCleaner(),
]
