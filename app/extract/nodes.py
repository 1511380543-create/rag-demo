from dataclasses import dataclass, field
from typing import Any


@dataclass
class ExtractNode:
    """抽取阶段内部节点，承接 Unstructured 元素与清洗链。"""

    text: str
    metadata: dict[str, Any] = field(default_factory=dict)
    node_id: str = ""
