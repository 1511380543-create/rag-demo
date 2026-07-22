from dataclasses import dataclass
from typing import Any, Literal

BlockType = Literal["title", "paragraph", "list_item", "table"]


@dataclass
class ContentBlock:
    """抽取后的有序内容块。"""

    block_type: BlockType
    order: int
    text: str | None = None
    html: str | None = None
    logical_table_id: str | None = None
    # 溯源：MinerU 页索引 0-based；切块据此写 page_num（1-based）
    page_idx: int | None = None
    # 可选页面坐标 [x0, y0, x1, y1]
    bbox: list[float] | None = None
    # 标题层级（MinerU text_level）；供切块构造 full_section_path
    text_level: int | None = None


@dataclass
class ExtractReport:
    """抽取统计报告（与 spec 08 / API ExtractReport 对齐）。"""

    element_count: int = 0
    dropped_elements: int = 0
    dropped_fragments: int = 0
    dropped_garbled: int = 0
    table_count: int = 0
    table_quality_failed: int = 0
    merged_continuations: int = 0
    title_count: int = 0
    paragraph_count: int = 0
    list_item_count: int = 0
    # 兼容旧字段名：等于 paragraph_count
    paragraph_block_count: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "element_count": self.element_count,
            "dropped_elements": self.dropped_elements,
            "dropped_fragments": self.dropped_fragments,
            "dropped_garbled": self.dropped_garbled,
            "table_count": self.table_count,
            "table_quality_failed": self.table_quality_failed,
            "merged_continuations": self.merged_continuations,
            "title_count": self.title_count,
            "paragraph_count": self.paragraph_count,
            "list_item_count": self.list_item_count,
            "paragraph_block_count": self.paragraph_block_count,
        }


@dataclass
class ExtractedDocument:
    """抽取结果，用于持久化。"""

    doc_id: str
    file_path: str
    extract_version: str
    page_count: int
    blocks: list[ContentBlock]
    full_text: str
    metadata: dict[str, Any] | None
    content_hash: str
    extract_report: ExtractReport

    @property
    def char_count(self) -> int:
        return len(self.full_text)
