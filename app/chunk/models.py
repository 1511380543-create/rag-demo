from dataclasses import dataclass, field
from typing import Any


@dataclass
class ChunkPiece:
    """切块中间结果，写入 rag_chunks 前的单片。"""

    chunk_text: str
    metadata: dict[str, Any] = field(default_factory=dict)


class EmptyChunkInputError(ValueError):
    """blocks 与 full_text 皆空，无法切块。"""
