from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class ContentBlock:
    """抽取后的有序内容块。"""

    block_type: Literal["paragraph", "table"]
    order: int
    text: str | None = None
    html: str | None = None
    logical_table_id: str | None = None


@dataclass
class ExtractReport:
    """抽取统计报告。"""

    element_count: int = 0
    dropped_elements: int = 0
    table_count: int = 0
    merged_continuations: int = 0
    paragraph_block_count: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "element_count": self.element_count,
            "dropped_elements": self.dropped_elements,
            "table_count": self.table_count,
            "merged_continuations": self.merged_continuations,
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
