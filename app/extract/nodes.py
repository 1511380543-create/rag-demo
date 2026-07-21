from dataclasses import dataclass, field
from typing import Any, Literal

NodeType = Literal["title", "paragraph", "list_item", "table"]


@dataclass
class ExtractNode:
    """抽取阶段内部节点，承接 MinerU 内容项与清洗链。"""

    text: str
    node_type: NodeType
    metadata: dict[str, Any] = field(default_factory=dict)
    node_id: str = ""
